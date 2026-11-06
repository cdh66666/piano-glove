"""Local original PDFs and review progress; no device operations."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading

PROGRESS_RULE_VERSION = 'editor-shared-progress-20261106-v2'


class WorkspaceStore:
    def __init__(self, root):
        self.root = Path(root) / 'workbench'
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Only scalar version/stat data, never a second retained score model.
        self._review_versions = {}
        self.progress_cache_revision = None
        self.progress_token_fn = None
        self.builtin_digests = set()

    def review_path(self, digest, scope=None):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('原谱编号不正确')
        digest = str(digest)
        if scope not in (None, '', 'builtin:' + digest, 'import:' + digest):
            raise ValueError('校对来源不正确')
        separate = scope == 'import:' + digest and digest in self.builtin_digests
        return self.root / (digest + ('.import.review.json' if separate else '.review.json'))

    def human_stats_key(self, digest, scope=None):
        separate = self.review_path(digest, scope).name.endswith('.import.review.json')
        return ('review-import:' if separate else 'review:') + str(digest)

    def progress_stats_key(self, digest, scope=None):
        self.review_path(digest, scope)
        return 'progress-v4:' + (scope or ('legacy:' + str(digest)))

    def progress_generation_key(self, digest, scope=None):
        self.review_path(digest, scope)
        return 'progress-generation-v2:' + (scope or ('legacy:' + str(digest)))

    def review_revision(self, digest, scope=None):
        path = self.review_path(digest, scope)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return str(stat.st_mtime_ns) + ':' + str(stat.st_size)

    def progress_generation(self, digest, scope=None):
        value = self.stats().get(self.progress_generation_key(digest, scope), 0)
        return value if type(value) is int and value >= 0 else 0

    def invalidate_current_progress(self, digest, scope=None):
        with self._lock:
            stats = self.stats()
            key = self.progress_generation_key(digest, scope)
            old = stats.get(key, 0)
            generation = (old if type(old) is int and old >= 0 else 0) + 1
            stats[key] = generation
            stats.pop(self.progress_stats_key(digest, scope), None)
            self._write(self.root / 'score-stats.json', stats)
            return generation

    @staticmethod
    def _clean_progress(value):
        if not isinstance(value, dict) or value.get('checking') is True:
            return None
        total, checked, unmatched = value.get('total'), value.get('checked'), value.get('unmatched', 0)
        if any(type(v) is not int for v in (total, checked, unmatched)) or not (0 <= checked <= total <= 1000000 and 0 <= unmatched <= 1000000):
            return None
        return dict(total=total, checked=checked, unmatched=unmatched)

    def record_current_progress(self, digest, scope, expected_revision, expected_generation, expected_cache_token, value):
        """Commit only a fully checked result for the exact saved review revision."""
        clean = self._clean_progress(value)
        if clean is None or not self.progress_cache_revision:
            raise ValueError('校对进度结果不完整')
        with self._lock:
            actual = self.review_revision(digest, scope)
            stats = self.stats()
            generation = stats.get(self.progress_generation_key(digest, scope), 0)
            if type(generation) is not int or generation < 0:
                generation = 0
            cache_token = self.progress_token_fn(digest, scope) if self.progress_token_fn else None
            if actual != expected_revision or expected_generation != generation or expected_cache_token != cache_token:
                return {'stored': False, 'revision': actual, 'generation': generation, 'cache_token': cache_token}
            stats[self.progress_stats_key(digest, scope)] = dict(clean, version=PROGRESS_RULE_VERSION,
                cache_revision=self.progress_cache_revision, review_revision=actual, generation=generation, cache_token=cache_token)
            self._write(self.root / 'score-stats.json', stats)
            return {'stored': True, 'revision': actual}

    def _write(self, path, value):
        temporary = path.with_suffix('.pending')
        # Keep atomic replacement, without retaining every encoder chunk plus
        # a joined multi-megabyte string and its UTF-8 copy at the same time.
        encoder=json.JSONEncoder(ensure_ascii=False,separators=(',',':'))
        def array(items):
            yield '['
            for i,item in enumerate(items):
                if i:yield ','
                yield encoder.encode(item)
            yield ']'
        def pieces():
            if isinstance(value,dict):
                yield '{'
                for i,(key,item) in enumerate(value.items()):
                    if i:yield ','
                    # Let the standard encoder handle every allowed key type.
                    yield encoder.encode({key:None})[1:-6]
                    yield ':'
                    if isinstance(item,list):yield from array(item)
                    else:yield encoder.encode(item)
                yield '}'
            elif isinstance(value,list):yield from array(value)
            else:yield encoder.encode(value)
        chunks=[];size=0
        with temporary.open('w',encoding='utf-8',newline='') as output:
            for chunk in pieces():
                chunks.append(chunk);size+=len(chunk)
                if size>=65536:
                    output.write(''.join(chunks));chunks.clear();size=0
            if chunks:output.write(''.join(chunks))
        temporary.replace(path)

    def remember(self, filename, content, expected_sha):
        data = base64.b64decode(content, validate=True)
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_sha:
            raise ValueError('原谱文件与识别结果不一致')
        with self._lock:
            (self.root / (digest + '.pdf')).write_bytes(data)
            self._write(self.root / (digest + '.source.json'), dict(id='import:'+digest, sha256=digest,
                filename=Path(filename).name, title=Path(filename).stem, bytes=len(data), bundled=False))

    def remember_bytes(self, filename, data):
        """Register an original PDF read from disk (native file picker); returns its digest."""
        if not data.startswith(b'%PDF-') or len(data) > 64 * 1024 * 1024:
            raise ValueError('不是 PDF 文件或超过 64MB：' + Path(filename).name)
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            (self.root / (digest + '.pdf')).write_bytes(data)
            self._write(self.root / (digest + '.source.json'), dict(id='import:'+digest, sha256=digest,
                filename=Path(filename).name, title=Path(filename).stem, bytes=len(data), bundled=False))
        return digest

    def forget(self, digest):
        """Remove an imported original from the list. Review progress is kept (re-import restores it)."""
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('原谱编号不正确')
        with self._lock:
            for suffix in ('.pdf', '.source.json'):
                path = self.root / (digest + suffix)
                if path.is_file():
                    path.unlink()
            stats = self.stats()
            if stats.pop('import:' + digest, None) is not None:
                self._write(self.root / 'score-stats.json', stats)
        return True

    def stats(self):
        """Per-score list numbers (pages, right-hand notes, still to fix). Small scalar data only."""
        path = self.root / 'score-stats.json'
        with self._lock:
            try:
                value = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            except (OSError, ValueError):
                value = {}
            return value if isinstance(value, dict) else {}

    def record_stats(self, score_id, values):
        score_id = str(score_id)
        if not re.fullmatch(r'(import:[0-9a-f]{64}|[A-Za-z0-9_-]{1,40})', score_id):
            raise ValueError('曲谱编号不正确')
        clean = {}
        for key in ('pages', 'notes', 'attention', 'questions', 'combined_total_v1', 'combined_checked_v1', 'combined_pending_v1', 'combined_groups_v1'):
            value = (values or {}).get(key)
            if type(value) is int and 0 <= value <= 1000000:
                clean[key] = value
        with self._lock:
            stats = self.stats()
            row = stats.get(score_id) if isinstance(stats.get(score_id), dict) else {}
            row.update(clean)
            stats[score_id] = row
            self._write(self.root / 'score-stats.json', stats)
        return row

    def stats_with_review_progress(self, digests):
        """Backfill actual saved-note counts once for older review files."""
        with self._lock:
            stats = self.stats()
            changed = False
            unavailable = {}
            for item in set(digests):
                digest, scope = item if isinstance(item, tuple) else (item, None)
                if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    continue
                key = self.human_stats_key(digest, scope)
                if isinstance(stats.get(key), dict):
                    continue
                path = self.review_path(digest, scope)
                if not path.is_file():
                    continue
                try:
                    review = json.loads(path.read_text(encoding='utf-8'))
                    if review.get('source_sha256') != digest or not isinstance(review.get('notes'), list):
                        raise ValueError('invalid review')
                    right = [n for n in review['notes'] if isinstance(n, dict) and n.get('hand') == 'right' and not n.get('excluded')]
                    stats[key] = dict(human_reviewed_notes_v1=sum(n.get('human_reviewed') is True for n in right),
                                      human_review_total_v1=len(right))
                    changed = True
                except (OSError, ValueError, UnicodeError, AttributeError):
                    unavailable[key] = {'human_progress_unavailable': True}
            if changed:
                self._write(self.root / 'score-stats.json', stats)
            return dict(stats, **unavailable)

    def preference(self, key, value=None):
        """Tiny UI preferences (e.g. last PDF folder)."""
        path = self.root / 'preferences.json'
        with self._lock:
            try:
                prefs = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            except (OSError, ValueError):
                prefs = {}
            if value is None:
                return prefs.get(key)
            prefs[key] = value
            self._write(path, prefs)
            return value

    def imports(self):
        with self._lock:
            return [json.loads(path.read_text(encoding='utf-8')) for path in self.root.glob('*.source.json')]

    def read_source(self, digest):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('原谱编号不正确')
        metadata = json.loads((self.root / (digest + '.source.json')).read_text(encoding='utf-8'))
        data = (self.root / (digest + '.pdf')).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('保存的原谱校验失败')
        return metadata, data

    def _cache_version(self, digest, path, recognizer):
        if recognizer is not None and (not isinstance(recognizer, str) or len(recognizer)>256):
            self._review_versions.pop(digest,None)
            return
        stat=path.stat()
        self._review_versions[digest]=((stat.st_ino,stat.st_size,stat.st_mtime_ns),recognizer)

    def _previous_version(self, digest, path):
        stat=path.stat();signature=(stat.st_ino,stat.st_size,stat.st_mtime_ns)
        cached=self._review_versions.get(digest)
        if cached is not None and cached[0]==signature:return cached[1]
        try:previous=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError):
            backup=self.root/(digest+'.before-unreadable.json')
            if not backup.exists():shutil.copyfile(path,backup)
            self._review_versions.pop(digest,None)
            return None
        recognizer=previous.get('recognizer')
        self._cache_version(digest,path,recognizer)
        return recognizer

    def save(self, state):
        # The public object API retains its defensive snapshot contract.
        return self._save_owned(deepcopy(state))

    def save_json(self, state_json):
        # pywebview owns this string, and json.loads creates one private tree.
        # It cannot subsequently be changed by the browser that sent it.
        if not isinstance(state_json,str):raise ValueError('校对快照不正确')
        value=json.loads(state_json)
        if not isinstance(value,dict):raise ValueError('校对快照不正确')
        return self._save_owned(value)

    def _save_owned(self, value):
        project = value.get('project')
        with self._lock:
            if project:
                digest = project.get('source_sha256')
                if not re.fullmatch(r'[0-9a-f]{64}', str(digest)) or not isinstance(project.get('notes'), list):
                    raise ValueError('校对项目不正确')
                project.pop('page_previews', None)
                scope=value.get('proof_scope') or None
                current=self.review_path(digest,scope)
                version_key=current.name[:-len('.review.json')]
                if current.is_file():
                    before=self._previous_version(version_key,current);after=project.get('recognizer')
                    if before and after and before!=after:
                        revision=re.sub(r'[^A-Za-z0-9_-]','_',str(before))[:80]
                        backup=self.root / (version_key + '.before-' + revision + '.json')
                        if not backup.exists():
                            shutil.copyfile(current,backup)
                self._write(current, project)
                self._cache_version(version_key,current,project.get('recognizer'))
                # A review count is based only on explicit human marks in the
                # saved project, never on automatic recognition or old curation.
                right = [n for n in project['notes'] if isinstance(n, dict) and n.get('hand') == 'right' and not n.get('excluded')]
                stats = self.stats()
                stats[self.human_stats_key(digest,scope)] = dict(human_reviewed_notes_v1=sum(n.get('human_reviewed') is True for n in right),
                                                               human_review_total_v1=len(right))
                progress = self._clean_progress(value.get('proof_progress'))
                generation = stats.get(self.progress_generation_key(digest, scope), 0)
                if type(generation) is not int or generation < 0:
                    generation = 0
                cache_token = self.progress_token_fn(digest, scope) if self.progress_token_fn else None
                if progress is not None and not project.get('validation_pending') and not project.get('validation_error') and self.progress_cache_revision and value.get('proof_generation') == generation and value.get('proof_cache_token') == cache_token:
                    stats[self.progress_stats_key(digest,scope)] = dict(progress, version=PROGRESS_RULE_VERSION,
                        cache_revision=self.progress_cache_revision, review_revision=self.review_revision(digest,scope), generation=generation, cache_token=cache_token)
                self._write(self.root / 'score-stats.json', stats)
            else:
                previous = self.last()
                digest = previous.get('source_sha256')
                scope = previous.get('review_scope')
            last = dict(source_sha256=digest, ui=value.get('ui') or {})
            if scope:last['review_scope'] = scope
            self._write(self.root / 'last.json', last)
        return {'saved': True}

    def review(self, digest, scope=None):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            return None
        path = self.review_path(digest,scope)
        with self._lock:
            if not path.is_file():return None
            value=json.loads(path.read_text(encoding='utf-8'))
            self._cache_version(path.name[:-len('.review.json')],path,value.get('recognizer'))
            return value

    def last(self):
        path = self.root / 'last.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

    def stage(self, files):
        with self._lock:
            self._write(self.root / 'drop-queue.json', files)
        return True

    def _staged_path(self, session=None):
        if session is None:
            return self.root / 'drop-queue.json'
        if not isinstance(session, str) or not re.fullmatch(r'[0-9a-f]{32}', session):
            raise ValueError('导入会话不正确')
        return self.root / ('drop-queue-' + session + '.json')

    def append_staged(self, files, session=None):
        """Keep rapid successive drops when the software page is still opening."""
        with self._lock:
            path = self._staged_path(session)
            old = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
            if not isinstance(old, list):
                raise ValueError('待导入文件队列不正确')
            self._write(path, old + list(files))
        return True

    def take_staged(self, session=None):
        with self._lock:
            path = self._staged_path(session)
            if not path.exists():
                return []
            files = json.loads(path.read_text(encoding='utf-8'))
            path.unlink()
            return files
