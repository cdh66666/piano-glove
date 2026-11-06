"""Recovered small-note rhythm stays visibly reviewable until user edits it."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import check_project

class SmallBeamWarningTests(unittest.TestCase):
    def test_precisely_recovered_small_note_warns_without_inventing_a_blocker(self):
        p=dict(name='合成小音符',automatic_mode=True,selection=dict(bpm=120,start_beat=0),notes=[dict(
            id='a',hand='right',pitch='C4',finger=1,beat=0,duration_beats=.125,
            issues=['small_notated_note_requires_review'],
            rhythm_evidence=dict(beam_recovery=dict(method='shared_original_stem')))])
        state=check_project(p)
        self.assertTrue(state['automatic']['ready'])
        self.assertEqual(state['automatic']['timing_warning_notes'],1)
        self.assertIn('小音符用途请核对',state['notes'][0]['timing_warning'])
        p['notes'][0]['manual_fields']=['duration_beats']
        confirmed=check_project(p)
        self.assertEqual(confirmed['automatic']['timing_warning_notes'],0)

if __name__=='__main__':unittest.main()
