"""Native desktop window. Device requests stay in process; no HTTP listener."""
import base64
from io import BytesIO
import json
import hashlib
import math
import os
import secrets
from pathlib import Path
import re
import threading
import time

import customer_runtime as runtime
from native_api import NativeAPI
from score_catalog import ScoreCatalog, ScoreCacheMissing
from workspace_store import WorkspaceStore, PROGRESS_RULE_VERSION
from conversion_progress import listen as listen_conversion_progress, notify as notify_conversion_progress

PAGES = {'software': 'software.html', 'debug': 'web_piano_glove.html',
         'guide': 'guide.html', 'licenses': 'guide.html'}


def dropped_pdf_path(uri):
    """Resolve a local file: PDF navigation without accepting web URLs."""
    from urllib.parse import urlsplit
    from urllib.request import url2pathname
    try:
        parsed = urlsplit(str(uri))
        if parsed.scheme.lower() != 'file':
            return None
        if re.fullmatch(r'[A-Za-z]:', parsed.netloc):
            raw = '/' + parsed.netloc + parsed.path
        else:
            raw = ('//' + parsed.netloc + parsed.path) if parsed.netloc and parsed.netloc.lower() != 'localhost' else parsed.path
        path = Path(url2pathname(raw))
        return path if path.suffix.lower() == '.pdf' else None
    except (ValueError, TypeError):
        return None


def install_pdf_navigation_guard(api, edge_class=None):
    """Keep an accidental file drop from replacing the whole WebView window."""
    if edge_class is None:
        from webview.platforms.edgechromium import EdgeChrome
        edge_class = EdgeChrome
    original = edge_class.on_navigation_start
    if getattr(original, '_piano_pdf_guard', False):
        return
    original_completed = getattr(edge_class, 'on_navigation_completed', None)
    def guarded(edge, sender, args):
        path = dropped_pdf_path(getattr(args, 'Uri', ''))
        if path is not None:
            navigation_id = getattr(args, 'NavigationId', None)
            if navigation_id is None:
                edge._piano_pdf_cancelled_without_id = True
            else:
                cancelled = getattr(edge, '_piano_cancelled_pdf_ids', None)
                if cancelled is None:
                    cancelled = set()
                    edge._piano_cancelled_pdf_ids = cancelled
                cancelled.add(int(navigation_id))
            args.Cancel = True
            threading.Thread(target=api._accept_native_pdf_drop, args=(path,), name='glove-pdf-drop', daemon=True).start()
            return
        return original(edge, sender, args)
    guarded._piano_pdf_guard = True
    edge_class.on_navigation_start = guarded
    if original_completed is not None:
        def guarded_completed(edge, sender, args):
            navigation_id = getattr(args, 'NavigationId', None)
            cancelled = getattr(edge, '_piano_cancelled_pdf_ids', set())
            if navigation_id is not None and int(navigation_id) in cancelled:
                cancelled.discard(int(navigation_id))
                return
            if navigation_id is None and getattr(edge, '_piano_pdf_cancelled_without_id', False) and getattr(args, 'IsSuccess', True) is False:
                edge._piano_pdf_cancelled_without_id = False
                return
            return original_completed(edge, sender, args)
        edge_class.on_navigation_completed = guarded_completed


def configure_background_polling():
    # WebView2 otherwise reduces hidden/occluded window timers to ~1 Hz, below
    # the measured feedback cadence required by calibration and link monitoring.
    key = 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'
    existing = os.environ.get(key, '')
    flags = ('--disable-background-timer-throttling', '--disable-renderer-backgrounding',
             '--disable-backgrounding-occluded-windows')
    missing = [flag for flag in flags if flag not in existing.split()]
    os.environ[key] = ' '.join(part for part in (existing, ' '.join(missing)) if part)


def render_page(page, root=None):
    """Inline trusted bundled assets into a stable file-origin application page."""
    root = Path(root or runtime.resources())
    text = (root / PAGES[page]).read_text(encoding='utf-8-sig')
    def asset(name):
        return (root / name.split('?', 1)[0].lstrip('/')).read_text(encoding='utf-8-sig')
    # Collect real stylesheet nodes before scripts are inlined. Parsing HTML,
    # rather than matching <style> text, leaves JavaScript templates untouched.
    from html.parser import HTMLParser
    class Styles(HTMLParser):
        def __init__(self, source):
            super().__init__(convert_charrefs=False)
            self.source, self.spans, self.active = source, [], None
            self.offsets = [0]
            for line in source.splitlines(keepends=True):
                self.offsets.append(self.offsets[-1] + len(line))
        def position(self):
            line, column = self.getpos()
            return self.offsets[line - 1] + column
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            start = self.position()
            end = start + len(self.get_starttag_text())
            if tag == 'style':
                self.active = (start, end)
            elif tag == 'link' and values.get('rel') == 'stylesheet':
                self.spans.append((start, end, asset(values['href'])))
        def handle_endtag(self, tag):
            if tag == 'style' and self.active:
                start, content = self.active
                end = self.position()
                self.spans.append((start, self.source.index('>', end) + 1, self.source[content:end]))
                self.active = None
    styles = Styles(text)
    styles.feed(text)
    for start, end, _ in reversed(styles.spans):
        text = text[:start] + text[end:]
    text = text.replace('</head>', ''.join('<style>\n'+css+'\n</style>' for _, _, css in styles.spans)+'</head>', 1)
    def script(match):
        return '<script>\n' + asset(match[1]).replace('</script', '<\\/script') + '\n</script>'
    text = re.sub(r'<script\s+src="([^"]+)"\s*></script>', script, text)
    text = re.sub(r'<link\b(?=[^>]*rel="stylesheet")[^>]*href="([^"]+)"[^>]*>',
                  lambda m: '<style>\n'+asset(m[1])+'\n</style>', text)
    text = text.replace('</head>', '<script>\n'+asset('native-transport.js')+'\n</script></head>', 1)
    text = re.sub(r'<body([^>]*)>', r'<body class="native-app" data-page="'+page+r'"\1>', text, count=1)
    if page != 'software':
        text = text.replace('</head>', '<style>'+asset('comic-pages.css')+'</style></head>', 1)
    if page == 'software':
        text = text.replace('</head>', '<style>'+asset('usb-driver.css')+'</style><style>'+asset('desktop-ui.css')+'</style></head>', 1)
        text = text.replace('</head>', '<style>'+asset('desktop-catalog.css')+'</style><style>'+asset('comic-ui.css')+'</style></head>', 1)
        text = text.replace('</body>', '<script>'+asset('usb-driver.js')+'</script><script>'+asset('desktop-shell.js')+'</script><script>'+asset('native-catalog.js')+'</script><script>'+asset('comic-art.js')+'</script><script>'+asset('comic-shell.js')+'</script><script>'+asset('comic-guide.js')+'</script><script>'+asset('proof-coach.js')+'</script><script>'+asset('score-list.js')+'</script><script>'+asset('reading-lesson.js')+'</script></body>', 1)
    elif page == 'debug':
        text = text.replace('<html ', '<html class="native-preparing" ', 1)
        text = text.replace('</head>', '<style>html.native-preparing,html.native-preparing body{background:#E5EBF1!important}html.native-preparing body>*{visibility:hidden!important}html.native-preparing body::after{content:"正在打开调手套…";position:fixed;inset:45% 0 auto;text-align:center;color:#52687C;font:14px "Microsoft YaHei UI",sans-serif}</style></head>', 1)
        text = text.replace('  bridgeBases(){', "  bridgeBases(){ if(window.NativeApp)return [''];")
        # WebView2 normalizes '?' in file URIs as part of the filename. Bake the
        # existing simple-mode flag into this trusted desktop-only document.
        text = re.sub(r'new URLSearchParams\(location\.search\)\.get\(([\'"])simple\1\)', "'1'", text)
        text = text.replace('</body>', '<script>NativeApp.addBackButton();const bootBack=document.getElementById("native-back");if(bootBack){bootBack.style.setProperty("display","block","important");bootBack.style.setProperty("visibility","visible","important");}</script></body>', 1)
    else:
        text = text.replace('</body>', '<script>NativeApp.addBackButton();</script><script>'+asset('comic-art.js')+'</script><script>document.querySelector(".intro")?.insertAdjacentHTML("afterbegin",ComicArt.mascot("happy","小音"));</script></body>', 1)
    def image(match):
        name = match[2].split('?', 1)[0].lstrip('/')
        path = root / name
        if not path.is_file() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.svg', '.webp'):
            return match[0]
        mime = {'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.svg':'image/svg+xml','.webp':'image/webp'}[path.suffix.lower()]
        return match[1]+'="data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')+'"'
    return re.sub(r'(src)="(/?assets/[^"]+)"', image, text)


