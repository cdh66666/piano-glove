from pathlib import Path
from copy import deepcopy
import sys,unittest
from unittest.mock import Mock
HOST=Path(__file__).resolve().parents[1];HERE=HOST.parent.parent/'evidence/memory-recognition-r24-20261029'
sys.path.insert(0,str(HOST))
from native_window import DesktopAPI
from score_automatic import check_project

def project():
    return dict(name='independent receipt',source_sha256='7'*64,recognizer='independent',source_kind='manual',recognition_performed=False,
        selection=dict(bpm=120,start_beat=0,end_beat=None,repeat_mode='written'),performance_policy=dict(mode='practice'),
        notes=[dict(id='a',hand='right',page=1,system=1,measure=1,pitch='C4',finger=1,beat=0,duration_beats=1,source_fingering_state='printed')],rests=[])

class ValidatedOpenTests(unittest.TestCase):
    def api(self,review=None):
        api=object.__new__(DesktopAPI);api._catalog=Mock();api._catalog.project.side_effect=lambda *a,**kw:project()
        api._catalog.get.return_value={'sha256':'7'*64}
        api._progress_cache_token=Mock(return_value='none')
        api._workspace=Mock();api._workspace.review.return_value=review;return api

    def test_catalog_receipt_matches_the_actual_validated_fresh_state(self):
        result=self.api().catalog_open('independent')
        p,r=result['project'],result['native_validation']
        self.assertTrue(p['automatic']['ready']);self.assertEqual(r['source_sha256'],p['source_sha256'])
        self.assertEqual(r['notes'],len(p['notes']));self.assertEqual(r['selection'],p['selection'])
        self.assertEqual(r['automatic_version'],p['automatic']['version']);self.assertFalse(p['validation_pending'])
        repeated=check_project(p)
        self.assertEqual(p['automatic'],repeated['automatic']);self.assertEqual(p['performance'],repeated['performance'])
        for n,state in zip(p['notes'],repeated['notes']):
            for key,value in state.items():self.assertEqual(n.get(key),value,(key,n.get(key),value))

    def test_existing_review_never_receives_permission_to_skip_merge_validation(self):
        result=self.api(dict(notes=[dict(id='a',finger=4,manual_fields=['finger'])])).catalog_open('independent')
        self.assertIsNone(result['native_validation']);self.assertEqual(result['review']['notes'][0]['finger'],4)

    def test_error_state_remains_an_error_after_final_validation(self):
        p=project();p['notes'][0]['pitch']='invalid';DesktopAPI._finish_fresh_validation(p)
        self.assertFalse(p['automatic']['ready']);self.assertGreater(p['automatic']['attention_notes'],0)
        self.assertFalse(p['notes'][0]['automatic_ready'])

    def test_native_legacy_export_refuses_to_export_a_partial_review_as_a_whole_score(self):
        api=object.__new__(DesktopAPI)
        api._catalog_open_project=Mock(return_value={'project':project(),'review':{'notes':[{'id':'a','finger':4}]}})
        api._record_summary=Mock();api.request=Mock()
        with self.assertRaisesRegex(ValueError,'合并保存的校对'):
            api.export_score('independent')
        api.request.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
