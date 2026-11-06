"""Original documents and historical score packages.

Historical curation flags are retained for file compatibility, but do not
establish independent human verification or recognition accuracy.
"""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import threading
from conversion_progress import notify
from workspace_store import PROGRESS_RULE_VERSION


HOLDOUT_IDS = frozenset(('1007271', '1003497', '969886'))


class ScoreCacheMissing(Exception):
    """No current recognition is available without processing the PDF."""


class ScoreCatalog:
    def __init__(self, root=None, cache_root=None, fallback_cache_root=None, prefer_fallback=False):
        self.root = Path(root or Path(__file__).resolve().parent / 'assets' / 'score-library')
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        self._entries = {entry['id']: entry for entry in self.manifest['scores']}
        if len(self._entries) != len(self.manifest['scores']):
            raise ValueError('内置原谱目录编号重复')
        self.cache_root = Path(cache_root) if cache_root is not None else (
            Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'PianoGloveSoftware' / 'score-catalog')
        self.fallback_cache_root = tuple(Path(p) for p in fallback_cache_root) if isinstance(fallback_cache_root, (list, tuple)) else Path(fallback_cache_root) if fallback_cache_root is not None else None
        self.prefer_fallback = bool(prefer_fallback)
        self._lock = threading.RLock()
        curated = self.root / 'curation-manifest.json'
        self._curated = {row['id']: row for row in json.loads(curated.read_text(encoding='utf-8')).get('entries', [])} if curated.is_file() else {}
        baseline_path = self.root / 'proof-baseline.json'
        try:
            baseline = json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.is_file() else {}
            self._proof_baselines = baseline.get('scores', {}) if baseline.get('version') == 1 and baseline.get('cache_revision') == self.manifest.get('cache_revision') else {}
            if not isinstance(self._proof_baselines, dict):
                self._proof_baselines = {}
        except (OSError, ValueError, AttributeError):
            self._proof_baselines = {}
        current_path = self.root / 'proof-current.json'
        try:
            current = json.loads(current_path.read_text(encoding='utf-8')) if current_path.is_file() else {}
            self._proof_current = current.get('scores', {}) if current.get('version') == PROGRESS_RULE_VERSION and current.get('cache_revision') == self.manifest.get('cache_revision') else {}
            if not isinstance(self._proof_current, dict):
                self._proof_current = {}
        except (OSError, ValueError, AttributeError):
            self._proof_current = {}

    def list(self, include_holdouts=False):
        rows = [dict(deepcopy(entry), playable=False) for entry in self._entries.values()
                if include_holdouts or entry['bundled']]
        for entry in rows:
            baseline = self._proof_baselines.get(entry.get('sha256'))
            if isinstance(baseline, dict):
                total, pending, groups = (baseline.get(k) for k in ('total', 'pending_notes', 'question_groups'))
                if all(type(v) is int for v in (total, pending, groups)) and 0 <= pending <= total <= 1000000 and 0 <= groups <= pending:
                    entry['proof_baseline'] = dict(total=total, checked=total-pending, pending=pending,
                                                   groups=groups, basis='上次软件预检')
            current = self._proof_current.get(entry.get('sha256'))
            if isinstance(current, dict):
                total, checked, recognition_hash = current.get('total'), current.get('checked'), current.get('recognition_hash')
                if type(total) is int and type(checked) is int and 0 <= checked <= total <= 1000000 and isinstance(recognition_hash, str) and re.fullmatch(r'[0-9a-f]{64}', recognition_hash):
                    entry['proof_current_default'] = dict(total=total, checked=checked, unmatched=0, recognition_hash=recognition_hash)
        return rows

    def _ready(self, score_id):
        entry = self._entries.get(str(score_id), {})
        record = self._curated.get(str(score_id), {})
        return record if (entry.get('bundled') and record.get('status') == 'reviewed-complete'
                          and record.get('full_source_coverage') is True and not record.get('unresolved_items')
                          and record.get('source_sha256') == entry.get('sha256')) else None

    def package(self, score_id):
        record = self._ready(score_id)
        if not record:
            raise ValueError('没有可用的历史曲谱包，请先转换并检查原谱')
        data = (self.root / record['pglpack']).read_bytes()
        if hashlib.sha256(data).hexdigest() != record['package_sha256']:
            raise ValueError('内置曲谱包校验失败')
        self.read(score_id)
        return dict(name=self.get(score_id)['title']+'.pglpack', base64=base64.b64encode(data).decode('ascii'),
                    score_sha256=record['score_sha256'], notes=record['played_right_events'])

    def get(self, score_id):
        try:
            return deepcopy(self._entries[str(score_id)])
        except KeyError:
            raise KeyError('没有这份内置原谱：' + str(score_id)) from None

    def read(self, score_id):
        entry = self.get(score_id)
        if not entry['bundled']:
            raise FileNotFoundError('这份原谱留作手动导入，不在内置目录中：' + entry['title'])
        data = (self.root / entry['file']).read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('内置原谱校验失败：' + entry['title'])
        return data

    def project(self, score_id, bpm=120, converter=None, force=False, cached_only=False):
        """Return an independent project; authored sources bypass OMR entirely.

        PDF cache identity includes original bytes and parser revision. Tempo
        is applied without repeating PDF recognition. These raw PDF caches never
        contain user review and cannot approve notes for export. Human-authored
        projects retain their explicit manual provenance and reviewed fields.
        """
        entry = self.get(score_id)
        data = self.read(score_id)  # Verify bundled bytes even on a cache hit.
        if entry.get('source_kind') == 'manual':
            return self._manual_project(entry, bpm)
        return self._project(entry, data, bpm, converter, force, cached_only)

    def _manual_project(self, entry, bpm):
        """Open an authored project; a refresh never sends its image to OMR."""
        if type(bpm) not in (int, float) or not 10 <= bpm <= 240 or int(bpm) != bpm:
            raise ValueError('BPM须为10至240')
        if not entry.get('manual_project') or not entry.get('manual_project_sha256'):
            raise ValueError('人工曲谱项目文件未配置')
        blob = (self.root / entry['manual_project']).read_bytes()
        if hashlib.sha256(blob).hexdigest() != entry['manual_project_sha256']:
            raise ValueError('人工曲谱项目校验失败')
        project = json.loads(blob)
        if not isinstance(project, dict) or not isinstance(project.get('notes'), list):
            raise ValueError('人工曲谱项目格式不正确')
        if project.get('source_sha256') != entry['sha256']:
            raise ValueError('人工曲谱项目与原件不一致')
        if project.get('source_kind') not in (None, 'manual'):
            raise ValueError('人工曲谱项目来源类型不一致')
        for note in project['notes']:
            note.pop('human_reviewed', None)
        project.update(source_kind='manual', recognition_performed=False, manual_review_import=True)
        project.setdefault('name', entry['title'])
        project.setdefault('source_name', entry['filename'])
        project.setdefault('selection', {}).update(bpm=int(bpm))
        return project

    def imported_project(self, filename, data, bpm=120, converter=None, force=False, cached_only=False):
        """Cache imported originals separately from the user's saved edits."""
        entry = dict(filename=filename, sha256=hashlib.sha256(data).hexdigest())
        project = self._project(entry, data, bpm, converter, force, cached_only)
        project['source_name'] = filename
        return project

    def _project(self, entry, data, bpm, converter, force, cached_only=False):
        if type(bpm) not in (int, float) or not 10 <= bpm <= 240 or int(bpm) != bpm:
            raise ValueError('BPM须为10至240')
        bpm = int(bpm)
        # Recognition and page rendering do not depend on playback tempo. Keep
        # the historical 120-BPM key so the bundled raw projects remain reusable.
        identity = '|'.join((entry['sha256'], self.manifest['cache_revision'], '120.0'))
        key = hashlib.sha256(identity.encode('ascii')).hexdigest()
        path = self.cache_root / (key + '.json')
        notify("cache",label="检查已保存识别")
        with self._lock:
            project = None
            roots = self.fallback_cache_root if isinstance(self.fallback_cache_root, tuple) else (self.fallback_cache_root,) if self.fallback_cache_root is not None else ()
            alternates = [root / (key + '.json') for root in roots]
            candidates = [*alternates, path] if self.prefer_fallback else [path, *alternates]
            for candidate in candidates if not force else []:
                if candidate is None:
                    continue
                try:
                    cached = json.loads(candidate.read_text(encoding='utf-8')) if candidate.is_file() else None
                    if isinstance(cached, dict) and cached.get('source_sha256') == entry['sha256'] and isinstance(cached.get('notes'), list):
                        project = cached
                        break
                except (OSError, ValueError, AttributeError):
                    pass
            bundled_index = self.root / 'precomputed.json'
            cache_hit = project is not None
            if not force and project is None and bundled_index.is_file():
                index = json.loads(bundled_index.read_text(encoding='utf-8'))
                record = index.get('projects', {}).get(key) if index.get('cache_revision') == self.manifest['cache_revision'] else None
                if record:
                    blob = (self.root / record['file']).read_bytes()
                    if hashlib.sha256(blob).hexdigest() != record['sha256']:
                        raise ValueError('内置识别数据校验失败')
                    cached = json.loads(blob)
                    if cached.get('source_sha256') == entry['sha256']:
                        project = cached
            if project is None:
                if cached_only:
                    raise ScoreCacheMissing('尚无可用的当前识别结果')
                if converter is None:
                    from bridge import SoftwareConsole
                    converter = lambda payload: SoftwareConsole(None).convert(payload)['project']
                project = deepcopy(converter(dict(filename=entry['filename'], bpm=bpm,
                    base64=base64.b64encode(data).decode('ascii'))))
                if project.get('source_sha256') != entry['sha256']:
                    raise ValueError('识别结果与内置原谱不一致')
            for note in project.get('notes', []):
                note['confirmed'] = False
                note.pop('human_reviewed', None)
            project.setdefault('selection', {}).update(bpm=bpm, range_reviewed=False)
            project.setdefault('report', {}).update(requires_review=True, ready=False)
            if not cache_hit and not cached_only:
                notify("cache",label="保存识别缓存")
                self.cache_root.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix('.pending')
                temporary.write_text(json.dumps(project, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
                temporary.replace(path)
            # Each branch above already owns its project: JSON decoding creates
            # a new tree and the converter result is copied on entry.  Copying
            # this large tree again delayed every cached opening considerably.
            return project


def build_catalog(source_root, bundle_root, manual_root, reviewed=None, cache_revision='1'):
    """Reproduce the bundle from the retained original-download manifest.

    This build helper verifies the original manifest and real page counts before
    copying. Reports, generated comparison PDFs and unrelated folders are never
    searched into the bundle. Existing differing destinations are not replaced.
    """
    from pypdf import PdfReader
    source_root, bundle_root, manual_root = map(Path, (source_root, bundle_root, manual_root))
    source_manifest = source_root / 'downloads-manifest.json'
    originals = json.loads(source_manifest.read_text(encoding='utf-8-sig'))
    records, seen = [], set()
    for original in sorted(originals, key=lambda item: item['name']):
        source = source_root / 'samples' / original['name']
        data = source.read_bytes()
        digest, pages = hashlib.sha256(data).hexdigest(), len(PdfReader(BytesIO(data)).pages)
        if (digest, len(data), pages) != (original['sha256'], original['bytes'], original['pages']):
            raise ValueError('原始下载清单不匹配：' + source.name)
        if digest in seen:
            continue
        seen.add(digest)
        numeric = re.match(r'^(\d+)_', source.name)
        score_id = numeric[1] if numeric else 'scan-' + digest[:12]
        title = re.sub(r'^\d+_9_', '', source.stem).split('_五线')[0].rstrip('_')
        bundled = score_id not in HOLDOUT_IDS
        filename = score_id + '.pdf' if bundled else None
        destination = bundle_root / filename if bundled else manual_root / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError('目标已有不同文件，未覆盖：' + str(destination))
        if not destination.exists():
            shutil.copyfile(source, destination)
        records.append(dict(id=score_id, title=title, filename=source.name, pages=pages, bytes=len(data),
            sha256=digest, bundled=bundled, file=filename, reviewed_conversion=deepcopy((reviewed or {}).get(score_id))))
    if not HOLDOUT_IDS.issubset({entry['id'] for entry in records}):
        raise ValueError('原始清单缺少预留的三份手动测试原谱')
    manifest = dict(schema_version=1, source='retained-chat-original-pdfs',
        source_manifest_sha256=hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        cache_revision=cache_revision, total=len(records), pages=sum(entry['pages'] for entry in records),
        bundled_count=sum(entry['bundled'] for entry in records),
        holdout_ids=sorted(HOLDOUT_IDS), scores=records)
    (bundle_root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest
