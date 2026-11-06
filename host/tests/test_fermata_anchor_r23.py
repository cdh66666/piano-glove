"""Independent RH-clock/LH-symbol controls, not customer score constants."""
from pathlib import Path
from copy import deepcopy
import json,sys,unittest
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
from score_realization import realize_project
from test_score_realization_r23 import note,mark,project

class FermataAnchorTests(unittest.TestCase):
    def shared(self,rest=False):
        a=note('a',measure_beat=0,measure_start_beat=0)
        b=note('b','D4',2,1,2,measure_beat=2,measure_start_beat=0)
        lh=dict(id='left',hand='left',page=1,system=1,measure=1,beat=None,measure_beat=None,duration=1,
            performance_marks=[mark('fermata','shared')])
        if rest:
            rh=dict(id='rh-rest',hand='right',page=1,system=1,measure=1,beat=1,measure_beat=1,duration=1,
                performance_marks=[mark('fermata','shared')])
            return project([a,b],rests=[rh,lh])
        a['duration_beats']=2;a['performance_marks']=[mark('fermata','shared')];lh['duration']=2
        return project([a,b,lh])

    def test_known_rh_note_anchors_duplicate_unknown_lh_without_double_hold(self):
        p=self.shared();before=deepcopy(p);r=realize_project(p)
        self.assertFalse(r['errors']);self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,1500])
        self.assertEqual(r['audio_events'][0]['duration_ms'],1500);self.assertEqual(p,before)

    def test_known_rh_rest_anchors_duplicate_lh_and_extends_only_silence(self):
        p=self.shared(rest=True);before=deepcopy(p);r=realize_project(p)
        self.assertFalse(r['errors']);self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,1250])
        self.assertEqual(r['audio_events'][0]['duration_ms'],500);self.assertEqual(p,before)

    def test_unmatched_lh_group_is_not_given_an_arbitrary_rh_time(self):
        p=self.shared();p['notes'][2]['performance_marks'][0]['group_id']='other'
        r=realize_project(p);self.assertTrue(r['errors'])
        self.assertTrue(any('时间锚' in e['message'] for e in r['errors']))

    def test_two_inconsistent_known_rh_endpoints_remain_a_real_ambiguity(self):
        p=self.shared();p['notes'][1]['performance_marks']=[mark('fermata','shared')]
        r=realize_project(p);self.assertTrue(r['errors'])

    def test_written_override_disables_duplicate_lh_effect_too(self):
        p=self.shared();p['notes'][0]['performance_override']={'mode':'written'}
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,1000])

if __name__=='__main__':unittest.main()
