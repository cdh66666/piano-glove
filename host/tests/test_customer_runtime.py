"""Customer launcher lifecycle regressions. No actual COM handles or service restarts."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HOST = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('customer_runtime', HOST / 'customer_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class LauncherTest(unittest.TestCase):
    def matching_opener(self, overrides=None):
        overrides = overrides or {}
        def respond(url, timeout):
            name = url.rsplit('/', 1)[1]
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = overrides.get(name, (HOST / name).read_bytes())
            return response
        opener = Mock()
        opener.open.side_effect = respond
        return opener

    def test_existing_wrong_fixed_port_is_not_reused(self):
        with patch.object(runtime, 'existing_service', return_value={'connected': True, 'fixed': 'COM4'}), \
             patch.object(runtime.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(RuntimeError, '其他串口'):
                runtime.open_existing(8123, 'COM3', 'software.html', True)
            browser.assert_not_called()

    def test_existing_auto_connection_does_not_override_explicit_port(self):
        with patch.object(runtime, 'existing_service', return_value={'connected': True, 'fixed': None, 'port': 'COM3'}):
            with self.assertRaisesRegex(RuntimeError, '其他串口'):
                runtime.open_existing(8123, 'COM3', 'software.html', False)

    def test_existing_wrong_version_is_not_opened(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'old software'
        opener = Mock()
        opener.open.return_value = response
        with patch.object(runtime, 'existing_service', return_value={'connected': False, 'fixed': None}), \
             patch.object(runtime, 'build_opener', return_value=opener), \
             patch.object(runtime.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(RuntimeError, '另一版本'):
                runtime.open_existing(8123, None, 'software.html', True)
            browser.assert_not_called()

    def test_review_changes_reject_reuse_even_when_main_script_matches(self):
        opener = self.matching_opener({'software-review.js': b'previous review UI'})
        with patch.object(runtime, 'existing_service', return_value={'connected': False}), \
             patch.object(runtime, 'build_opener', return_value=opener), \
             patch.object(runtime.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(RuntimeError, 'software-review.js'):
                runtime.open_existing(8123, None, 'software.html', True)
            browser.assert_not_called()
        self.assertIn('http://127.0.0.1:8123/software.js', [call.args[0] for call in opener.open.call_args_list])

    def test_matching_all_assets_accepts_line_ending_differences(self):
        files = {name: (HOST / name).read_bytes().replace(b'\r\n', b'\n') for name in runtime.WEB_ASSETS}
        opener = self.matching_opener(files)
        with patch.object(runtime, 'existing_service', return_value={'connected': False}), \
             patch.object(runtime, 'build_opener', return_value=opener), \
             patch.object(runtime.webbrowser, 'open') as browser:
            self.assertTrue(runtime.open_existing(8123, None, 'software.html', True))
            browser.assert_called_once_with('http://127.0.0.1:8123/software.html')
        self.assertEqual(len(runtime.WEB_ASSETS), opener.open.call_count)

    def test_reusing_existing_service_reports_no_owned_server(self):
        ready = Mock()
        with patch.object(runtime, 'open_existing', return_value=True), \
             patch.object(runtime, 'ThreadingHTTPServer') as server:
            args = runtime.parse_arguments(['--no-auto', '--no-open', '--port', '8127'])
            runtime.serve(args, on_ready=ready)
        ready.assert_called_once_with(None, None, 'http://127.0.0.1:8127/software.html')
        server.assert_not_called()

    def shutdown(self, connected=True, release_error=None, on_ready=None):
        import sys
        sys.path.insert(0, str(HOST))
        import bridge
        session = Mock(connected=connected)
        console = Mock()
        console.release_usb.side_effect = release_error
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt()
        args = SimpleNamespace(debug=False, port=8127, url=None, baud=115200, no_auto=True, no_open=True)
        with patch.object(runtime, 'open_existing', return_value=False), \
             patch.object(bridge, 'Bridge', return_value=session), \
             patch.object(bridge, 'SoftwareConsole', return_value=console) as adapter, \
             patch.object(runtime, 'ThreadingHTTPServer', return_value=server), \
             patch.object(runtime.threading, 'Thread') as thread, \
             patch.object(bridge, 'make_handler', return_value=object()):
            runtime.serve(args, on_ready=on_ready)
        # No global STOP/SAFE may follow release or its failure: a phone could
        # own a live run while this otherwise idle desktop app closes.
        session.send.assert_not_called()
        session.close.assert_called_once()
        self.assertTrue(session._stop)
        self.assertTrue(session.paused)
        server.server_close.assert_called_once()
        thread.return_value.start.assert_called_once()
        return session, console, adapter

    def test_new_service_reports_owned_server_and_session_before_serving(self):
        ready = Mock()
        session, _, _ = self.shutdown(on_ready=ready)
        ready.assert_called_once()
        self.assertIs(session, ready.call_args.args[1])
        self.assertEqual('http://127.0.0.1:8127/software.html', ready.call_args.args[2])
        ready.call_args.args[0].serve_forever.assert_called_once()

    def test_shutdown_releases_usb_and_closes_its_session(self):
        session, console, adapter = self.shutdown()
        adapter.assert_called_once_with(session)
        console.release_usb.assert_called_once_with()

    def test_shutdown_release_failure_does_not_fall_back_to_global_stop(self):
        session, console, adapter = self.shutdown(release_error=RuntimeError('readback_timeout'))
        adapter.assert_called_once_with(session)
        console.release_usb.assert_called_once_with()

    def test_shutdown_disconnected_session_does_not_try_release(self):
        _, console, adapter = self.shutdown(connected=False)
        adapter.assert_not_called()
        console.release_usb.assert_not_called()

    def test_no_serial_is_opened_for_invalid_launch_arguments(self):
        with self.assertRaises(SystemExit):
            runtime.main(['--url', 'http://example.com'])
        with self.assertRaises(SystemExit):
            runtime.main(['--port', '80'])

    def test_self_test_report_records_returned_result_without_serving(self):
        expected = {'ok': True, 'serial_opened': False, 'build_date': runtime.BUILD_DATE}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(runtime, 'self_test', return_value=expected), \
             patch.object(runtime, 'serve') as serve:
            path = Path(temporary) / 'check.json'
            result = runtime.main(['--self-test', '--report', str(path)])
            self.assertEqual(expected, result)
            self.assertEqual(expected, json.loads(path.read_text(encoding='utf-8')))
            serve.assert_not_called()

    def test_self_test_failure_is_written_for_windowed_process(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(runtime, 'self_test', side_effect=RuntimeError('missing PDF module')):
            path = Path(temporary) / 'failed.json'
            with self.assertRaisesRegex(RuntimeError, 'missing PDF'):
                runtime.main(['--self-test', '--report', str(path)])
            report = json.loads(path.read_text(encoding='utf-8'))
            self.assertFalse(report['ok'])
            self.assertEqual('missing PDF module', report['error'])

    def test_report_requires_a_report_command_and_absolute_path(self):
        with self.assertRaises(SystemExit):
            runtime.parse_arguments(['--report', 'relative.json', '--self-test'])
        with self.assertRaises(SystemExit):
            runtime.parse_arguments(['--report', str(HOST / 'result.json')])


if __name__ == '__main__':
    unittest.main()
