"""Native original-PDF intake and review recovery, without GUI or devices."""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree

HOST = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOST))
import native_window as native
from workspace_store import WorkspaceStore


def pdf_bytes():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    document = PdfWriter()
    page = document.add_blank_page(width=400, height=200)
    content = DecodedStreamObject()
    content.set_data(b'0.5 w\n' + b'\n'.join(('20 %d m 380 %d l S' % (y, y)).encode()
                                           for y in (70, 78, 86, 94, 102)))
    page[NameObject('/Contents')] = content
    output = BytesIO()
    document.write(output)
    return output.getvalue()


def as64(data):
    return base64.b64encode(data).decode('ascii')


def review(digest):
    return dict(name='我的校对', source_sha256=digest, page_previews=[{'page': 1, 'data': 'large-preview'}],
        selection=dict(bpm=95, start_beat=0, end_beat=4, range_reviewed=False),
        notes=[dict(id='n1', page=1, pitch='C4', finger=1, beat=0, duration_beats=1, confirmed=True),
               dict(id='n2', page=1, pitch='D4', finger=2, beat=1, duration_beats=1, confirmed=False)])


UI = dict(tab='convert', row='2:3', page=1, rowMode=False, zoom='150',
          settings=dict(tempo='135', amplitude='45', hold='70', sound=False))


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='piano-workspace-test-')
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name)
        self.store = WorkspaceStore(self.data_root)
        self.pdf = pdf_bytes()
        self.digest = hashlib.sha256(self.pdf).hexdigest()

    def test_parser_upgrade_retains_a_recoverable_copy_of_all_previous_edits(self):
        old=review(self.digest);old['recognizer']='vector-v5'
        old['notes'][1].update(finger=4,confirmed=False,excluded=True,excluded_manual=True,manual_fields=['finger'])
        self.store.save({'project':old,'ui':UI})
        new=review(self.digest);new['recognizer']='vector-v6';new['notes'][1]['finger']=2
        self.store.save({'project':new,'ui':UI})
        backup=self.store.root/(self.digest+'.before-vector-v5.json')
        preserved=json.loads(backup.read_text(encoding='utf-8'))
        self.assertEqual(preserved['notes'][1]['finger'],4)
        self.assertTrue(preserved['notes'][1]['excluded'])
        self.assertFalse(preserved['notes'][1]['confirmed'])
        self.assertEqual(self.store.review(self.digest)['recognizer'],'vector-v6')
        new['notes'][1]['finger']=3;self.store.save({'project':new,'ui':UI})
        self.assertEqual(json.loads(backup.read_text(encoding='utf-8'))['notes'][1]['finger'],4)

    def test_new_valid_save_preserves_unreadable_old_bytes_without_blocking_save(self):
        current=self.store.root/(self.digest+'.review.json');current.write_bytes(b'{partial')
        self.store.save({'project':review(self.digest),'ui':UI})
        self.assertEqual((self.store.root/(self.digest+'.before-unreadable.json')).read_bytes(),b'{partial')
        self.assertEqual(len(self.store.review(self.digest)['notes']),2)

    def test_remember_and_read_verify_original_digest_and_replace_same_content_metadata(self):
        self.store.remember('原谱.pdf', as64(self.pdf), self.digest)
        self.store.remember('同一原谱另存.pdf', as64(self.pdf), self.digest)
        imports = self.store.imports()
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]['id'], 'import:' + self.digest)
        self.assertEqual(imports[0]['filename'], '同一原谱另存.pdf')
        metadata, original = self.store.read_source(self.digest)
        self.assertEqual(original, self.pdf)
        self.assertEqual(metadata['bytes'], len(self.pdf))
        self.assertEqual(hashlib.sha256(original).hexdigest(), metadata['sha256'])

    def test_wrong_recognition_digest_and_changed_saved_pdf_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '不一致'):
            self.store.remember('原谱.pdf', as64(self.pdf), '0' * 64)
        self.assertEqual(self.store.imports(), [])
        self.store.remember('原谱.pdf', as64(self.pdf), self.digest)
        saved = self.store.root / (self.digest + '.pdf')
        saved.write_bytes(self.pdf + b'changed')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.store.read_source(self.digest)
        with self.assertRaisesRegex(ValueError, '编号'):
            self.store.read_source('../other-file')

    def test_review_excludes_preview_bytes_preserves_partial_approval_and_ui_after_restart(self):
        project = review(self.digest)
        original = deepcopy(project)
        self.assertEqual(self.store.save({'project': project, 'ui': UI}), {'saved': True})
        restarted = WorkspaceStore(self.data_root)
        saved = restarted.review(self.digest)
        self.assertNotIn('page_previews', saved)
        self.assertEqual(saved['notes'], project['notes'])
        self.assertEqual([note['confirmed'] for note in saved['notes']], [True, False])
        self.assertEqual(project, original)
        self.assertEqual(restarted.last(), {'source_sha256': self.digest, 'ui': UI})
        self.assertFalse(any(path.suffix == '.pending' for path in self.store.root.iterdir()))

    def test_ui_only_save_keeps_review_file_bytes_and_source_identity_unchanged(self):
        self.store.save({'project':review(self.digest),'ui':UI})
        path=self.store.root/(self.digest+'.review.json');before=path.read_bytes()
        next_ui=dict(UI,tab='train')
        self.store.save({'project':None,'ui':next_ui})
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),hashlib.sha256(before).hexdigest())
        self.assertEqual(self.store.last(),{'source_sha256':self.digest,'ui':next_ui})

    def test_saving_only_current_ui_keeps_previous_review_and_source(self):
        project = review(self.digest)
        self.store.save({'project': project, 'ui': UI})
        changed = dict(UI, tab='train', settings=dict(UI['settings'], hold='50'))
        self.store.save({'project': None, 'ui': changed})
        self.assertEqual(self.store.last(), {'source_sha256': self.digest, 'ui': changed})
        self.assertEqual(self.store.review(self.digest)['notes'], project['notes'])

    def test_invalid_review_does_not_replace_saved_source_or_progress(self):
        self.store.save({'project': review(self.digest), 'ui': UI})
        previous = self.store.last()
        for project in ({'source_sha256': '../bad', 'notes': []}, {'source_sha256': self.digest, 'notes': None}):
            with self.assertRaisesRegex(ValueError, '校对项目'):
                self.store.save({'project': project, 'ui': {}})
        self.assertEqual(self.store.last(), previous)
        self.assertIsNone(self.store.review('../bad'))

    def test_stage_queue_is_durable_and_taken_once_without_changing_review(self):
        self.store.save({'project': review(self.digest), 'ui': UI})
        files = [{'name': '原谱.pdf', 'content': as64(self.pdf)},
                 {'name': '节选.pgl', 'content': as64(b'PGL1-queued-only')}]
        self.assertTrue(self.store.stage(files))
        restarted = WorkspaceStore(self.data_root)
        self.assertEqual(restarted.take_staged(), files)
        self.assertEqual(restarted.take_staged(), [])
        self.assertEqual(restarted.last()['ui'], UI)
        self.assertEqual(restarted.imports(), [])


class DesktopWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='piano-desktop-workspace-test-')
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name)
        contexts = [patch.object(native.runtime, 'data_directory', return_value=self.data_root),
                    patch.object(native.runtime, 'resources', return_value=HOST),
                    patch.dict('os.environ', LOCALAPPDATA=str(self.data_root))]
        for target in ('socket.socket', 'serial.Serial', 'serial.serial_for_url', 'webbrowser.open'):
            contexts.append(patch(target, side_effect=AssertionError('unexpected transport: ' + target)))
        for context in contexts:
            context.start()
            self.addCleanup(context.stop)
        self.session = Mock(connected=False)
        self.session.recording_root = str(self.data_root / 'recordings')
        self.session.firmware.serialExclusive = False
        self.session.status.return_value = {'connected': False}
        self.session.send.side_effect = AssertionError('no device traffic during file/workspace operations')
        self.api = native.DesktopAPI(self.session)

    def tearDown(self):
        self.session.send.assert_not_called()

    def test_catalog_filters_duplicate_builtin_import_and_repeated_original(self):
        entry = self.api.catalog_list()['builtins'][0]
        original = self.api._catalog.read(entry['id'])
        for name in (entry['filename'], '内置原谱副本.pdf'):
            self.assertEqual(self.api.register_pdf(name, as64(original)), 'import:' + entry['sha256'])
        catalog = self.api.catalog_list()
        self.assertEqual(len(catalog['builtins']), 100)  # 11-04 内置扩到 100 首
        self.assertEqual(sum(row.get('source_kind')=='manual' for row in catalog['builtins']),0)  # 11-05 用户：认不出的 Megalovania 图片谱删掉
        self.assertEqual(sum(str(row.get('file','')).lower().endswith('.pdf') for row in catalog['builtins']),100)  # 11-05：100 首都是 PDF
        self.assertEqual(catalog['imports'], [])
        data = pdf_bytes()
        first = self.api.register_pdf('用户新谱.pdf', as64(data))
        self.assertEqual(self.api.register_pdf('同内容另存.pdf', as64(data)), first)
        self.assertEqual(len(self.api.catalog_list()['imports']), 1)

    def test_builtin_recognition_does_not_register_an_import_but_explicit_upload_does(self):
        entry = self.api.catalog_list()['builtins'][0]
        self.assertEqual(self.api.catalog_list()['imports'], [])
        with patch.object(self.api, '_convert', wraps=self.api._convert) as convert:
            opened = self.api.catalog_open(entry['id'], 120, True)
        self.assertTrue(convert.called)
        self.assertEqual(opened['project']['source_sha256'], entry['sha256'])
        self.assertEqual(self.api.catalog_list()['imports'], [])
        original = self.api._catalog.read(entry['id'])
        imported = self.api.register_pdf('用户主动导入.pdf', as64(original))
        self.assertEqual(imported, 'import:' + entry['sha256'])
        self.api.catalog_prepare(imported, 120, True)
        imports = self.api.catalog_list()['imports']
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]['filename'], '用户主动导入.pdf')

    def test_builtin_open_reuses_local_raw_cache_and_restores_saved_review_separately(self):
        opened = self.api.catalog_open('1002604')
        project = opened['project']
        self.assertIsNone(opened['review'])
        self.assertEqual(len(project['page_previews']), 2)
        self.assertTrue(project['notes'])
        self.assertTrue(all(not note['confirmed'] for note in project['notes']))
        user_review = deepcopy(project)
        user_review['notes'][0]['confirmed'] = True
        user_review['notes'][1]['pitch'] = 'F#4'
        user_review['notes'][1]['manual_fields'] = ['pitch']  # 真界面改音高会记下手动字段
        self.api.save_workspace({'project': user_review, 'ui': UI})
        restarted = native.DesktopAPI(self.session)
        with patch.object(restarted, '_convert', side_effect=AssertionError('raw cache not reused')):
            result = restarted.restore_workspace()
        self.assertEqual(result['ui'], UI)
        self.assertEqual(result['project']['source_sha256'], project['source_sha256'])
        self.assertTrue(all(not note['confirmed'] for note in result['project']['notes']))
        self.assertTrue(result['review']['notes'][0]['confirmed'])
        edited = {n['id']: n for n in result['review']['notes']}
        self.assertEqual(edited[user_review['notes'][1]['id']]['pitch'], 'F#4')
        self.assertFalse(edited[user_review['notes'][1]['id']]['confirmed'])
        self.assertNotIn('page_previews', result['review'])
        self.assertEqual(restarted.catalog_list()['imports'], [])

    def test_successful_native_convert_remembers_pdf_for_dict_and_json_callers(self):
        data = pdf_bytes()
        digest = hashlib.sha256(data).hexdigest()
        payload = {'filename': '直接拖入.pdf', 'base64': as64(data), 'bpm': 120}
        for body, headers in ((payload, None), (json.dumps(payload), {'Content-Type': 'application/json'})):
            response = self.api.request('/api/software/convert', 'POST', body, False, headers)
            self.assertEqual(response['status'], 200, response)
            self.assertEqual(response['body']['project']['source_sha256'], digest)
            self.assertTrue(response['body']['project']['page_previews'][0]['data'].startswith('data:image/png;base64,'))
        metadata, stored = self.api._workspace.read_source(digest)
        self.assertEqual(stored, data)
        self.assertEqual(metadata['filename'], payload['filename'])
        self.assertEqual(len(self.api.catalog_list()['imports']), 1)
        rejected = self.api.request('/api/software/convert', 'POST', dict(payload, base64=as64(b'not a PDF')))
        self.assertEqual(rejected['status'], 400)
        self.assertEqual(len(self.api.catalog_list()['imports']), 1)

    def test_reserved_original_can_be_manually_registered_opened_and_recovered(self):
        entry = self.api._catalog.get('1007271')
        original = HOST.parent.parent / 'evidence' / 'user-flow-20261024' / 'manual-pdfs' / entry['filename']
        if not original.is_file():
            self.skipTest('The deliberately external manual-test originals are not part of the source checkout')
        data = original.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
        identity = self.api.register_pdf(entry['filename'], as64(data))
        self.assertEqual(identity, 'import:' + entry['sha256'])
        self.assertEqual(self.api.catalog_list()['imports'][0]['id'], identity)
        opened = self.api.catalog_open(identity)
        project = opened['project']
        self.assertEqual(project['source_sha256'], entry['sha256'])
        self.assertEqual(len(project['page_previews']), 2)
        self.assertTrue(all(not note['confirmed'] for note in project['notes']))
        project['notes'][0]['confirmed'] = True
        self.api.save_workspace({'project': project, 'ui': UI})
        restored = native.DesktopAPI(self.session).restore_workspace()
        self.assertEqual(restored['ui'], UI)
        self.assertEqual(restored['project']['source_sha256'], entry['sha256'])
        self.assertTrue(restored['review']['notes'][0]['confirmed'])
        self.assertTrue(all(not note['confirmed'] for note in restored['project']['notes']))
        self.assertNotIn('page_previews', restored['review'])

    def test_missing_original_recovers_review_with_no_fabricated_preview(self):
        digest = hashlib.sha256(pdf_bytes()).hexdigest()
        saved = review(digest)
        self.api.save_workspace({'project': saved, 'ui': UI})
        restored = self.api.restore_workspace()
        self.assertEqual(restored['ui'], UI)
        self.assertEqual(restored['project']['notes'], saved['notes'])
        self.assertEqual(restored['project']['page_previews'], [])
        self.assertIsNone(restored['review'])

    def test_imported_pdf_reopen_uses_raw_cache_and_preserves_review_separately(self):
        data=pdf_bytes();identity=self.api.register_pdf('开发缓存.pdf',as64(data))
        with patch.object(self.api,'_convert',wraps=self.api._convert) as convert:
            first=self.api.catalog_open(identity)
            saved=deepcopy(first['project']);saved['name']='已改标题'
            self.api.save_workspace({'project':saved,'ui':UI})
            second=self.api.catalog_open(identity,bpm=96)
            self.assertEqual(convert.call_count,1)
            self.assertEqual(second['review']['name'],'已改标题')
            self.assertNotEqual(second['project']['name'],'已改标题')
            self.assertTrue(second['project']['page_previews'])
            self.api.catalog_open(identity,bpm=96,force=True)
            self.assertEqual(convert.call_count,2)
            self.assertEqual(self.api._workspace.review(saved['source_sha256'])['name'],'已改标题')

    def test_stage_and_take_native_files_never_convert_upload_or_select_a_device(self):
        files = [{'name': '原谱.pdf', 'content': as64(pdf_bytes())},
                 {'name': '曲谱.pgl', 'content': as64(b'PGL1-queued-only')}]
        with patch.object(self.api, '_convert', side_effect=AssertionError('staging converted file')), \
             patch.object(self.api, 'request', side_effect=AssertionError('staging called API')):
            self.assertTrue(self.api.stage_files(files))
            self.assertEqual(self.api.take_staged_files(), files)
            self.assertEqual(self.api.take_staged_files(), [])
        self.session.select_port.assert_not_called()
        self.assertEqual(self.api.catalog_list()['imports'], [])

    def test_phone_codes_use_current_ssid_and_fixed_independent_control_url(self):
        import qrcode
        ssid = 'PIANO_GLOVE_TEST'
        with patch.object(self.api, 'request', return_value={'status': 200, 'body': {'capacity': {'ap': ssid}}}) as request, \
             patch.object(qrcode, 'make', wraps=qrcode.make) as make:
            result = self.api.phone_connection()
        request.assert_called_once_with('/api/library')
        self.assertEqual(result['ssid'], ssid)
        self.assertEqual([call.args[0] for call in make.call_args_list],
                         ['WIFI:T:nopass;S:' + ssid + ';;', 'http://192.168.4.1/'])
        for name in ('wifi_qr', 'page_qr'):
            self.assertTrue(result[name].startswith('data:image/svg+xml;base64,'))
            svg = ElementTree.fromstring(base64.b64decode(result[name].split(',', 1)[1]))
            self.assertEqual(svg.tag, '{http://www.w3.org/2000/svg}svg')
            self.assertTrue(svg.attrib.get('viewBox'))
            self.assertTrue(svg.findall('.//{http://www.w3.org/2000/svg}path'))

    def test_phone_without_connected_ssid_does_not_invent_a_wifi_code(self):
        with patch.object(self.api, 'request', return_value={'status': 409, 'body': {'ok': False, 'error': 'not connected'}}):
            result = self.api.phone_connection()
        self.assertEqual(result['ssid'], '')
        self.assertIsNone(result['wifi_qr'])
        self.assertTrue(result['page_qr'].startswith('data:image/svg+xml;base64,'))


if __name__ == '__main__':
    unittest.main()
