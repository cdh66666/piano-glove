import pathlib
import sys
import unittest
import json
import threading
import urllib.request
import urllib.error
import importlib.util
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch, MagicMock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from bridge import Bridge, make_handler, peer_console_url
spec = importlib.util.spec_from_file_location('dual_launcher', pathlib.Path(__file__).resolve().parents[1]/'start-dual.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class DualConsoleTests(unittest.TestCase):
    def test_peer_navigation_only_matches_target_owner(self):
        import io
        response = MagicMock()
        response.__enter__.side_effect = lambda: io.BytesIO(b'{"fixed":"COM27","connected":true}')
        with patch('bridge.urlopen', return_value=response):
            self.assertIn(':8124/', peer_console_url(8123, 'COM27'))
            self.assertIsNone(peer_console_url(8123, 'COM5'))

    def test_launcher_enumeration_requires_exactly_two_supported_boards(self):
        ports = [SimpleNamespace(device=p, vid=0x10C4, pid=0xEA60) for p in ('COM27', 'COM3')]
        self.assertEqual(launcher.choose_ports([], ports), ['COM3', 'COM27'])
        with self.assertRaises(ValueError):
            launcher.choose_ports([], ports[:1])
        with self.assertRaises(ValueError):
            launcher.choose_ports(['COM3', 'COM3'], ports)
        self.assertEqual(launcher.choose_ports(['COM27', 'COM3'], ports), ['COM27', 'COM3'])

    def test_fixed_port_rejection_keeps_existing_connection(self):
        bridge = Bridge(url='COM3')
        bridge.close = Mock()
        bridge._open_raw = Mock()
        self.assertFalse(bridge.open('COM27')[0])
        bridge.close.assert_not_called()
        bridge._open_raw.assert_not_called()

    def test_fixed_autoconnect_never_probes_other_board(self):
        bridge = Bridge(url='COM3')
        bridge.open = Mock(return_value=(True, 'ok'))
        bridge._reload_ports = Mock()
        bridge.autoconnect_once()
        bridge.open.assert_called_once_with('COM3')
        bridge._reload_ports.assert_not_called()

    def test_fixed_recording_roots_are_distinct(self):
        first, second = Bridge(url='COM3'), Bridge(url='COM27')
        self.assertNotEqual(first.recording_root, second.recording_root)
        self.assertTrue(first.recording_root.endswith('COM3'))

    def test_explicit_selection_stops_old_board_and_changes_target(self):
        bridge = Bridge(url='COM3')
        bridge.connected, bridge.port = True, 'COM3'
        bridge.send = Mock(return_value={'lines':['OK SAFE armed=0']})
        bridge.close = Mock()
        bridge.open = Mock(return_value=(True, 'ok'))
        self.assertTrue(bridge.select_port('COM27')[0])
        bridge.send.assert_called_once_with('SAFE', timeout_ms=1500, quiet_ms=25)
        self.assertEqual(bridge.url, 'COM27')
        self.assertTrue(bridge.recording_root.endswith('COM27'))
        self.assertFalse(bridge.paused)

    def test_failed_stop_keeps_original_board(self):
        bridge = Bridge(url='COM3')
        bridge.connected, bridge.port = True, 'COM3'
        bridge.send = Mock(return_value={'lines':[]})
        bridge.close = Mock()
        self.assertFalse(bridge.select_port('COM27')[0])
        self.assertEqual(bridge.url, 'COM3')
        bridge.close.assert_not_called()

    def test_http_flash_rejects_unselected_board(self):
        bridge = Bridge(url='COM3')
        bridge.open = Mock()
        bridge.firmware.start = Mock()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for route, code in [('firmware/flash', 400)]:
                request = urllib.request.Request('http://127.0.0.1:%d/api/%s' % (server.server_port, route),
                                                 data=json.dumps({'port':'COM27'}).encode(),
                                                 headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, code)
                caught.exception.close()
            bridge.open.assert_not_called()
            bridge.firmware.start.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
