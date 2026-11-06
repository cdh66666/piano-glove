"""Recognized unmeasured ornaments remain optional only while genuinely unmarked."""
from copy import deepcopy
import unittest
from score_automatic import prepare_automatic_project

class OrnamentReadinessContractTests(unittest.TestCase):
    def test_all_unmeasured_kinds_share_unmarked_and_manual_finger_policy(self):
        for kind in ('slashed','unmeasured_prefix','unmeasured'):
            with self.subTest(kind=kind):
                p=dict(name='independent ornament',notes=[dict(id='o',hand='right',pitch='C4',finger=None,
                    source_fingering_state='unmarked',beat=0,duration_beats=None,grace_kind=kind,issues=[])],
                    selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
                before=deepcopy(p)
                ready=prepare_automatic_project(p)
                self.assertTrue(ready['notes'][0]['automatic_ready'])
                self.assertEqual(p['notes'][0]['duration_beats'],None)
                manual=deepcopy(before);manual['notes'][0].update(finger=2,finger_source='manual',manual_fields=['finger'])
                checked=prepare_automatic_project(manual)
                self.assertFalse(checked['notes'][0]['automatic_ready'])
                self.assertIn('选择音值',checked['notes'][0]['automatic_reasons'])

if __name__=='__main__':unittest.main()
