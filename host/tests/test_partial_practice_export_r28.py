"""Partial practice export must retain its identity, source and explicit omissions."""
from copy import deepcopy
from pathlib import Path
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import SoftwareConsole
from native_api import NativeAPI
from score_automatic import export_automatic
from score_codec import encode, decode
from score_sources import ScoreSources
from test_native_api import FakeSession
from test_software_console import FakeBridge


def project(title='通用练习'):
    return dict(name=title, source_sha256='a'*64, automatic_mode=True,
                performance_policy=dict(mode='practice'), written_duration_beats=4,
                selection=dict(bpm=120, start_beat=0), pages=[dict(page=1, width=100, height=100)],
                notes=[dict(id='first', page=1, system=1, measure=1, hand='right', pitch='C4', finger=1, beat=0, duration_beats=1),
                       dict(id='last', page=1, system=1, measure=1, hand='right', pitch='E4', finger=2, beat=2, duration_beats=1)])


def unfinished(p):
    p['notes'].append(dict(id='manual-unfinished', page=1, hand='right', pitch=None, finger=None,
                           beat=None, duration_beats=None, issues=['manual_entry_requires_review']))
    return p


class PartialPracticeExport(unittest.TestCase):
    def test_omission_label_keeps_the_same_terminal_arrangement_identity(self):
        base=project();full=export_automatic(base);p=unfinished(deepcopy(base));original=deepcopy(p)
        partial=export_automatic(p,skip_pending=True)
        self.assertEqual(p,original)
        self.assertEqual(partial['performance']['arrangement_id'],full['performance']['arrangement_id'])
        self.assertEqual(partial['notes'],full['notes']);self.assertEqual(partial['performance']['audio_events'],full['performance']['audio_events'])
        self.assertTrue(partial['title'].endswith('（练习·'+partial['performance']['arrangement_id'][:16]+'）'))
        self.assertIn('跳过1处待处理',partial['title'])
        self.assertEqual(partial['partial_export']['skipped_pending'][0]['id'],'manual-unfinished')
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder);blob=encode(partial);self.assertTrue(store.associate(blob,p,partial))
            with zipfile.ZipFile(io.BytesIO(store.package(blob))) as bundle:
                data=json.loads(bundle.read('source.json'))
                self.assertEqual(bundle.read('score.pgl'),blob)
                self.assertEqual(data['performance']['arrangement_id'],partial['performance']['arrangement_id'])
                self.assertEqual(data['partial_export']['skipped_pending_count'],1)

    def test_long_unicode_titles_keep_both_labels_within_pgl96_bytes(self):
        for title in ['很长的中文练习名称'*25, 'Piano🎹混合曲名'*30]:
            with self.subTest(title=title[:16]):
                p=unfinished(project(title));partial=export_automatic(p,skip_pending=True);wire=decode(encode(partial))
                self.assertLessEqual(len(wire['title'].encode('utf-8')),96)
                self.assertIn('跳过1处待处理',wire['title'])
                self.assertTrue(wire['title'].endswith('（练习·'+partial['performance']['arrangement_id'][:16]+'）'))

    def test_real_export_api_reports_omission_and_returns_a_valid_practice_package(self):
        p=unfinished(project());before=deepcopy(p)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,LOCALAPPDATA=folder),patch('serial.Serial',side_effect=AssertionError('No serial allowed')):
            api=NativeAPI(FakeSession(folder))
            self.assertEqual(api.request('/api/software/export','POST',dict(project=p))['status'],400)
            reply=api.request('/api/software/export','POST',dict(project=p,skip_pending=True))
            self.assertEqual(reply['status'],200,reply.get('body'))
            body=reply['body'];self.assertEqual(body['skipped_pending_count'],1)
            self.assertEqual(body['package_extension'],'pglpack')
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(body['package_base64']))) as bundle:
                self.assertEqual(bundle.read('score.pgl'),base64.b64decode(body['base64']))
        self.assertEqual(p,before)

    def test_partial_export_still_rejects_a_wrong_motion_identity(self):
        p=unfinished(project());score=export_automatic(p,skip_pending=True)
        wrong=deepcopy(score);wrong['title']='不同动作（练习·'+'b'*16+'）'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'编排标识不一致'):
                ScoreSources(folder).associate(encode(wrong),p,score)

    def test_missing_hold_defaults_to_full_but_explicit_maintenance_values_remain(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,LOCALAPPDATA=folder):
            fake=FakeBridge();console=SoftwareConsole(fake)
            console.action('train',dict(mask=1));self.assertEqual(fake.commands[-1],'LIB TRAIN 1 100 100')
            console.action('pattern',dict(pattern=0,repeats=1,tempo=100));self.assertEqual(fake.commands[-1],'LIB PATTERN 0 1 100 100 100')
            console.action('train',dict(mask=1,hold=20));self.assertEqual(fake.commands[-1],'LIB TRAIN 1 20 100')
            console.action('pattern',dict(pattern=0,repeats=1,tempo=0,hold=0));self.assertEqual(fake.commands[-1],'LIB PATTERN 0 1 0 100 0')


if __name__=='__main__':unittest.main()