def page_path(page, root=None):
    folder = runtime.data_directory() / 'interface'
    folder.mkdir(exist_ok=True)
    output = folder / (page + '.html')
    output.write_text(render_page(page, root), encoding='utf-8')
    uri = output.as_uri()
    if page == 'debug':
        uri += '#connect'
    elif page == 'licenses':
        uri += '#licenses'
    return uri



def _review_edits_only(review):
    """11-05 用户：点「校对」打开太慢。上次的进度只传前端合并要用的部分：
    改过的音（确认/手动字段/排除/手动补录/特殊记号改动/“就这样弹”/连线）、没对上的旧修改和几个设置，
    不再把整份曲谱再传一遍（大曲子能省一半）。前端合并规则见 software.js acceptRecognized。"""
    if not isinstance(review, dict):
        return review
    def edited(n):
        return bool(n.get('human_reviewed') is True or n.get('confirmed') or n.get('manual_fields') or n.get('excluded') or n.get('excluded_manual')
                    or str(n.get('id', '')).startswith('manual-') or n.get('performance_override')
                    or n.get('start_estimate_ok') is not None or 'tie_to' in n or 'tie_reviewed' in n)
    keep = {k: review[k] for k in ('source_sha256', 'name', 'selection', 'performance_policy', 'manual_review_import',
                                   'unmatched_review_notes', 'recognizer') if k in review}
    keep['notes'] = [n for n in review.get('notes') or [] if isinstance(n, dict) and edited(n)]
    return keep

