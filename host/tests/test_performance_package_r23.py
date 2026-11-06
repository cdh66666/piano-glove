"""Actual motion-PGL/rich-audio roundtrips; no serial or user documents."""
from copy import deepcopy
from pathlib import Path
import base64,io,json,sys,tempfile,unittest,zipfile
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_codec import encode,decode
from score_sources import ScoreSources
from performance_schema import clean_performance,performance_identity
import os
from unittest.mock import patch


def performance():
    p=dict(version=1,mode='practice',source_identity='a'*64,duration_ms=1000,
        audio_events=[dict(t_ms=0,duration_ms=500,pitch=60,velocity=96,finger=1,source_note_ids=['root']),
                      dict(t_ms=0,duration_ms=1000,pitch=64,velocity=72,finger=None,source_note_ids=['gray'])],
        source_map={'root':dict(page=1,pitch='C4'),'gray':dict(page=2,pitch='E4')},
        display_title='独立合成和弦',estimates=[],features=[],coverage={'missing_source_ids':[]})
    p['arrangement_id']=performance_identity(p)
    return p


def score(p=None):
    p=performance() if p is None else p
    return dict(version=1,hand='right',title='合弦（练习·'+p['arrangement_id'][:16]+'）',duration_ms=1000,
        notes=[dict(t_ms=0,duration_ms=500,pitch=60,finger=1,velocity=96,amplitude_pct=100)],
        source_notes=[dict(id='root',source_note_ids=['root'],page=1,bbox=[20,30,30,40])],performance=p)


def page(n):
    out=io.BytesIO()
    with Image.new('RGB',(100,100),'white') as im:im.save(out,format='PNG')
    return dict(page=n,data='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode())


class PerformancePackageTests(unittest.TestCase):
    def test_rich_v2_preserves_two_audio_voices_and_one_valid_motor(self):
        s=score();p=dict(source_sha256='a'*64,notes=[
            dict(id='root',page=1,bbox=[20,30,30,40]),dict(id='gray',page=2,bbox=[40,50,50,60])])
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder);store.record_document('a'*64,[page(1),page(2)],
                [dict(page=1,width=100,height=100),dict(page=2,width=100,height=100)])
            blob=encode(s);self.assertTrue(store.associate(blob,p,s))
            packaged=store.package(blob)
            with zipfile.ZipFile(io.BytesIO(packaged)) as bundle:
                metadata=json.loads(bundle.read('source.json'))
                self.assertEqual(metadata['version'],2)
                self.assertEqual(bundle.read('score.pgl'),blob)
                self.assertEqual(len(decode(blob)['notes']),1)
                self.assertEqual(len(metadata['performance']['audio_events']),2)
                self.assertEqual({x['page'] for x in metadata['pages']},{1,2})
                self.assertEqual(metadata['performance']['source_map']['gray']['location']['page'],2)
            self.assertEqual(packaged,store.package(blob))

    def test_manual_score_has_complete_sound_package_without_fake_pdf(self):
        s=score()
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder);blob=encode(s)
            self.assertTrue(store.associate(blob,{'notes':[]},s))
            with zipfile.ZipFile(io.BytesIO(store.package(blob))) as bundle:
                self.assertEqual(set(bundle.namelist()),{'score.pgl','source.json'})
                metadata=json.loads(bundle.read('source.json'))
                self.assertEqual(metadata['pages'],[])
                self.assertEqual(metadata['source_kind'],'score-model')
                self.assertEqual(len(metadata['performance']['audio_events']),2)

    def test_tampered_sound_is_rejected_even_when_motor_unchanged(self):
        p=performance();p['audio_events'][1]['pitch']=65
        with self.assertRaisesRegex(ValueError,'编排标识'):clean_performance(p,1000)

    def test_distinct_sound_changes_identity_and_pgl_artifact(self):
        p=performance();q=deepcopy(p);q['audio_events'][1]['pitch']=65;q['arrangement_id']=performance_identity(q)
        self.assertNotEqual(p['arrangement_id'],q['arrangement_id'])
        self.assertNotEqual(encode(score(p)),encode(score(q)))

    def test_legacy_without_performance_stays_v1(self):
        s=score();s.pop('performance')
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder);store.record_document('a'*64,[page(1)])
            blob=encode(s);store.associate(blob,{'source_sha256':'a'*64},s)
            with zipfile.ZipFile(io.BytesIO(store.package(blob))) as bundle:
                metadata=json.loads(bundle.read('source.json'))
                self.assertEqual(metadata['version'],1)
                self.assertNotIn('performance',metadata)

    def test_invalid_timing_or_source_mapping_rejected(self):
        for change in ('tail','origin','finger'):
            p=performance()
            if change=='tail':p['audio_events'][0]['duration_ms']=2000
            elif change=='origin':p['source_map'].pop('gray')
            else:p['audio_events'][0]['finger']=0
            with self.subTest(change=change),self.assertRaises(ValueError):clean_performance(p,1000)

    def test_wrong_motion_artifact_cannot_pick_up_another_arrangement(self):
        p=performance();q=deepcopy(p);q['audio_events'][1]['pitch']=67;q['arrangement_id']=performance_identity(q)
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder)
            with self.assertRaisesRegex(ValueError,'编排标识'):
                store.associate(encode(score(p)),{'notes':[]},score(q))

    def test_pdf_identity_cannot_be_reassigned_to_another_original(self):
        s=score()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'原谱标识'):
                ScoreSources(folder).associate(encode(s),{'source_sha256':'b'*64},s)

    def test_saved_audio_corruption_is_rejected_after_restart(self):
        s=score()
        with tempfile.TemporaryDirectory() as folder:
            store=ScoreSources(folder);blob=encode(s);store.associate(blob,{'notes':[]},s)
            path=Path(folder)/'scores'/(store.lookup(blob)['score_sha256']+'.json')
            value=json.loads(path.read_text(encoding='utf8'));value['performance']['audio_events'][1]['pitch']=67
            path.write_text(json.dumps(value),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'编排标识'):
                ScoreSources(folder).lookup(blob)


