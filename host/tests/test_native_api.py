"""Exercise real route logic in memory; never listen on a socket or open COM."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge
from native_api import NativeAPI
from score_codec import decode, encode


SCORE = dict(version=1, hand='right', title='原曲', duration_ms=500,
             notes=[dict(t_ms=0, duration_ms=500, pitch=60, finger=1)])


class FakeSession:
    def __init__(self, root):
        self.firmware = SimpleNamespace(serialExclusive=False, status=lambda: {'state': 'idle'})
        self.commands = []
        self.connected = False
        self.url = self.port = None
        self.baud = 115200
        self._seq = 8
        self.last_error = ''
        self.recording_root = root
        self.fail = None
        self.ports = [dict(device='COM7', candidate=True)]

    def status(self):
        return dict(connected=self.connected, fixed=self.url, ports=self.ports)

    def _reload_ports(self):
        pass

    def select_port(self, port, baud):
        self.port = self.url = port
        return True, 'selected'

    def lines_since(self, since):
        return ([dict(seq=8, line='最新反馈')] if since < 8 else []), 8

    def send(self, command, *args, **kwargs):
        self.commands.append(command)
        if self.fail and command.startswith(self.fail):
            return dict(ok=True, lines=['ERR LIB test_failure'])
        lines = ['OK ' + command]
        if command == 'LIB INFO':
            lines = ['OK LIB INFO ready=1 count=1 max=100 free=1048576']
        elif command == 'LIB LIST':
            lines = ['LIB_ITEM slot=7 bytes=144 notes=1 duration_ms=500 title_hex=' + SCORE['title'].encode().hex(),
                     'OK LIB LIST count=1']
        elif command == 'LIB STATE':
            lines = ['LIB_STATE ' + json.dumps(dict(active=False, owner='none', error='none')), 'OK LIB STATE']
        elif command == 'LIB READ 7':
            lines = ['LIB_DATA hex=' + encode(SCORE).hex(), 'OK LIB READ']
        return dict(ok=True, lines=lines)


class NativeAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='piano-native-api-test-')
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict('os.environ', LOCALAPPDATA=self.temporary.name)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Even an accidental peer lookup, server construction or COM open fails
        # the tests. PDF work and connection selection must stay in process.
        for name in ('socket.socket', 'serial.Serial', 'serial.serial_for_url',
                     'bridge.ThreadingHTTPServer', 'webbrowser.open'):
            blocker = patch(name, side_effect=AssertionError('unexpected external transport: ' + name))
            blocker.start()
            self.addCleanup(blocker.stop)
        self.session = FakeSession(self.temporary.name)
        self.api = NativeAPI(self.session)

    def test_review_check_updates_validation_without_hardware_or_value_changes(self):
        original=dict(name='开发谱',automatic_mode=True,source_has_printed_fingering=True,
            selection=dict(bpm=120,start_beat=0),notes=[
                dict(id='good',hand='right',pitch='C4',finger=1,beat=2,duration_beats=1,confirmed=False),
                dict(id='ignored',hand='right',pitch='D4',finger=None,beat=None,duration_beats=None,excluded=True)])
        before=json.dumps(original,sort_keys=True)
        reply=self.api.request('/api/software/check','POST',{'project':original})
        self.assertEqual(reply['status'],200)
        self.assertTrue(reply['body']['automatic']['ready'])
        self.assertEqual(reply['body']['automatic']['ignored_notes'],1)
        self.assertEqual(reply['body']['notes'][0]['automatic_reasons'],[])
        self.assertEqual(json.dumps(original,sort_keys=True),before)

    def test_status_library_score_state_and_query_use_real_routes(self):
        self.assertEqual(self.api.request('/api/status')['body']['connected'], False)
        software = self.api.request('/api/software/status')
        self.assertEqual(software['status'], 200)
        self.assertEqual(software['body']['upload_protocol'], 'chunks-v1')
        self.assertFalse(software['body']['motion_ready'])
        library = self.api.request('/api/library')['body']
        self.assertEqual(library['slots'][0]['title'], SCORE['title'])
        score = self.api.request('/api/score?slot=%37')
        self.assertEqual(decode(base64.b64decode(score['body']['base64']))['title'], SCORE['title'])
        self.assertFalse(self.api.request('/api/state')['body']['active'])
        self.assertEqual(self.api.request('/api/lines?since=7&wait=0')['body']['lines'][0]['line'], '最新反馈')
        self.assertEqual(self.api.request('/api/lines?since=8&wait=0')['body']['lines'], [])

    def test_real_review_check_text_opt_in_is_equivalent_and_does_not_change_music_or_touch_hardware(self):
        original=dict(name='独立合成对照',automatic_mode=True,source_has_printed_fingering=True,
            selection=dict(bpm=120,start_beat=0),notes=[
                dict(id='a',hand='right',pitch='F#4',finger=2,beat=.333333,duration_beats=.25,confirmed=False),
                dict(id='b',hand='right',pitch='C5',finger=None,beat=2,duration_beats=.5,confirmed=False)])
        before=json.dumps(original,sort_keys=True)
        default=self.api.request('/api/software/check','POST',{'project':original})
        text=self.api.request('/api/software/check','POST',{'project':original},False,{'X-Piano-Json-Text':'1'})
        self.assertEqual(default['status'],200);self.assertEqual(text['status'],200)
        self.assertEqual(text['body_encoding'],'json-text');self.assertEqual(json.loads(text['body']),default['body'])
        self.assertEqual(json.dumps(original,sort_keys=True),before);self.assertEqual(self.session.commands,[])
        self.assertFalse(any(command.startswith(('LIB PLAY', 'LIB TRAIN', 'LIB PATTERN', 'MOVE'))
                             for command in self.session.commands))

    def test_manual_connect_accepts_other_usb_boards_but_not_blacklisted_ports(self):
        self.session.ports=[dict(device='COM5',candidate=False,score=92),dict(device='COM1',candidate=False,score=bridge.SCORE_BLACKLISTED)]
        api=NativeAPI(self.session)
        self.assertTrue(api.request('/api/connect','POST',dict(port='COM5',baud=115200))['body']['ok'])
        self.assertEqual(api.request('/api/connect','POST',dict(port='COM1',baud=115200))['status'],400)

    def test_connect_skips_http_peer_discovery_without_patching_shared_bridge(self):
        with patch.object(bridge, 'peer_console_url', side_effect=AssertionError('HTTP peer lookup')) as peer:
            api = NativeAPI(self.session)
            reply = api.request('/api/connect', 'POST', dict(port='COM7', baud=115200))
        self.assertEqual(reply['status'], 200)
        self.assertTrue(reply['body']['ok'])
        self.assertEqual(reply['body']['port'], 'COM7')
        peer.assert_not_called()

    def test_binary_array_and_base64_upload_preserve_exact_wire_bytes(self):
        blob = encode(SCORE)
        for value in (list(blob), base64.b64encode(blob).decode('ascii')):
            with self.subTest(kind=type(value).__name__):
                before = len(self.session.commands)
                result = self.api.request('/api/upload?slot=7', 'POST', value, True,
                                          {'X-Piano-Controller': 'desktop-a'})
                self.assertEqual(result['status'], 200, result)
                self.assertEqual(result['body']['bytes'], len(blob))
                sent = self.session.commands[before:]
                self.assertEqual(sent[0], 'LIB BEGIN 7 144')
                self.assertEqual(b''.join(bytes.fromhex(line.split()[2]) for line in sent
                                          if line.startswith('LIB CHUNK ')), blob)
                self.assertEqual(sent[-1], 'LIB COMMIT')

    def test_chunks_keep_owner_across_calls_and_reject_other_controller(self):
        owner = {'x-piano-controller': 'desktop-a'}
        blob = encode(SCORE)
        self.assertEqual(self.api.request('/api/upload/begin', 'POST',
                         dict(slot=7, bytes=len(blob)), False, owner)['status'], 200)
        before = list(self.session.commands)
        mismatch = self.api.request('/api/upload/chunk', 'POST', list(blob[:72]), True,
                                    {'X-Piano-Controller': 'desktop-b'})
        self.assertEqual(mismatch['status'], 409)
        self.assertIn('controller_mismatch', mismatch['body']['error'])
        self.assertEqual(self.session.commands, before)
        for chunk in (blob[:72], blob[72:]):
            self.assertEqual(self.api.request('/api/upload/chunk', 'POST', list(chunk), True, owner)['status'], 200)
        self.assertEqual(self.api.request('/api/upload/commit', 'POST', {}, False, owner)['status'], 200)
        self.assertEqual(self.session.commands[-1], 'LIB COMMIT')

    def test_controller_json_form_and_explicit_stop_routes(self):
        owner = {'X-Piano-Controller': 'desktop-a'}
        started = self.api.request('/api/train', 'POST', 'mask=3&hold=50&amplitude=20', False, owner)
        self.assertEqual(started['status'], 200)
        status = self.api.request('/api/software/status')['body']
        self.assertEqual(status['controller_id'], 'desktop-a')
        stopped = self.api.request('/api/stop', 'POST', '{}', False,
                                   dict(owner, **{'Content-Type': 'application/json'}))
        self.assertEqual(stopped['status'], 200)
        self.assertEqual(self.session.commands[-1], 'LIB STOP')
        self.assertEqual(self.api.request('/api/software/status')['body']['controller_id'], '')

    def test_route_failure_and_unknown_route_keep_error_status(self):
        self.session.fail = 'LIB DELETE'
        failed = self.api.request('/api/delete', 'POST', {'slot': 7})
        self.assertEqual(failed['status'], 409)
        self.assertFalse(failed['body']['ok'])
        self.assertIn('test_failure', failed['body']['error'])
        self.assertEqual(self.api.request('/api/no-such-route', 'POST', {})['status'], 404)
        self.assertEqual(self.api.request('/api/software/export', 'POST', {'project': {}})['status'], 400)
        self.assertEqual(self.api.request('/api/state', 'PUT')['status'], 405)

    def test_origin_validation_and_content_length_cannot_bypass_real_route(self):
        denied = self.api.request('/api/stop', 'POST', {}, False, {'Origin': 'https://example.com'})
        self.assertEqual(denied['status'], 403)
        self.assertEqual(self.session.commands, [])
        result = self.api.request('/api/send', 'POST', {'cmd': 'INFO'}, False, {'Content-Length': '0'})
        self.assertEqual(result['status'], 200)
        self.assertEqual(self.session.commands, ['INFO'])

    def test_native_bridge_preserves_failures_outside_route_exception_handlers(self):
        with patch.object(self.session, 'status', side_effect=RuntimeError('read_status_failed')):
            result = self.api.request('/api/status')
        self.assertEqual(result['status'], 500)
        self.assertFalse(result['body']['ok'])
        self.assertEqual(result['body']['error'], 'read_status_failed')

    def test_input_errors_and_options_do_not_issue_device_commands(self):
        for path in ('https://example.com/api/stop', '//example.com/api/stop', None):
            self.assertEqual(self.api.request(path)['status'], 400)
        self.assertEqual(self.api.request('/api/upload?slot=7', 'POST', 'not base64!', True)['status'], 400)
        options = self.api.request('/api/state', 'OPTIONS')
        self.assertEqual(options['status'], 204)
        self.assertFalse(options['binary'])
        self.assertEqual(options['body'], '')
        self.assertEqual(self.session.commands, [])

    def test_text_static_errors_and_json_response_headers(self):
        missing = self.api.request('/not-a-file-20261024.txt')
        self.assertEqual(missing['status'], 404)
        self.assertFalse(missing['binary'])
        self.assertIn('找不到', missing['body'])
        result = self.api.request('/api/status')
        self.assertFalse(result['binary'])
        self.assertIn('application/json', result['headers']['content-type'])
        size = len(json.dumps(result['body'], ensure_ascii=False).encode('utf-8'))
        self.assertEqual(int(result['headers']['content-length']), size)

    def test_real_pdf_preview_export_bundle_and_binary_source_have_no_socket(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
        output = io.BytesIO()
        document = PdfWriter()
        page = document.add_blank_page(width=400, height=200)
        stream = DecodedStreamObject()
        stream.set_data(b'0.5 w\n' + b'\n'.join(('20 %d m 380 %d l S' % (y, y)).encode('ascii')
                                                for y in (70, 78, 86, 94, 102)))
        page[NameObject('/Contents')] = stream
        document.write(output)
        converted = self.api.request('/api/software/convert', 'POST', dict(
            filename='真实页面.pdf', bpm=120, base64=base64.b64encode(output.getvalue()).decode('ascii')))
        self.assertEqual(converted['status'], 200, converted)
        project = converted['body']['project']
        png = base64.b64decode(project['page_previews'][0]['data'].split(',', 1)[1])
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        project.update(name='手录校对', automatic_mode=False, selection=dict(bpm=120, start_beat=0, end_beat=1, range_reviewed=True),
                       notes=[dict(id='manual-1', page=1, hand='right', pitch='C4', finger=1,
                                   beat=0, duration_beats=1, confirmed=True)])
        exported = self.api.request('/api/software/export', 'POST', {'project': project})
        self.assertEqual(exported['status'], 200, exported)
        result = exported['body']
        score_bytes = base64.b64decode(result['base64'])
        self.assertEqual(decode(score_bytes)['notes'][0]['pitch'], 60)
        self.assertEqual(result['bytes'], 144)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['package_base64']))) as package:
            self.assertIsNone(package.testzip())
            self.assertEqual(package.read('score.pgl'), score_bytes)
            self.assertEqual(package.read('pages/1.png'), png)
            manifest = json.loads(package.read('source.json'))
        source = self.api.request('/api/software/source/' + manifest['score_sha256'] + '/1')
        self.assertEqual(source['status'], 200)
        self.assertTrue(source['binary'])
        self.assertEqual(source['headers']['content-type'], 'image/png')
        self.assertEqual(base64.b64decode(source['body']), png)
        missing = self.api.request('/api/software/source/' + manifest['score_sha256'] + '/2')
        self.assertEqual(missing['status'], 404)
        self.assertEqual(self.session.commands, [])


if __name__ == '__main__':
    unittest.main()
