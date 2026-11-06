"""Opt-in partial action export preserves source and does not invent fingers."""
from copy import deepcopy
from pathlib import Path
import base64,io,json,os,sys,tempfile,unittest,zipfile
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import check_project,export_automatic
from score_codec import decode,encode
from score_sources import ScoreSources
from native_api import NativeAPI
from test_native_api import FakeSession

def note(ident,beat,pitch,finger,duration=1,**kwargs):
    return dict(id=ident,page=1,system=1,measure=1,hand='right',beat=beat,pitch=pitch,
                finger=finger,duration_beats=duration,confirmed=False,**kwargs)

def score():
    return dict(name='独立合成谱',automatic_mode=True,written_duration_beats=8,
        selection=dict(bpm=120,start_beat=0,repeat_mode='written'),notes=[
            note('one',0,'C4',1),note('unknown',1,'D4',None,source_fingering_state='unresolved'),
            note('two',2,'E4',2),note('gray',3,'F4',None,source_fingering_state='unmarked'),
            note('overlap-a',4,'G4',3,2),note('overlap-b',5,'A4',3),note('last',7,'B4',5)])

class PartialExportTests(unittest.TestCase):
    def test_explicit_partial_skips_pending_actions_without_changing_source_or_time(self):
        project=score();before=deepcopy(project)
        full=check_project(project)
        self.assertFalse(full['automatic']['ready']);self.assertEqual(full['automatic']['attention_notes'],3)
        with self.assertRaisesRegex(ValueError,'还有 3 处'):export_automatic(project)
        partial=export_automatic(project,skip_pending=True)
        self.assertEqual(project,before)
        self.assertEqual(partial['partial_export']['skipped_pending_count'],3)
        self.assertEqual({n['id'] for n in partial['partial_export']['skipped_pending']},{'unknown','overlap-a','overlap-b'})
        restored=decode(encode(partial))
        self.assertEqual([(n['pitch'],n['t_ms']) for n in restored['notes']],[(60,0),(64,1000),(71,3500)])
        self.assertEqual(restored['duration_ms'],4000)
        self.assertIn('跳过3处待处理',restored['title'])

    def test_no_playable_actions_are_not_presented_as_successful_export(self):
        project=score();project['notes']=[project['notes'][1]]
        with self.assertRaises(ValueError):export_automatic(project,skip_pending=True)

    def test_source_excerpt_skips_only_its_own_pending_notes(self):
        project=score();project['selection']['end_beat']=3
        partial=export_automatic(project,skip_pending=True)
        self.assertEqual(partial['partial_export']['skipped_pending_count'],1)
        self.assertEqual(partial['partial_export']['skipped_pending'][0]['id'],'unknown')
        self.assertEqual([(n['pitch'],n['t_ms']) for n in partial['notes']],[(60,0),(64,1000)])
        self.assertEqual(partial['duration_ms'],1500)

    def test_non_boolean_skip_or_duplicate_ids_cannot_silently_omit_wrong_note(self):
        with self.assertRaises(ValueError):export_automatic(score(),skip_pending='true')
        project=score();project['notes'][1]['id']='one'
        with self.assertRaisesRegex(ValueError,'编号不唯一'):export_automatic(project,skip_pending=True)

    def test_skipping_tie_target_keeps_prior_attack_and_source_link(self):
        project=score();project['notes']=[note('root',0,'C4',1,tie_to='missing',tie_reviewed=True),
            note('missing',1,'C4',1,duration=None),note('tail',3,'D4',2)]
        before=deepcopy(project)
        result=export_automatic(project,skip_pending=True)
        self.assertEqual(project,before)
        self.assertEqual(result['partial_export']['skipped_pending_count'],1)
        self.assertEqual([(n['pitch'],n['t_ms'],n['duration_ms']) for n in result['notes']],[(60,0,500),(62,1500,500)])

    def test_old_project_without_written_length_keeps_skipped_tail_and_rest(self):
        project=score();project.pop('written_duration_beats')
        project['notes']=[note('first',0,'C4',1),note('late',10,'D4',None,source_fingering_state='unresolved')]
        original=deepcopy(project);partial=export_automatic(project,skip_pending=True)
        self.assertEqual(project,original);self.assertEqual(partial['duration_ms'],5500)
        project['notes'][1]['duration_beats']=None
        self.assertEqual(export_automatic(project,skip_pending=True)['duration_ms'],5000)
        project['rests']=[dict(hand='right',beat=12,duration=2)]
        self.assertEqual(export_automatic(project,skip_pending=True)['duration_ms'],7000)

    def test_left_hand_id_collision_does_not_block_right_hand_partial_export(self):
        project=score();left=note('one',0,'C3',1);left['hand']='left';project['notes'].append(left)
        before=deepcopy(left);result=export_automatic(project,skip_pending=True)
        self.assertEqual(result['partial_export']['skipped_pending_count'],3)
        self.assertEqual(project['notes'][-1],before)

    def test_long_chinese_title_keeps_the_omission_marker_in_valid_pgl(self):
        project=score();project['name']='很长的练习曲名'*20
        decoded=decode(encode(export_automatic(project,skip_pending=True)))
        self.assertIn('跳过3处待处理',decoded['title'])
        self.assertLessEqual(len(decoded['title'].encode('utf-8')),96)

    def test_api_requires_explicit_skip_and_reports_actual_omissions(self):
        project=score();before=deepcopy(project)
        with tempfile.TemporaryDirectory(prefix='piano-partial-export-') as folder, \
             patch.dict(os.environ,LOCALAPPDATA=folder), \
             patch('serial.Serial',side_effect=AssertionError('no real serial')):
            api=NativeAPI(FakeSession(folder))
            self.assertEqual(api.request('/api/software/export','POST',{'project':project})['status'],400)
            reply=api.request('/api/software/export','POST',{'project':project,'skip_pending':True})
            self.assertEqual(reply['status'],200)
            self.assertEqual(reply['body']['skipped_pending_count'],3)
            decoded=decode(base64.b64decode(reply['body']['base64']))
            self.assertIn('跳过3处待处理',decoded['title'])
            self.assertEqual(decoded['duration_ms'],4000)
        self.assertEqual(project,before)

    def test_partial_package_records_omissions_and_preserves_original_pages(self):
        project=score();project['source_sha256']='a'*64
        project['notes'][1]['page']=2
        result=export_automatic(project,skip_pending=True);blob=encode(result)
        image=io.BytesIO();Image.new('RGB',(12,16),'white').save(image,format='PNG')
        png='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode('ascii')
        with tempfile.TemporaryDirectory(prefix='piano-partial-source-') as folder:
            store=ScoreSources(folder);store.record_document(project['source_sha256'],[dict(page=1,data=png),dict(page=2,data=png)])
            self.assertTrue(store.associate(blob,project,result))
            with zipfile.ZipFile(io.BytesIO(store.package(blob))) as archive:
                manifest=json.loads(archive.read('source.json'))
                self.assertEqual(manifest['partial_export']['skipped_pending_count'],3)
                self.assertEqual({p['page'] for p in manifest['pages']},{1,2})
                self.assertEqual({n['id'] for n in manifest['partial_export']['skipped_pending']},{'unknown','overlap-a','overlap-b'})

if __name__=='__main__':unittest.main()