class DesktopAPI(NativeAPI):
    def __init__(self, session):
        super().__init__(session)
        self._window = None
        self._application_session_id = secrets.token_hex(16)
        self._workspace = WorkspaceStore(runtime.data_directory())
        catalog_root = runtime.resources() / 'assets' / 'score-library'
        main_cache = runtime.data_directory() / 'score-catalog'
        progress_cache = runtime.data_directory() / 'score-progress-catalog'
        import_cache = runtime.data_directory() / 'score-import-catalog'
        import_progress_cache = runtime.data_directory() / 'score-import-progress-catalog'
        self._catalog = ScoreCatalog(catalog_root, main_cache, progress_cache)
        self._progress_catalog = ScoreCatalog(catalog_root, progress_cache, main_cache, prefer_fallback=True)
        self._import_catalog = ScoreCatalog(catalog_root, import_cache, (main_cache, import_progress_cache))
        self._progress_import_catalog = ScoreCatalog(catalog_root, import_progress_cache, (import_cache, main_cache), prefer_fallback=True)
        self._workspace.builtin_digests = {str(e.get('sha256')) for e in self._catalog.manifest['scores'] if e.get('bundled')}
        self._workspace.progress_cache_revision = self._catalog.manifest['cache_revision']
        self._workspace.progress_token_fn = self._progress_cache_token
        seed_location = os.environ.get('PIANO_GLOVE_PROGRESS_SEED')
        seed_path = Path(seed_location) if seed_location else runtime.data_directory() / 'score-progress-seed-v1.json'
        try:
            seed = json.loads(seed_path.read_text(encoding='utf-8')) if seed_path.is_file() else {}
            self._progress_seed = seed.get('scores', {}) if seed.get('version') == PROGRESS_RULE_VERSION and seed.get('cache_revision') == self._catalog.manifest['cache_revision'] else {}
            self._progress_seed_scoped = seed.get('scoped_scores', {}) if seed.get('version') == PROGRESS_RULE_VERSION and seed.get('cache_revision') == self._catalog.manifest['cache_revision'] else {}
            if not isinstance(self._progress_seed, dict):
                self._progress_seed = {}
            if not isinstance(self._progress_seed_scoped, dict):
                self._progress_seed_scoped = {}
        except (OSError, ValueError, AttributeError):
            self._progress_seed = {}
            self._progress_seed_scoped = {}
        self._session_opened = False  # a score was opened since this program started
        self._conversion_progress_lock = threading.Lock()
        self._conversion_progress = {}
        self._progress_cache_lock = threading.RLock()
        self._progress_cache_index = None
        self._baseline_hash_cache = {}
        self._drop_switch_lock = threading.Lock()
        self._drop_switch_pending = False
        self._close_lock = threading.Lock()
        self._close_pending = False
        self._close_approved = False
        self._close_error = None

    def application_session_id(self):
        """Stable across page changes, new for each launched program."""
        return self._application_session_id

    def _progress_cache_location(self, digest, scope=None):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('原谱编号不正确')
        identity = '|'.join((str(digest), self._catalog.manifest['cache_revision'], '120.0'))
        key = hashlib.sha256(identity.encode('ascii')).hexdigest() + '.json'
        folders = (('import', self._import_catalog.cache_root), ('main', self._catalog.cache_root), ('import-progress', self._progress_import_catalog.cache_root)) if scope == 'import:' + str(digest) else (('main', self._catalog.cache_root), ('progress', self._progress_catalog.cache_root))
        for label, folder in folders:
            try:
                path = folder / key
                stat = path.stat()
                return path, label + ':' + str(stat.st_mtime_ns) + ':' + str(stat.st_size)
            except FileNotFoundError:
                continue
            except OSError:
                return None, 'unavailable'
        return None, 'none'

    def _progress_cache_token(self, digest, scope=None):
        return self._progress_cache_location(digest, scope)[1]

    def _baseline_cache_matches(self, digest, scope, expected_hash):
        path, token = self._progress_cache_location(digest, scope)
        if token == 'none':
            return True
        if path is None or token == 'unavailable':
            return False
        key = (str(digest), scope, token, expected_hash)
        with self._progress_cache_lock:
            if key in self._baseline_hash_cache:
                return self._baseline_hash_cache[key]
            try:
                with path.open('rb') as source:
                    matched = hashlib.file_digest(source, 'sha256').hexdigest() == expected_hash
                matched = matched and self._progress_cache_token(digest, scope) == token
            except OSError:
                matched = False
            self._baseline_hash_cache[key] = matched
            return matched

    @staticmethod
    def _progress_scope(score_id, digest):
        return ('import:' if str(score_id).startswith('import:') else 'builtin:') + str(digest)

    def request(self, path, method='GET', body=None, raw=False, headers=None):
        reply = super().request(path, method, body, raw, headers)
        if path == '/api/software/convert' and str(method).upper() == 'POST' and reply['status'] == 200:
            payload = json.loads(body) if isinstance(body, str) else body
            project = reply['body'].get('project')
            if project:
                self._session_opened = True
                self._workspace.remember(payload['filename'], payload['base64'], project['source_sha256'])
        return reply

    def catalog_list(self):
        builtins = self._catalog.list()
        imports = self._workspace.imports()
        stats = self._workspace.stats_with_review_progress((entry.get('sha256'), self._progress_scope(entry['id'], entry.get('sha256'))) for entry in builtins + imports)
        for entry in builtins + imports:
            measured = stats.get(str(entry['id']))
            if isinstance(measured, dict):
                entry['stats'] = dict(entry.get('stats') or {}, **measured)
            scope = self._progress_scope(entry['id'], entry.get('sha256'))
            separate_import = scope.startswith('import:') and entry.get('sha256') in self._workspace.builtin_digests
            human = stats.get(self._workspace.human_stats_key(entry.get('sha256'), scope))
            if isinstance(human, dict):
                entry['stats'] = dict(entry.get('stats') or {}, **human)
            try:
                revision = self._workspace.review_revision(entry.get('sha256'), scope)
            except (OSError, ValueError):
                revision = 'unavailable'
            entry['proof_revision'] = revision
            entry['proof_scope'] = scope
            if separate_import and revision is None:
                entry['legacy_shared_review'] = self._workspace.review_path(entry.get('sha256'), 'builtin:' + str(entry.get('sha256'))).is_file()
            generation = stats.get(self._workspace.progress_generation_key(entry.get('sha256'), scope), 0)
            if type(generation) is not int or generation < 0:
                generation = 0
            entry['proof_generation'] = generation
            cache_token = self._progress_cache_token(entry.get('sha256'), scope)
            entry['proof_cache_token'] = cache_token
            current = stats.get(self._workspace.progress_stats_key(entry.get('sha256'), scope))
            clean = self._workspace._clean_progress(current)
            if (clean is not None and isinstance(current, dict) and current.get('version') == PROGRESS_RULE_VERSION
                    and current.get('cache_revision') == self._catalog.manifest['cache_revision']
                    and current.get('review_revision') == revision and current.get('generation') == generation
                    and current.get('cache_token') == cache_token):
                entry['proof_current'] = clean
            else:
                seed = self._progress_seed_scoped.get(scope)
                if seed is None and not separate_import:
                    seed = self._progress_seed.get(str(entry.get('sha256') or ''))
                seed_clean = self._workspace._clean_progress(seed)
                if (seed_clean is not None and isinstance(seed, dict) and seed.get('review_revision') == revision
                        and seed.get('generation') == generation and seed.get('cache_token') == cache_token):
                    entry['proof_current'] = seed_clean
                elif revision is None and generation == 0 and isinstance(entry.get('proof_current_default'), dict):
                    default = entry['proof_current_default']
                    if self._baseline_cache_matches(entry.get('sha256'), scope, default.get('recognition_hash')):
                        entry['proof_current'] = {key:default[key] for key in ('total', 'checked', 'unmatched')}
        return {'builtins': builtins, 'imports': imports}

    def export_score(self, score_id):
        """Package one score for the glove without opening it: saved review if any, else the
        converted project; unchecked notes are skipped (same as 送到手套)."""
        reply = self._catalog_open_project(score_id, 120, False)
        self._record_summary(score_id, reply)
        fresh = reply['project']
        if isinstance(reply.get('review'), dict):
            # Saved review is an edit-only delta. It cannot be exported as a
            # score; the UI must merge it with fresh via mergeRecognized first.
            raise ValueError('请从曲库重新准备曲谱，以便合并保存的校对')
        project = fresh
        project = dict(project)
        project.setdefault('selection', dict(fresh.get('selection') or {}))
        previews = fresh.get('page_previews') or []
        result = self.request('/api/software/export', 'POST', dict(project=project, skip_pending=True, page_previews=previews))
        if result['status'] != 200:
            raise ValueError(result['body'].get('error', '导出失败'))
        body = result['body']
        packaged = bool(body.get('package_base64')) and body.get('package_extension') == 'pglpack'
        builtin = next((row for row in self._catalog.list() if str(row['id']) == str(score_id)), None)
        title = str((builtin or {}).get('title') or fresh.get('name') or fresh.get('source_name') or score_id)
        return dict(name=title + ('.pglpack' if packaged else '.pgl'),
                    base64=body['package_base64'] if packaged else body['base64'],
                    skipped=int(body.get('skipped_pending_count') or 0))

    def record_score_stats(self, score_id, values):
        """The review page reports its live counts so the score list shows them."""
        return self._workspace.record_stats(score_id, values)

    def catalog_progress_notes(self, score_id):
        """Read compact saved/cached note states without changing the open score."""
        score_id = str(score_id)
        if score_id.startswith('import:'):
            digest = score_id.split(':', 1)[1]
            if not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('曲谱编号不正确')
        else:
            digest = self._catalog.get(score_id).get('sha256')
        scope = self._progress_scope(score_id, digest)
        path = self._workspace.review_path(digest, scope)
        try:
            with self._workspace._lock:
                project = self._workspace.review(digest, scope)
                stat = path.stat() if project is not None else None
                revision = str(stat.st_mtime_ns) + ':' + str(stat.st_size) if stat else None
        except (OSError, ValueError, UnicodeError, AttributeError):
            return {'available': False, 'unreadable': True}
        basis = 'historical-review' if isinstance(project, dict) and 'automatic_mode' not in project else 'saved'
        if project is None:
            identity = '|'.join((digest, self._catalog.manifest['cache_revision'], '120.0'))
            key = hashlib.sha256(identity.encode('ascii')).hexdigest()
            path = self._catalog.cache_root / (key + '.json')
            try:
                project = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
            except (OSError, ValueError, UnicodeError):
                project = None
            basis = 'cache'
            if project is None:
                # Older cache filenames use an earlier recognizer revision.
                # Find them by their embedded source checksum, and label their
                # results as previous checks until the score is reopened.
                with self._progress_cache_lock:
                    if self._progress_cache_index is None:
                        index = {}
                        for candidate in self._catalog.cache_root.glob('*.json'):
                            try:
                                with candidate.open('rb') as source:
                                    match = re.search(rb'"source_sha256"\s*:\s*"([0-9a-f]{64})"', source.read(4096))
                                if match:
                                    index.setdefault(match.group(1).decode('ascii'), []).append(candidate)
                            except OSError:
                                continue
                        self._progress_cache_index = index
                    candidates = list(self._progress_cache_index.get(digest, []))
                def modified(candidate):
                    try:
                        return candidate.stat().st_mtime_ns
                    except OSError:
                        return 0
                candidates.sort(key=modified, reverse=True)
                for candidate in candidates:
                    try:
                        older = json.loads(candidate.read_text(encoding='utf-8'))
                        if older.get('source_sha256') == digest and isinstance(older.get('notes'), list):
                            project = older
                            basis = 'historical-cache'
                            break
                    except (OSError, ValueError, UnicodeError, AttributeError):
                        continue
        if not isinstance(project, dict) or project.get('source_sha256') != digest or not isinstance(project.get('notes'), list):
            return {'available': False, 'unreadable': basis in ('saved', 'historical-review')}
        fields = ('id','hand','excluded','pitch','finger','beat','duration_beats','validation_pending',
                  'automatic_ready','automatic_reasons','performance_state','performance_marks',
                  'source_fingering_state','grace_kind','timing_warning','timing_estimated',
                  'start_estimate_ok','manual_fields','human_reviewed','in_export_scope','page',
                  'measure','rhythm_evidence','issues','finger_source','unfingered')
        notes = [{key:n[key] for key in fields if key in n} for n in project['notes']
                 if isinstance(n, dict) and n.get('hand') == 'right' and not n.get('excluded')]
        return {'available': True, 'basis': basis, 'revision': revision, 'automatic_mode': project.get('automatic_mode', True),
                'validation_pending': project.get('validation_pending', False), 'notes': notes}

    def forget_import(self, score_id):
        score_id = str(score_id)
        if not score_id.startswith('import:'):
            raise ValueError('内置曲谱不能删除')
        return self._workspace.forget(score_id.split(':', 1)[1])

    def pick_pdfs(self):
        """Native multi-select PDF picker that opens in the last used folder; registers each file."""
        import webview
        start = self._workspace.preference('pdf_folder') or str(Path.home() / 'Documents')
        if not Path(start).is_dir():
            start = str(Path.home())
        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=start, allow_multiple=True,
                                                 file_types=('PDF 曲谱 (*.pdf)', '所有文件 (*.*)'))
        if not chosen:
            return []
        paths = [Path(item) for item in (chosen if isinstance(chosen, (list, tuple)) else [chosen])]
        self._workspace.preference('pdf_folder', str(paths[0].parent))
        result = []
        for path in paths:
            if path.suffix.lower() != '.pdf':
                result.append(dict(name=path.name, error='不是 PDF 文件'))
                continue
            try:
                digest = self._workspace.remember_bytes(path.name, path.read_bytes())
                result.append(dict(name=path.name, id='import:' + digest, force=True))
            except (OSError, ValueError) as error:
                result.append(dict(name=path.name, error=str(error)))
        return result

    # 11-05 用户：换了新主控就用不了——软件自己认出手套程序旧了/没有，一键打开独立升级器。
    # 主程序不链接 esptool（许可要求单独分发），只找放在旁边的「固件升级」文件夹并启动它。
    @staticmethod
    def _upgrader_candidates():
        import sys
        roots = [Path(sys.executable).resolve().parent]
        if not getattr(sys, 'frozen', False):
            roots.append(Path(__file__).resolve().parents[2])
        found = []
        for root in roots:
            for exe in list(root.glob('固件升级/PianoGloveUpgrade.exe')) + list(root.glob('固件升级_*/固件升级/PianoGloveUpgrade.exe')):
                manifest = exe.parent / '_internal' / 'image' / 'firmware-manifest.json'
                try:
                    version = str(json.loads(manifest.read_text(encoding='utf-8')).get('version') or '')
                except (OSError, ValueError):
                    version = ''
                if re.fullmatch(r'\d+\.\d+\.\d+(?:-r\d+(?:\.\d+)?)?', version):
                    found.append((version, exe))
        return found

    @staticmethod
    def _version_key(version):
        m = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-r(\d+)(?:\.(\d+))?)?', str(version or ''))
        return tuple(int(x or 0) for x in m.groups()) if m else ()

    def firmware_upgrade_info(self):
        found = sorted(self._upgrader_candidates(), key=lambda row: self._version_key(row[0]))
        if not found:
            return {'available': False}
        version, exe = found[-1]
        return {'available': True, 'version': version, 'path': str(exe)}

    def firmware_upgrade_start(self):
        """11-05 用户：更新固件不要重启软件。舵机先失能，让出 USB 口，在后台跑升级器，完了自动重连。"""
        import subprocess
        state = getattr(self, '_fw_upgrade', None)
        if state and state.get('state') == 'running':
            return dict(state)
        info = self.firmware_upgrade_info()
        if not info.get('available'):
            raise ValueError('没找到「固件升级」文件夹，请把它放在钢琴手套软件旁边')
        exe = Path(info['path'])
        port = None
        try:
            port = (self.request('/api/status').get('body') or {}).get('port')
            self.request('/api/send', 'POST', {'cmd': 'SAFE', 'timeoutMs': 1500, 'quietMs': 25})
        except Exception:
            pass
        self.request('/api/disconnect', 'POST', {})
        self._fw_upgrade = dict(state='running', percent=0, text='准备升级…', version=info.get('version'))
        command = [str(exe), '--headless'] + (['--port', str(port)] if port else [])

        def work():
            state = self._fw_upgrade
            try:
                process = subprocess.Popen(command, cwd=str(exe.parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), encoding='utf-8', errors='replace')
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if 'percent' in event:
                        state['percent'] = max(state['percent'], int(event['percent']))
                    if event.get('stage'):
                        state['text'] = '正在升级：' + str(event['stage'])
                    if event.get('error'):
                        state.update(state='error', text=str(event['error']))
                    if event.get('done'):
                        state.update(state='done', percent=100, text='更新好了')
                code = process.wait()
                if state['state'] == 'running':
                    state.update(state='error' if code else 'done', text='升级没完成，请再试一次' if code else '更新好了')
            except Exception as error:
                state.update(state='error', text=str(error))
            finally:
                try:
                    time.sleep(1.5)
                    self.request('/api/connect', 'POST', {'auto': True})
                except Exception:
                    pass
                state['reconnected'] = True
        threading.Thread(target=work, name='glove-firmware-upgrade', daemon=True).start()
        return dict(self._fw_upgrade)

    def firmware_upgrade_status(self):
        return dict(getattr(self, '_fw_upgrade', None) or dict(state='idle'))

    def launch_firmware_upgrade(self):
        """用户点了「一键更新」：启动升级器，软件自己退出，把 USB 口让给升级器。"""
        import subprocess
        info = self.firmware_upgrade_info()
        if not info.get('available'):
            raise ValueError('没找到「固件升级」文件夹，请把它放在钢琴手套软件旁边')
        exe = Path(info['path'])
        # 11-05 用户：直接更新就完事了，更新前把舵机失能一下。先发 SAFE（舵机松开），再让升级器自己开始、做完重开软件
        port = None
        try:
            port = (self.request('/api/status').get('body') or {}).get('port')
            self.request('/api/send', 'POST', {'cmd': 'SAFE', 'timeoutMs': 1500, 'quietMs': 25})
        except Exception:
            pass
        import sys
        command = [str(exe), '--auto']
        if port:
            command += ['--port', str(port)]
        if getattr(sys, 'frozen', False):
            command += ['--relaunch', sys.executable]
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        subprocess.Popen(command, cwd=str(exe.parent), creationflags=flags, close_fds=True)
        timer = threading.Timer(.8, self.close_app)
        timer.daemon = True
        timer.start()
        return {'started': True, 'version': info['version']}

    def open_runtime_download(self):
        """User-clicked fixed Microsoft entry; never downloads or installs."""
        import webbrowser
        from desktop_setup import RUNTIME_DOWNLOAD_URL
        # 11-05：打包后 webbrowser 有时打不开，Windows 上先用系统默认浏览器
        try:
            os.startfile(RUNTIME_DOWNLOAD_URL)
            return {'opened': True}
        except (AttributeError, OSError):
            return {'opened': bool(webbrowser.open(RUNTIME_DOWNLOAD_URL))}

    def catalog_package(self, score_id):
        return self._catalog.package(score_id)

    def driver_archive(self):
        """Save-ready offline driver files; no installation or device changes."""
        import tempfile
        import zipfile
        from usb_driver_install import _bundled_package, _extract_package, _verify_catalog
        package = _bundled_package()
        if package is None:
            raise RuntimeError('完整驱动包未找到，请使用完整的钢琴手套 EXE。')
        with tempfile.TemporaryDirectory(prefix='piano-driver-export-') as directory:
            inf, catalog = _extract_package(package, Path(directory))
            _verify_catalog(catalog)
            output = BytesIO()
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(inf.parent.rglob('*')):
                    if path.is_file():
                        archive.write(path, path.relative_to(inf.parent).as_posix())
            return {'name': 'CP210x 官方串口驱动.zip', 'base64': base64.b64encode(output.getvalue()).decode('ascii')}

    def _convert(self, payload):
        # A catalog conversion already has a source: either a bundled PDF or
        # an explicitly registered import.  Do not run the direct-upload hook
        # here, or opening a bundled score silently adds it to "我转换的".
        reply = super().request('/api/software/convert', 'POST', payload)
        if reply['status'] != 200:
            raise ValueError(reply['body'].get('error', '原谱识别失败'))
        return reply['body']['project']

    @staticmethod
    def _conversion_token(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',value):
            raise ValueError('转换进度标识不正确')
        return value

    def _conversion_started(self,token,score_id):
        with self._conversion_progress_lock:
            prior=self._conversion_progress.get(token)
            if prior and prior['state']=='running':raise ValueError('该转换进度仍在使用')
            self._conversion_progress[token]=dict(token=token,score_id=str(score_id),state='running',stage='loading',label='读取原谱',
                page_done=None,page_total=None,determinate=False,finished=False,error=None,sequence=1)

    def _conversion_observed(self,token,event):
        with self._conversion_progress_lock:
            row=self._conversion_progress.get(token)
            if row is None or row['state']!='running':return
            row.update(event);row['sequence']+=1

    def _conversion_finished(self,token,error=None):
        with self._conversion_progress_lock:
            row=self._conversion_progress[token]
            row.update(state='error' if error is not None else 'done',stage='error' if error is not None else 'done',label='转换失败' if error is not None else '转换完成',
                page_done=None,page_total=None,determinate=False,finished=True,error=str(error) if error is not None else None,sequence=row['sequence']+1)
            finished=[key for key,value in self._conversion_progress.items() if value['finished']]
            for key in finished[:-32]:del self._conversion_progress[key]

    def get_conversion_progress(self,progress_token):
        token=self._conversion_token(progress_token)
        with self._conversion_progress_lock:
            row=self._conversion_progress.get(token)
            return dict(row) if row is not None else dict(token=token,score_id=None,state='unknown',stage='loading',label='等待转换开始',
                page_done=None,page_total=None,determinate=False,finished=False,error=None,sequence=0)

    def _record_summary(self,score_id,reply):
        try:
            project=reply['project'];automatic=project.get('automatic') or {}
            self._workspace.record_stats(score_id,dict(pages=len(project.get('pages',[])),
                notes=int(automatic.get('notes',0)),attention=int(automatic.get('attention_notes',0))))
        except Exception:
            pass

    @staticmethod
    def _catalog_summary(score_id,reply):
        project=reply['project'];automatic=project.get('automatic') or {}
        return dict(id=str(score_id),title=str(project.get('name') or project.get('source_name') or score_id),
            pages=len(project.get('pages',[])),right=int(automatic.get('notes',sum(n.get('hand')=='right' and not n.get('excluded') for n in project.get('notes',[])))),
            ready=automatic.get('ready') is True,attention=int(automatic.get('attention_notes',0)),
            # 11-05 用户：转换完说差 1 处、点进去又没问题——给前端一份精简音符，用校对页同一套规则算
            review_notes=[{k:n[k] for k in ('id','hand','excluded','pitch','finger','beat','duration_beats','timing_warning','timing_estimated','automatic_ready','automatic_reasons','performance_state','source_fingering_state','grace_kind','in_export_scope','validation_pending','manual_fields','page','measure','rhythm_evidence','unfingered','finger_source') if k in n} for n in project.get('notes',[]) if n.get('hand')!='left' and not n.get('excluded')])

    def _catalog_with_progress(self,score_id,bpm,force,progress_token,summary):
        if progress_token is None:
            reply=self._catalog_open_project(score_id,bpm,force)
            self._record_summary(score_id,reply)
            return self._catalog_summary(score_id,reply) if summary else reply
        token=self._conversion_token(progress_token);self._conversion_started(token,score_id)
        try:
            with listen_conversion_progress(lambda event:self._conversion_observed(token,event)):
                reply=self._catalog_open_project(score_id,bpm,force)
                self._record_summary(score_id,reply)
                result=self._catalog_summary(score_id,reply) if summary else reply
        except Exception as exc:
            self._conversion_finished(token,error=exc)
            raise
        self._conversion_finished(token)
        return result

    def catalog_open(self,score_id,bpm=120,force=False,progress_token=None):
        return self._catalog_with_progress(score_id,bpm,force,progress_token,False)

    def catalog_prepare(self,score_id,bpm=120,force=False,progress_token=None):
        return self._catalog_with_progress(score_id,bpm,force,progress_token,True)

    def catalog_progress_project(self, score_id, bpm=120):
        """Use existing recognition for progress; never start PDF recognition here."""
        try:
            return self._catalog_open_project(score_id, bpm, False, progress_only=True)
        except ScoreCacheMissing:
            return {'available': False, 'reason': 'not_cached'}

    def record_catalog_progress(self, score_id, expected_revision, expected_generation, expected_cache_token, values):
        score_id = str(score_id)
        digest = score_id.split(':', 1)[1] if score_id.startswith('import:') else self._catalog.get(score_id).get('sha256')
        scope = self._progress_scope(score_id, digest)
        return self._workspace.record_current_progress(digest, scope, expected_revision, expected_generation, expected_cache_token, values)

    def invalidate_catalog_progress(self, score_id):
        score_id = str(score_id)
        digest = score_id.split(':', 1)[1] if score_id.startswith('import:') else self._catalog.get(score_id).get('sha256')
        return self._workspace.invalidate_current_progress(digest, self._progress_scope(score_id, digest))

    def _catalog_open_project(self, score_id, bpm=120, force=False, progress_only=False):
        if not progress_only:
            self._session_opened = True
        identity = str(score_id)
        imported = identity.startswith('import:')
        catalog = (self._progress_import_catalog if progress_only else self._import_catalog) if imported else (self._progress_catalog if progress_only else self._catalog)
        digest = identity.split(':', 1)[1] if identity.startswith('import:') else catalog.get(identity).get('sha256')
        scope = self._progress_scope(identity, digest)
        with self._workspace._lock:
            progress_generation = self._workspace.progress_generation(digest, scope)
        if str(score_id).startswith('import:'):
            metadata, data = self._workspace.read_source(str(score_id).split(':', 1)[1])
            project = catalog.imported_project(metadata['filename'], data, bpm=bpm,
                converter=self._convert, force=force, cached_only=progress_only)
        else:
            project = catalog.project(score_id, bpm=bpm, converter=self._convert, force=force, cached_only=progress_only)
        from score_automatic import prepare_automatic_project
        tempo=project.get('source_tempo_bpm')
        if type(tempo) in (int,float) and 10<=tempo<=240:
            project['selection']['bpm']=tempo
        notify_conversion_progress("arranging",label="整理右手演奏")
        prepare_automatic_project(project)
        if not progress_only and project.get('page_previews'):
            from score_sources import ScoreSources
            notify_conversion_progress("saving",label="保存原谱定位")
            ScoreSources().record_document(project['source_sha256'],project['page_previews'],project.get('pages'))
        with self._workspace._lock:
            review=self._workspace.review(project['source_sha256'], scope)
            review_revision=self._workspace.review_revision(project['source_sha256'], scope)
        receipt=None
        if review is None:
            # Execute the same final editor validator here, before returning
            # the model. The untouched fresh editor need not send the complete
            # score through pywebview again merely to obtain these same states.
            notify_conversion_progress("validating",label="检查转换结果")
            self._finish_fresh_validation(project)
            receipt=dict(version=1,source_sha256=project['source_sha256'],recognizer=project.get('recognizer'),
                notes=len(project['notes']),automatic_version=project['automatic']['version'],
                selection=dict(project.get('selection') or {}),performance_policy=project.get('performance_policy'))
        if progress_only:
            project.pop('page_previews', None)
        return {'project':project,'review':_review_edits_only(review),'native_validation':receipt,'review_revision':review_revision,'progress_generation':progress_generation,'progress_cache_token':self._progress_cache_token(digest, scope),'progress_scope':scope}

    @staticmethod
    def _finish_fresh_validation(project):
        from score_automatic import check_project
        selection=project.setdefault('selection',{})
        for key,value in dict(bpm=120,start_beat=0,end_beat=None,start_page=None,end_page=None,
            range_reviewed=False,repeat_mode='written',repeats_reviewed=False,apply_tie_candidates=False,ties_reviewed=False).items():
            selection.setdefault(key,value)
        result=check_project(project)
        states={str(n['id']):n for n in result['notes']}
        for note in project['notes']:
            status=states.get(str(note['id']))
            if status:
                for key in ('automatic_ready','automatic_reasons','in_export_scope','unfingered','source_fingering_state',
                    'timing_warning','timing_estimated','timing_source_id'):
                    if key in status:note[key]=status[key]
                if 'performance_state' in status:note['performance_state']=status['performance_state']
                else:note.pop('performance_state',None)
                if result.get('right_hand_timing'):
                    for key,value in status.items():
                        if key.startswith('timing_') or key in ('beat','start_beat','written_beat','measure_beat','measure_start_beat','main_anchor_beat'):
                            note[key]=value
            note['validation_pending']=False
        if result.get('right_hand_timing'):
            for key in ('right_hand_timing','written_duration_beats','repeat_sections','repeat_markers','ending_brackets','rests'):
                if key in result:project[key]=result[key]
        if result.get('performance',{}).get('version')==1:project['performance']=result['performance']
        else:project.pop('performance',None)
        project['automatic']=result['automatic'];project['export_scope']=result['scope']
        project.setdefault('report',{}).update(result['report'])
        project['validation_pending']=False;project['validation_error']=''

    def _source_pdf_path(self, digest):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('原谱编号不正确')
        saved = self._workspace.root / (digest + '.pdf')
        if saved.is_file():
            return saved
        records = self._catalog.manifest if isinstance(self._catalog.manifest, list) else self._catalog.manifest.get('scores', [])
        entry = next((row for row in records if row.get('sha256') == digest and row.get('file')), None)
        if entry is None:
            raise ValueError('找不到这份原谱')
        return self._catalog.root / entry['file']

    def source_crop(self, digest, page, x, y, width, height):
        """Sharp crop of the original PDF for the review lens; read-only."""
        from pdf_preview import render_pdf_region
        values = [float(x), float(y), float(width), float(height)]
        if not all(math.isfinite(v) for v in values) or not 0 < values[2] <= 400 or not 0 < values[3] <= 400:
            raise ValueError('放大区域不正确')
        return render_pdf_region(self._source_pdf_path(digest), int(page), *values)

    def source_row(self, digest, page, x, y, width, height):
        """11-05 用户：上面整行谱子也要高清（不只放大镜）。按显示宽度渲染这一行原谱；只读。"""
        from pdf_preview import render_pdf_region
        values = [float(x), float(y), float(width), float(height)]
        if not all(math.isfinite(v) for v in values) or not 0 < values[2] <= 1200 or not 0 < values[3] <= 900:
            raise ValueError('整行区域不正确')
        scale = max(2.0, min(6.0, 2600.0 / values[2]))
        return render_pdf_region(self._source_pdf_path(digest), int(page), *values, scale=scale)

    def register_pdf(self, filename, content):
        data = base64.b64decode(content, validate=True)
        digest = hashlib.sha256(data).hexdigest()
        self._workspace.remember(filename, content, digest)
        return 'import:'+digest

    def stage_files(self, files):
        return self._workspace.append_staged(files, self._application_session_id)

    def take_staged_files(self):
        return self._workspace.take_staged(self._application_session_id)

    def _accept_native_pdf_drop(self, path):
        """Fallback for a file drop that WebView tried to navigate to."""
        try:
            if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError('文件不存在或超过 64MB')
            data = path.read_bytes()
            digest = self._workspace.remember_bytes(path.name, data)
            item = {'id': 'import:' + digest, 'name': path.name, 'force': True}
            value = json.dumps(item, ensure_ascii=False)
            script = "(function(){if(!window.ScoreList||!window.GloveWorkspace)return false;window.GloveWorkspace.show('convert');window.ScoreList.show();window.ScoreList.enqueue([" + value + "]);return true})()"
            try:
                delivered = self._window.evaluate_js(script) is True
            except Exception:
                delivered = False
            if delivered:
                return
            self._workspace.append_staged([{'name': path.name, 'content': base64.b64encode(data).decode('ascii')}], self._application_session_id)
            try:
                current = str(self._window.get_current_url() or '')
            except Exception:
                current = ''
            if 'software.html' not in current.lower():
                with self._drop_switch_lock:
                    if not self._drop_switch_pending:
                        self._drop_switch_pending = True
                        self.open_page('software')
                        def reset():
                            with self._drop_switch_lock:
                                self._drop_switch_pending = False
                        timer = threading.Timer(3, reset);timer.daemon = True;timer.start()
        except Exception as error:
            message = json.dumps('未能导入拖入的 PDF：' + str(error), ensure_ascii=False)
            try:
                self._window.evaluate_js("window.GloveWorkspace?.notice(" + message + ",true)")
            except Exception:
                pass

    def save_workspace(self, state):
        return self._workspace.save(state)

    def save_workspace_json(self, state_json):
        """Save one immutable browser snapshot without bridge object copies."""
        return self._workspace.save_json(state_json)

    def launch_state(self):
        """A fresh start opens nothing; the last score is only offered. None once a score is open."""
        if self._session_opened:
            return None
        last = self._workspace.last()
        digest = last.get('source_sha256')
        scope = last.get('review_scope')
        if scope not in (None, 'builtin:' + str(digest), 'import:' + str(digest)):
            scope = None
        name = None
        if digest:
            entry = next((row for row in self._catalog.list() if row['sha256'] == digest), None)
            try:
                name = self._workspace.read_source(digest)[0]['filename'] if scope == 'import:' + digest else entry['title'] if entry else self._workspace.read_source(digest)[0]['filename']
            except (OSError, ValueError, KeyError):
                review = self._workspace.review(digest, scope)
                name = (review or {}).get('source_name')
        return {'ui': last.get('ui') or {}, 'last_name': name}

    def page_html(self, page):
        """Static help page rendered for an in-window overlay, so the device page is not reloaded."""
        if page not in ('guide', 'licenses'):
            raise ValueError('没有这个说明页面')
        return render_page(page)

    def restore_workspace(self):
        last = self._workspace.last()
        digest = last.get('source_sha256')
        scope = last.get('review_scope')
        if scope not in (None, 'builtin:' + str(digest), 'import:' + str(digest)):
            scope = None
        result = {'ui': last.get('ui') or {}}
        if not digest:
            return result
        entry = next((row for row in self._catalog.list() if row['sha256'] == digest), None)
        score_id = 'import:' + digest if scope == 'import:' + digest else entry['id'] if entry else 'import:' + digest
        try:
            opened = self.catalog_open(score_id)
        except (OSError, ValueError):
            review = self._workspace.review(digest, scope)
            opened = {'project': dict(review, page_previews=[]) if review else None, 'review': None,
                      'progress_scope': scope, 'progress_generation': self._workspace.progress_generation(digest, scope),
                      'progress_cache_token': self._progress_cache_token(digest, scope)}
        result['score_id'] = score_id
        result.update(opened)
        return result

    def phone_connection(self):
        import qrcode
        import qrcode.image.svg
        reply = self.request('/api/library')
        capacity = (reply.get('body') or {}).get('capacity') or {}
        ssid = capacity.get('ap') or ''
        if not ssid:
            # The library is refused while servos are unpowered (boot enrollment wait); INFO still names the hotspot.
            info = str((self.request('/api/software/status').get('body') or {}).get('device_info') or '')
            match = re.search(r'(?:^|\s)ap=(\S+)', info)
            ssid = match.group(1) if match else ''
        def qr(value):
            output = BytesIO()
            qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=4).save(output)
            return 'data:image/svg+xml;base64,'+base64.b64encode(output.getvalue()).decode('ascii')
        escaped = re.sub(r'([\\;,:\"])', r'\\\1', ssid)
        return {'ssid': ssid, 'wifi_qr': qr('WIFI:T:nopass;S:'+escaped+';;') if ssid else None,
                'page_qr': qr('http://192.168.4.1/')}

    def open_page(self, page):
        if page not in PAGES:
            raise ValueError('没有这个软件页面')
        target = page_path(page)
        # Return to the current JS caller before replacing its document.
        timer = threading.Timer(.1, lambda: self._window.load_url(target))
        timer.daemon = True
        timer.start()
        return True

    def save_many(self, files):
        """Pick one folder (starts at the last one) and write several files there."""
        import webview
        start = self._workspace.preference('save_folder') or str(Path.home() / 'Documents')
        if not Path(start).is_dir():
            start = str(Path.home())
        target = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        if not target:
            return {'saved': False, 'count': 0}
        folder = Path(target[0] if isinstance(target, (list, tuple)) else target)
        self._workspace.preference('save_folder', str(folder))
        count = 0
        for item in files or []:
            name = re.sub(r'[\\/:*?"<>|]', '_', str(item.get('name') or 'score.pgl')).strip() or 'score.pgl'
            (folder / name).write_bytes(base64.b64decode(item.get('base64', ''), validate=True))
            count += 1
        return {'saved': True, 'count': count, 'folder': str(folder)}

    def save_file(self, content, name):
        import webview
        safe_name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
        target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=safe_name)
        if not target:
            return {'saved': False}
        path = Path(target[0] if isinstance(target, (list, tuple)) else target)
        path.write_bytes(base64.b64decode(content, validate=True))
        return {'saved': True, 'name': path.name}

    def _before_close(self):
        """Cancel the UI-thread close event while JS commits and saves its edits."""
        with self._close_lock:
            if self._close_approved:
                return
            # Before the first document loads there cannot be editable state.
            if not self._window.events.loaded.is_set():
                return
            if self._close_pending:
                return False
            self._close_pending = True
            self._close_retry = self._close_error is not None
            self._close_error = None
        threading.Thread(target=self._flush_before_close, name='glove-save-on-close', daemon=True).start()
        return False

    def _flush_before_close(self):
        # WinForms invokes closing handlers synchronously. evaluate_js marshals
        # to its UI thread, so neither evaluation nor a Promise wait belongs in
        # that handler. The Promise callback is our only save-completion signal.
        script = """(async()=>{
            const workspace=window.GloveWorkspace;
            if(!workspace?.flush)return {saved:true};
            const locked=[];
            let saved=false;
            try {
                await workspace.prepareClose?.();
                const operation=workspace.flush();
                // Keep the header Stop button reachable even if saving stalls.
                for(const node of document.querySelectorAll('main, nav')){
                    locked.push([node,node.inert]);node.inert=true;
                }
                if(await operation===true){saved=true;return {saved:true};}
                workspace.notice?.('修改尚未保存，窗口保持打开，请重试保存后关闭。');
                return {saved:false};
            } catch(error) {
                workspace.notice?.('修改保存失败，窗口保持打开：'+String(error?.message||error));
                return {saved:false,error:String(error?.message||error)};
            } finally {if(!saved){for(const [node,inert] of locked)node.inert=inert;workspace.cancelClose?.();}}
        })()"""
        try:
            self._window.evaluate_js(script, callback=self._finish_close_save)
        except Exception as error:
            self._close_save_failed(str(error))

    def _finish_close_save(self, result):
        if not isinstance(result, dict) or result.get('saved') is not True:
            error = result.get('error') if isinstance(result, dict) else None
            self._close_save_failed(error or '修改尚未保存', show_notice=False)
            return
        with self._close_lock:
            self._close_pending = False
            self._close_approved = True
        try:
            self._window.destroy()
        except Exception as error:
            with self._close_lock:self._close_approved = False
            self._close_save_failed(str(error))

    def _close_save_failed(self, error, show_notice=True):
        with self._close_lock:
            offer_discard = getattr(self, '_close_retry', False)
            self._close_pending = offer_discard
            self._close_error = str(error)
        if show_notice:
            text = json.dumps('修改保存未完成，窗口保持打开：'+str(error), ensure_ascii=False)
            try:self._window.evaluate_js('window.GloveWorkspace?.cancelClose?.();window.GloveWorkspace?.notice?.('+text+')')
            except Exception:pass  # A dead JS bridge cannot display a notice; keep the window open.
        if offer_discard:
            threading.Thread(target=self._offer_discard_close, name='glove-confirm-unsaved-close', daemon=True).start()

    def _confirm_discard_close(self):
        """Windows-owned dialog; No is the default and only Yes discards edits."""
        import ctypes
        from ctypes import wintypes
        message_box = ctypes.WinDLL('user32', use_last_error=True).MessageBoxW
        message_box.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
        message_box.restype = ctypes.c_int
        owner = self._window.native.Handle.ToInt64()
        answer = message_box(owner,
            '修改仍未能保存。是否放弃本次未保存的修改并退出？\n\n选择“否”将保留窗口，可以继续编辑或重试保存。',
            '钢琴手套 · 修改尚未保存', 0x00000004 | 0x00000030 | 0x00000100)
        return answer == 6  # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2; IDYES only.

    def _offer_discard_close(self):
        try:
            discard = self._confirm_discard_close() is True
        except Exception as error:
            with self._close_lock:
                self._close_pending = False
                self._close_error = '退出确认未完成：'+str(error)
            return
        with self._close_lock:
            self._close_pending = False
            if discard:self._close_approved = True
        if discard:
            try:self._window.destroy()
            except Exception as error:
                with self._close_lock:
                    self._close_approved = False
                    self._close_error = str(error)

    def close_app(self):
        if self._before_close() is not False:
            self._window.destroy()


