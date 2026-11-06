"""Native desktop lifecycle and bundled pages; no GUI, sockets, or COM handles."""
import base64
from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import url2pathname

HOST = Path(__file__).resolve().parents[1]
if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))
import bridge
import customer_runtime as runtime
import desktop_runtime as desktop
import native_window as native


class ResourceInventory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.stylesheets = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'script' and attributes.get('src'):
            self.scripts.append(attributes['src'])
        if tag == 'link' and attributes.get('rel') == 'stylesheet':
            self.stylesheets.append(attributes.get('href'))


class ClosingEvent(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self


class DesktopTest(unittest.TestCase):
    def test_native_background_polling_keeps_existing_browser_arguments(self):
        import os
        key='WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'
        with patch.dict(os.environ,{key:'--example="two words" --disable-renderer-backgrounding'}):
            native.configure_background_polling()
            first=os.environ[key]
            native.configure_background_polling()
            self.assertEqual(first,os.environ[key])
            self.assertTrue(first.startswith('--example="two words"'))
            for flag in ('--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows'):
                self.assertEqual(first.count(flag),1)
    def test_navigation_returns_before_replacing_the_javascript_document(self):
        api = native.DesktopAPI.__new__(native.DesktopAPI)
        api._window = Mock()
        with patch.object(native, 'page_path', return_value='file:///app/guide.html'), \
             patch.object(native.threading, 'Timer') as timer:
            self.assertTrue(api.open_page('guide'))
            api._window.load_url.assert_not_called()
            timer.assert_called_once()
            self.assertTrue(timer.return_value.daemon)
            timer.return_value.start.assert_called_once()
            timer.call_args.args[1]()
            api._window.load_url.assert_called_once_with('file:///app/guide.html')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='piano-native-window-test-')
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        context = patch.dict('os.environ', LOCALAPPDATA=str(self.data))
        context.start()
        self.addCleanup(context.stop)
        context = patch('desktop_setup.ensure_runtime', return_value={'installed':False,'version':'155.0.4283.62'})
        context.start()
        self.addCleanup(context.stop)
        # Any accidental legacy service, HTTP listener, COM open, or browser
        # launch fails immediately even when the window itself is mocked.
        for target in ('customer_runtime.serve', 'bridge.ThreadingHTTPServer',
                       'socket.socket', 'serial.Serial', 'serial.serial_for_url', 'webbrowser.open'):
            context = patch(target, side_effect=AssertionError('unexpected external transport: ' + target))
            context.start()
            self.addCleanup(context.stop)
        self.webview = ModuleType('webview')
        self.webview.settings = {}
        self.webview.FileDialog = SimpleNamespace(SAVE='save')
        self.window = Mock()
        self.window.events = SimpleNamespace(closing=ClosingEvent(),
            loaded=SimpleNamespace(is_set=lambda: False))
        self.webview.create_window = Mock(return_value=self.window)
        self.webview.start = Mock()
        context = patch.dict(sys.modules, webview=self.webview)
        context.start()
        self.addCleanup(context.stop)

    def session(self, connected=True):
        session = Mock(connected=connected, _stop=False, paused=False)
        session.recording_root = str(self.data / 'recordings')
        return session

    def test_command_line_checks_do_not_create_gui_or_legacy_service(self):
        for flag in ('--self-test', '--list-ports'):
            with self.subTest(flag=flag), \
                 patch.object(runtime, 'run', return_value={'ok': True}) as run, \
                 patch.object(bridge, 'Bridge') as session:
                output = desktop.main([flag, '--report', str(self.data / 'check.json')])
                self.assertEqual(output, {'ok': True})
                self.assertTrue(getattr(run.call_args.args[0], flag[2:].replace('-', '_')))
                session.assert_not_called()
        self.webview.create_window.assert_not_called()
        self.webview.start.assert_not_called()

    def test_main_embeds_stable_file_page_and_starts_only_usb_discovery(self):
        session = self.session()
        with patch.object(bridge, 'Bridge', return_value=session) as constructor, \
             patch.object(native.threading, 'Thread') as discovery, \
             patch.object(native, 'close_session') as close:
            desktop.main(['--no-auto'])
        constructor.assert_called_once_with(url=None, baud=115200, auto=False)
        self.assertTrue(session.paused)
        discovery.assert_called_once_with(target=session._autoloop, name='glove-usb', daemon=True)
        discovery.return_value.start.assert_called_once_with()
        self.webview.create_window.assert_called_once()
        options = self.webview.create_window.call_args.kwargs
        uri = urlsplit(options['url'])
        self.assertEqual(uri.scheme, 'file')
        self.assertEqual(uri.netloc, '')
        output_path = Path(url2pathname(uri.path))
        self.assertEqual(output_path, runtime.data_directory() / 'interface' / 'software.html')
        self.assertTrue(output_path.is_file())
        self.assertIsInstance(options['js_api'], native.DesktopAPI)
        self.assertIs(options['js_api']._window, self.window)
        self.assertIn(options['js_api']._before_close, self.window.events.closing)
        self.assertFalse(options['hidden'])
        self.webview.start.assert_called_once_with(
            gui='edgechromium', http_server=False, private_mode=False,
            storage_path=str(runtime.data_directory() / 'window-data'), debug=False,
            icon=str(runtime.resources() / 'assets' / 'app-icon.ico'))
        self.assertFalse(self.webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'])
        self.assertTrue(self.webview.settings['ALLOW_DOWNLOADS'])
        self.assertTrue(self.webview.settings['ALLOW_FILE_URLS'])
        close.assert_called_once_with(session)
        session.send.assert_not_called()

    def test_debug_and_hidden_options_keep_file_origin_and_simple_query(self):
        session = self.session(connected=False)
        with patch.object(bridge, 'Bridge', return_value=session), \
             patch.object(native.threading, 'Thread'), \
             patch.object(native, 'close_session'):
            desktop.main(['--debug', '--no-open', '--no-auto', '--url', 'com7'])
        options = self.webview.create_window.call_args.kwargs
        uri = urlsplit(options['url'])
        self.assertEqual(uri.scheme, 'file')
        self.assertTrue(uri.path.endswith('/debug.html'))
        self.assertEqual(uri.query, '')
        self.assertEqual(uri.fragment, 'connect')
        self.assertNotIn("new URLSearchParams(location.search).get('simple')", native.render_page('debug', HOST))
        self.assertTrue(options['hidden'])

    def test_webview_start_failure_still_closes_session(self):
        session = self.session()
        self.webview.start.side_effect = RuntimeError('renderer failed')
        with patch.object(bridge, 'Bridge', return_value=session), \
             patch.object(native.threading, 'Thread'), \
             patch.object(native, 'close_session') as close:
            with self.assertRaisesRegex(RuntimeError, 'renderer failed'):
                desktop.main(['--no-auto'])
        close.assert_called_once_with(session)

    def test_close_releases_usb_without_global_stop_and_disables_reconnect(self):
        for failure in (None, RuntimeError('release readback failed')):
            with self.subTest(failure=failure):
                session = self.session()
                console = Mock()
                def release():
                    self.assertFalse(session._stop, 'Reader must stay alive for LIB INFO / RELEASE acknowledgements')
                    self.assertTrue(session.paused, 'Discovery must already be paused during shutdown')
                    if failure:
                        raise failure
                console.release_usb.side_effect = release
                with patch.object(bridge, 'SoftwareConsole', return_value=console) as adapter:
                    native.close_session(session)
                adapter.assert_called_once_with(session)
                console.release_usb.assert_called_once_with()
                session.close.assert_called_once_with()
                session.send.assert_not_called()
                self.assertTrue(session._stop)
                self.assertTrue(session.paused)

    def test_close_disconnected_session_does_not_issue_release_commands(self):
        session = self.session(connected=False)
        with patch.object(bridge, 'SoftwareConsole') as adapter:
            native.close_session(session)
        adapter.assert_not_called()
        session.send.assert_not_called()
        session.close.assert_called_once_with()

    def api(self):
        api = native.DesktopAPI(self.session(connected=False))
        api._window = self.window
        return api

    def test_save_cancel_does_not_decode_or_write_a_file(self):
        api = self.api()
        self.window.create_file_dialog.return_value = None
        result = api.save_file('invalid base64 because cancelled', '进度.json')
        self.assertEqual(result, {'saved': False})
        self.window.create_file_dialog.assert_called_once_with('save', save_filename='进度.json')
        self.assertFalse((self.data / '进度.json').exists())

    def test_save_preserves_every_binary_byte_and_uses_selected_path(self):
        api = self.api()
        blob = bytes(range(256)) * 3 + b'\x00\xffPGL\r\n'
        path = self.data / '用户选择的曲谱.pglpack'
        self.window.create_file_dialog.return_value = (str(path),)
        result = api.save_file(base64.b64encode(blob).decode('ascii'), '..\\other\\原谱.pglpack')
        self.assertEqual(result, {'saved': True, 'name': path.name})
        self.assertEqual(path.read_bytes(), blob)
        self.window.create_file_dialog.assert_called_once_with('save', save_filename='原谱.pglpack')

    def test_navigation_only_loads_declared_application_pages(self):
        api = self.api()
        with patch.object(native, 'page_path', side_effect=lambda page: 'file:///native/' + page + '.html') as path, \
             patch.object(native.threading, 'Timer') as timer:
            for page in native.PAGES:
                self.assertTrue(api.open_page(page))
                timer.call_args.args[1]()
                self.window.load_url.assert_called_with('file:///native/' + page + '.html')
            count = path.call_count
            for page in ('../software', 'https://example.com', 'missing'):
                with self.assertRaisesRegex(ValueError, '没有这个软件页面'):
                    api.open_page(page)
            self.assertEqual(path.call_count, count)

    def test_close_app_requests_native_window_close_before_document_load(self):
        api = self.api()
        api.close_app()
        self.window.destroy.assert_called_once_with()

    def test_actual_pages_inline_assets_and_keep_native_transport(self):
        for page in ('software', 'debug', 'guide'):
            with self.subTest(page=page):
                text = native.render_page(page, HOST)
                inventory = ResourceInventory()
                inventory.feed(text)
                self.assertEqual(inventory.scripts, [])
                self.assertEqual(inventory.stylesheets, [])
                self.assertIn('pywebviewready', text)
                self.assertIn('NativeApp', text)
                self.assertIn('native-app', text)
        self.assertIn("bridgeBases(){ if(window.NativeApp)return [''];", native.render_page('debug', HOST))

    def test_page_paths_are_stable_and_license_anchor_stays_in_app(self):
        first = native.page_path('software', HOST)
        self.assertEqual(first, native.page_path('software', HOST))
        uri = urlsplit(native.page_path('licenses', HOST))
        self.assertEqual(uri.scheme, 'file')
        self.assertEqual(uri.fragment, 'licenses')
        self.assertTrue(Path(url2pathname(uri.path)).is_file())


if __name__ == '__main__':
    unittest.main()
