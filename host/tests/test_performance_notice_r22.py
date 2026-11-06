"""Notation capability metadata never changes actions or adds attention."""
from pathlib import Path
from copy import deepcopy
import base64,io,json,os,sys,tempfile,unittest,zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent;HOST=ROOT.parents[2]/'repo/host'
sys.path.insert(0,str(HOST));sys.path.insert(0,str(HOST/'tests'));sys.path.insert(0,str(ROOT/'candidate'))
import score_performance,score_automatic,score_sources,bridge
from score_performance import performance_notice,source_ids
from score_automatic import check_project,export_automatic
from score_codec import encode,decode
from score_sources import ScoreSources
from native_api import NativeAPI
from test_native_api import FakeSession
from test_score_sources import preview

def note(ident,beat,pitch='C4',finger=1,**extra):
    return dict(id=ident,page=1,system=1,measure=1,hand='right',pitch=pitch,finger=finger,
                beat=beat,duration_beats=1,confirmed=False,issues=[],**extra)

def project():
    a=note('arpeggio',0);a['issues']=['arpeggio_requires_review']
    return dict(name='独立合成奏法',source_sha256='c'*64,automatic_mode=True,
                selection=dict(bpm=120,start_beat=0,end_beat=2,range_reviewed=True,repeat_mode='written'),
                notes=[a,note('ordinary',1,pitch='E4',finger=3)])

def ordinary_bytes():
    return encode(dict(version=1,hand='right',title='独立合成奏法',duration_ms=1000,notes=[
        dict(t_ms=0,duration_ms=500,pitch=60,finger=1),dict(t_ms=500,duration_ms=500,pitch=64,finger=3)]))

