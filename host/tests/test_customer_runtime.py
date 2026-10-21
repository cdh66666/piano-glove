"""Customer launcher lifecycle regressions. No actual COM handles or service restarts."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HOST = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('customer_runtime', HOST / 'customer_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class LauncherTest(unittest.TestCase):
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

    def shutdown(self, connected=True, release_error=None):
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
            runtime.serve(args)
        # No global STOP/SAFE may follow release or its failure: a phone could
        # own a live run while this otherwise idle desktop app closes.
        session.send.assert_not_called()
        session.close.assert_called_once()
        server.server_close.assert_called_once()
        thread.return_value.start.assert_called_once()
        return session, console, adapter

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


if __name__ == '__main__':
    unittest.main()