class RichExportRouteTests(unittest.TestCase):
    def setUp(self):
        from test_native_api import FakeSession
        from native_api import NativeAPI
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,LOCALAPPDATA=self.tmp.name);env.start();self.addCleanup(env.stop)
        for name in ('socket.socket','serial.Serial','serial.serial_for_url','bridge.ThreadingHTTPServer','webbrowser.open'):
            handle=patch(name,side_effect=AssertionError('No device or external transport'))
            handle.start();self.addCleanup(handle.stop)
        self.api=NativeAPI(FakeSession(self.tmp.name))

    def test_actual_export_route_requires_v2_and_returns_small_summary(self):
        s=score()
        with patch('score_automatic.export_automatic',return_value=s):
            result=self.api.request('/api/software/export','POST',dict(project={'automatic_mode':True,'notes':[]}))
        self.assertEqual(result['status'],200,result)
        body=result['body'];self.assertEqual(body['preferred_extension'],'pglpack')
        self.assertTrue(body['motion_only_pgl'])
        self.assertNotIn('audio_events',body['performance_summary'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(body['package_base64']))) as package:
            metadata=json.loads(package.read('source.json'))
            self.assertEqual(metadata['version'],2)
            self.assertEqual(len(metadata['performance']['audio_events']),2)

    def test_pack_failure_does_not_claim_complete_export_of_motor_only(self):
        with patch('score_automatic.export_automatic',return_value=score()),patch.object(ScoreSources,'package',side_effect=ValueError('synthetic package size limit')):
            result=self.api.request('/api/software/export','POST',dict(project={'automatic_mode':True,'notes':[]}))
        self.assertEqual(result['status'],400,result)
        self.assertFalse(result['body']['ok'])
        self.assertNotIn('base64',result['body'])


if __name__=='__main__':unittest.main()