class NoticeTests(unittest.TestCase):
    def test_plain_score_has_no_new_notice_and_same_pgl(self):
        p=project();p['notes'][0]['issues']=[]
        self.assertNotIn('performance_notice',check_project(p)['automatic'])
        self.assertNotIn('performance_notice',export_automatic(p))
        self.assertEqual(encode(export_automatic(p)),ordinary_bytes())

    def test_arpeggio_notice_does_not_make_new_attention_or_change_actions(self):
        p=project();before=deepcopy(p);checked=check_project(p)
        self.assertTrue(checked['automatic']['ready'])
        self.assertEqual(checked['automatic']['attention_notes'],0)
        score=export_automatic(p);self.assertEqual(encode(score),ordinary_bytes())
        self.assertEqual(p,before)
        f=score['performance_notice']['features'][0]
        self.assertEqual(f,dict(kind='arpeggio',rendering='written-attacks',source_note_ids=['arpeggio']))
        self.assertIn('琶音未展开',score['performance_notice']['message'])
        self.assertIn('已导出',score['performance_notice']['message'])

    def test_selection_filters_outside_marker(self):
        p=project();p['selection']['start_beat']=1
        self.assertNotIn('performance_notice',check_project(p)['automatic'])
        self.assertNotIn('performance_notice',export_automatic(p))

    def test_left_and_excluded_markers_do_not_add_notice(self):
        p=project();p['notes'][0]['excluded']=True
        left=note('left',0);left.update(hand='left',issues=['arpeggio_requires_review']);p['notes'].append(left)
        self.assertNotIn('performance_notice',export_automatic(p))

    def test_partial_export_notice_only_names_exported_sources(self):
        p=project();p['notes'][0]['finger']=None;p['notes'][0]['source_fingering_state']='unresolved'
        result=export_automatic(p,skip_pending=True)
        self.assertEqual(result['partial_export']['skipped_pending_count'],1)
        self.assertNotIn('performance_notice',result)
        self.assertEqual(source_ids(result),{'ordinary'})

    def test_quantized_tremolo_notice_maps_back_to_true_source_ids(self):
        p=project();p['selection']['end_beat']=4
        p['notes']=[dict(note('endpoint-'+str(side),0,pitch=pitch,finger=side+1),duration_beats=4,
            tremolo_group='synthetic',tremolo_side=side,tremolo_step_beats=.25,tremolo_span_beats=4)
            for side,pitch in [(0,'C4'),(1,'G4')]]
        result=export_automatic(p);self.assertEqual(len(result['notes']),16)
        expected=dict(version=1,hand='right',title='独立合成奏法',duration_ms=2000,
            notes=[dict(t_ms=i*125,duration_ms=125,pitch=60 if i%2==0 else 67,finger=i%2+1) for i in range(16)])
        self.assertEqual(encode(result),encode(expected))
        f=result['performance_notice']['features'][0]
        self.assertEqual(f['rendering'],'quantized-written-subdivision')
        self.assertEqual(set(f['source_note_ids']),{'endpoint-0','endpoint-1'})
        self.assertIn('速度需核对',result['performance_notice']['message'])

    def test_unexpanded_tremolo_is_never_claimed_as_expanded(self):
        n=note('t',0);n['tremolo_group']='observed'
        notice=performance_notice([n],{'t'},exported=True)
        self.assertEqual(notice['features'][0]['rendering'],'written-attacks')
        self.assertIn('震音未展开',notice['message'])

    def test_unsupported_unknown_issues_are_not_claimed_detected_or_supported(self):
        n=note('n',0);n['issues']=['not_a_recognized_mordent']
        self.assertIsNone(performance_notice([n],{'n'},exported=True))

    def test_notice_identity_filter_and_deduplication(self):
        n=note('n',0);n['issues']=['arpeggio_requires_review']
        self.assertIsNone(performance_notice([n],{'other'},exported=True))
        notice=performance_notice([n,deepcopy(n)],{'n'},exported=True)
        self.assertEqual(notice['features'][0]['source_note_ids'],['n'])

    def test_source_association_and_portable_package_retain_notice_not_device_bytes(self):
        p=project();score=export_automatic(p);blob=encode(score)
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder);store.record_document(p['source_sha256'],[preview()])
            self.assertTrue(store.associate(blob,p,score))
            self.assertEqual(store.lookup(blob)['performance_notice'],score['performance_notice'])
            with zipfile.ZipFile(io.BytesIO(store.package(blob))) as package:
                self.assertEqual(package.read('score.pgl'),blob)
                self.assertEqual(json.loads(package.read('source.json'))['performance_notice'],score['performance_notice'])
        self.assertNotIn('performance_notice',decode(blob))

class APINoticeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,LOCALAPPDATA=self.temp.name);env.start();self.addCleanup(env.stop)
        for name in ('socket.socket','serial.Serial','serial.serial_for_url','bridge.ThreadingHTTPServer','webbrowser.open'):
            p=patch(name,side_effect=AssertionError('No external transport'));p.start();self.addCleanup(p.stop)
        self.api=NativeAPI(FakeSession(self.temp.name))

    def test_real_route_retains_capability_notice_and_genuine_package(self):
        p=project();ScoreSources().record_document(p['source_sha256'],[preview()])
        response=self.api.request('/api/software/export','POST',dict(project=p))
        self.assertEqual(response['status'],200,response)
        body=response['body'];self.assertIn('琶音未展开',body['performance_notice']['message'])
        blob=base64.b64decode(body['base64']);self.assertEqual(blob,ordinary_bytes())
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(body['package_base64']))) as package:
            self.assertEqual(json.loads(package.read('source.json'))['performance_notice'],body['performance_notice'])

    def test_manual_legacy_export_also_reports_observed_unexpanded_arpeggio(self):
        p=project();p['automatic_mode']=False
        for n in p['notes']:n['confirmed']=True
        response=self.api.request('/api/software/export','POST',dict(project=p))
        self.assertEqual(response['status'],200,response)
        self.assertIn('琶音未展开',response['body']['performance_notice']['message'])

if __name__=='__main__':unittest.main()
