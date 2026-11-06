"""An unfingered, unmeasured grace stays editable without a phantom action."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import check_project,export_automatic,prepare_automatic_project

def score():
    return dict(name='独立合成装饰音',notes=[
        dict(id='grace',hand='right',pitch='D4',finger=None,source_fingering_state='unmarked',
             grace_kind='slashed',beat=0,duration_beats=None,confirmed=False),
        dict(id='principal',hand='right',pitch='E4',finger=2,source_fingering_state='printed',
             beat=0,duration_beats=1,confirmed=False)],
        selection=dict(bpm=120,start_beat=0,repeat_mode='written'),written_duration_beats=1)

class UnfingeredGraceTests(unittest.TestCase):
    def test_unfingered_unmeasured_grace_can_be_skipped_without_losing_main_note(self):
        p=score();before=deepcopy(p);prepare_automatic_project(p)
        self.assertTrue(p['automatic']['ready'])
        self.assertTrue(p['notes'][0]['unfingered'])
        self.assertIsNone(p['notes'][0]['duration_beats'])
        exported=export_automatic(p)
        self.assertEqual([(n['pitch'],n['finger'],n['t_ms']) for n in exported['notes']],[(64,2,0)])
        self.assertEqual(exported['duration_ms'],500)
        self.assertIsNone(before['notes'][0]['finger'])

    def test_setting_finger_requires_actual_duration_to_make_grace_action(self):
        p=score();p['notes'][0].update(finger=1,finger_source='manual')
        result=check_project(p)
        self.assertFalse(result['automatic']['ready'])
        self.assertIn('选择音值',result['notes'][0]['automatic_reasons'])
        with self.assertRaisesRegex(ValueError,'选择音值'):export_automatic(p)

    def test_ordinary_unfingered_unknown_duration_stays_pending(self):
        p=score();p['notes'][0].pop('grace_kind')
        result=check_project(p)
        self.assertFalse(result['automatic']['ready'])
        self.assertIn('选择音值',result['notes'][0]['automatic_reasons'])

if __name__=='__main__':unittest.main()