def close_session(session):
    session.paused = True
    if session.connected:
        import bridge
        try:
            bridge.SoftwareConsole(session).release_usb()
        except Exception:
            pass
    session._stop = True
    session.close()


def main(argv=None):
    args = runtime.parse_arguments(argv)
    if args.self_test or args.list_ports:
        return runtime.run(args)
    configure_background_polling()
    from desktop_setup import ensure_runtime
    ensure_runtime(runtime.resources(), show_progress=not args.no_open)
    import bridge
    import webview
    bridge.HOST_DIR = str(runtime.resources())
    bridge.RUNTIME_DATA_DIR = str(runtime.data_directory())
    session = bridge.Bridge(url=args.url, baud=args.baud, auto=not args.no_auto)
    session.paused = bool(args.no_auto)
    api = DesktopAPI(session)
    install_pdf_navigation_guard(api)
    window = webview.create_window('钢琴手套', url=page_path('debug' if args.debug else 'software'),
                                   js_api=api, width=1280, height=840, min_size=(960,680),
                                   background_color='#F7F9FC', text_select=True, hidden=args.no_open)
    api._window = window
    window.events.closing += api._before_close
    threading.Thread(target=session._autoloop, name='glove-usb', daemon=True).start()
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['ALLOW_FILE_URLS'] = True
    try:
        webview.start(gui='edgechromium', http_server=False, private_mode=False,
                      storage_path=str(runtime.data_directory() / 'window-data'), debug=False,
                      icon=str(runtime.resources() / 'assets' / 'app-icon.ico'))
    finally:
        close_session(session)
