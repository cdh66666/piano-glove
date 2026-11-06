"""Snapshot ownership, recovery and exact source/export equivalence."""
from pathlib import Path
from copy import deepcopy
import hashlib,importlib.util,json,sys,tempfile,unittest
from unittest.mock import patch
HOST=Path(__file__).resolve().parents[1];HERE=HOST.parent.parent/'evidence/memory-recognition-r24-20261029'
sys.path.insert(0,str(HOST))
import workspace_store
from workspace_store import WorkspaceStore
import score_automatic as candidate
from score_codec import encode
spec=importlib.util.spec_from_file_location('r23_automatic_baseline',HERE/'before-r23/score_automatic.py')
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)

def source():
    return dict(name='Independent memory preservation',source_sha256='7'*64,recognizer='independent-reader',source_kind='manual',recognition_performed=False,
        notes=[dict(id='a',hand='right',page=1,system=1,measure=1,pitch='C4',finger=1,source_fingering_state='printed',beat=0,duration_beats=1,manual_fields=['finger'],performance_override={'reviewed':True},performance_state={'stale':[0]*100}),
               dict(id='b',hand='right',page=1,system=1,measure=1,pitch='D4',finger=None,source_fingering_state='unmarked',beat=1,duration_beats=1)],
        rests=[],selection=dict(bpm=120,start_beat=0,repeat_mode='written'),performance_policy=dict(mode='practice'),
        performance=dict(old=['discarded']*100),automatic=dict(stale=True),export_scope=dict(stale=True))

class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=WorkspaceStore(self.temp.name)
        self.p=source();self.ui=dict(tab='convert',row='1:1',sound=False)

    def payload(self):return json.dumps(dict(project=self.p,ui=self.ui),ensure_ascii=False)

    def test_json_api_saves_one_owned_tree_without_second_deepcopy(self):
        self.p['page_previews']=[dict(page=1,data='original PNG kept elsewhere')]
        original=deepcopy(self.p)
        with patch.object(workspace_store,'deepcopy',side_effect=AssertionError('Already owned JSON must not be copied again')):
            self.assertEqual(self.store.save_json(self.payload()),{'saved':True})
        saved=self.store.review('7'*64)
        self.assertNotIn('page_previews',saved);self.assertEqual(saved['notes'],self.p['notes']);self.assertEqual(self.p,original)

    def test_public_object_api_keeps_defensive_copy_and_source_unchanged(self):
        state=dict(project=self.p,ui=self.ui);old=deepcopy(state)
        with patch.object(workspace_store,'deepcopy',wraps=deepcopy) as copy:
            self.store.save(state);self.assertEqual(copy.call_count,1)
        self.assertEqual(state,old)

    def test_same_version_save_does_not_reload_an_unchanged_large_review(self):
        self.store.save_json(self.payload());original=Path.read_text
        def read(path,*a,**kw):
            if path.name.endswith('.review.json'):raise AssertionError('Unchanged version cache must avoid loading the whole review')
            return original(path,*a,**kw)
        self.p['notes'][0]['finger']=4
        with patch.object(Path,'read_text',read):self.store.save_json(self.payload())
        self.assertEqual(self.store.review('7'*64)['notes'][0]['finger'],4)

    def test_external_corruption_invalidates_cache_and_is_recoverable(self):
        self.store.save_json(self.payload());path=self.store.root/('7'*64+'.review.json');bad=b'{incomplete external edit'
        path.write_bytes(bad);self.store.save_json(self.payload())
        self.assertEqual((self.store.root/('7'*64+'.before-unreadable.json')).read_bytes(),bad)
        self.assertEqual(len(self.store.review('7'*64)['notes']),2)

    def test_version_backup_retains_exact_manual_edits_and_bytes(self):
        self.p['notes'][0].update(excluded=True,excluded_manual=True,confirmed=False)
        self.store.save_json(self.payload());path=self.store.root/('7'*64+'.review.json');original=path.read_bytes()
        self.p['recognizer']='independent-reader-v2';self.store.save_json(self.payload())
        self.assertEqual((self.store.root/('7'*64+'.before-independent-reader.json')).read_bytes(),original)

    def test_restarted_store_checks_old_content_before_caching(self):
        self.store.save_json(self.payload());restarted=WorkspaceStore(self.temp.name)
        saved=restarted.review('7'*64);self.assertEqual(saved['recognizer'],'independent-reader')
        restarted.save_json(self.payload());self.assertEqual(restarted.last()['source_sha256'],'7'*64)

    def test_json_api_rejects_nonobject_snapshot(self):
        for bad in ('[]','null','false',3):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.store.save_json(bad)

    def test_streamed_json_is_identical_utf8_and_failed_write_keeps_previous_file(self):
        value=dict(text='音符🙂\\\"\n'*20000,values=[None,True,False,1,1.0,1/3,1e-8],nested={'2':['x','♭']})
        value.update({None:'null key',3.5:'numeric key','quote:😀':'key'})
        target=self.store.root/'exact.json';self.store._write(target,value)
        expected=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf8')
        self.assertEqual(target.read_bytes(),expected)
        with self.assertRaises(TypeError):self.store._write(target,dict(text=value['text'],bad=object()))
        self.assertEqual(target.read_bytes(),expected)

class ValidationCopyTests(unittest.TestCase):
    def test_practice_check_result_equals_baseline_and_source_is_unchanged(self):
        p=source();before=deepcopy(p)
        self.assertEqual(candidate.check_project(p),baseline.check_project(p));self.assertEqual(p,before)

    def test_strict_check_result_equals_baseline(self):
        p=source();p['performance_policy']={'mode':'strict'}
        self.assertEqual(candidate.check_project(p),baseline.check_project(p))

    def test_export_motor_audio_identity_and_source_map_equal(self):
        p=source();before=deepcopy(p);a=candidate.export_automatic(p);b=baseline.export_automatic(p)
        self.assertEqual(encode(a),encode(b));self.assertEqual(a['performance'],b['performance']);self.assertEqual(p,before)

    def test_interpretation_and_manual_fields_are_never_discarded(self):
        p=source();p['notes'][0]['performance_marks']=[dict(kind='trill',group_id='ornament',options={})]
        p['notes'][0]['performance_override'].update(rate_hz=4,aux_finger=2)
        self.assertEqual(candidate.export_automatic(p)['performance'],baseline.export_automatic(p)['performance'])

if __name__=='__main__':unittest.main(verbosity=2)
