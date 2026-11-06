from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_converter_engine import _protect_unowned_partial_chord_finger_evidence
def fixture(value=5):
    upper={'id':'upper','gap':5.};lower={'id':'lower','gap':5.}
    def note(nid,staff,y,stem):return dict(id=nid,page=1,system=1,measure=1,staff=staff,hand='left' if staff=='lower' else 'right',origin=[100.,float(y)],glyph_bbox=[100.,y-2.,106.,y+2.],
        rhythm_evidence={'stem':stem},finger=None,finger_source=None,finger_candidates=[],source_fingering_state='unmarked',source_fingering_evidence={'method':'no_unassigned_digit_in_column','candidate_bboxes':[]},issues=[])
    chord=[note('c'+str(i),'lower',y,[100.2,100.,140.]) for i,y in enumerate((100,110,120))]
    other=note('r','upper',80,[100.2,80.,97.]);other.update(finger=1,finger_source='printed',finger_bbox=[100,69,104,75],source_fingering_state='printed')
    digit=dict(char=chr(0x130+value),font='Aloisen',x=100.,y=95.,size=7.,bbox=[100.,91.,104.,97.])
    jobs=[(upper,[other],[[other]]),(lower,chord,[chord])]
    return jobs,[digit],chord,other
class PartialChordStateTests(unittest.TestCase):
    def test_visible_unowned_partial_digit_preserved_without_assigning_finger(self):
        jobs,digits,chord,other=fixture();self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),1)
        self.assertIsNone(chord[0]['finger']);self.assertEqual(chord[0]['source_fingering_state'],'unresolved');self.assertEqual(chord[0]['finger_candidates'],[5])
        self.assertEqual(chord[0]['source_fingering_evidence']['candidate_bboxes'],[[100.,91.,104.,97.]])
        self.assertTrue(all(n['source_fingering_state']=='unmarked' for n in chord[1:]))
    def test_any_valid_digit_uses_same_rule(self):
        jobs,digits,chord,_=fixture(3);self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),1);self.assertEqual(chord[0]['finger_candidates'],[3])
    def test_true_unmarked_no_digit_unchanged(self):
        jobs,digits,chord,_=fixture();before=deepcopy(chord);self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,[]),0);self.assertEqual(chord,before)
    def test_digit_owned_by_another_head_does_not_yellow_chord(self):
        jobs,digits,chord,other=fixture();other['finger_bbox']=digits[0]['bbox'];self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_without_other_staff_competition_no_new_state(self):
        jobs,digits,chord,_=fixture();self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs[1:],digits),0)
    def test_same_staff_music_does_not_trigger(self):
        jobs,digits,chord,other=fixture();other['staff']='lower';self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_other_staff_without_own_printed_finger_not_claimed_uncertain(self):
        jobs,digits,chord,other=fixture();other.update(finger=None,finger_source=None);self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_existing_printed_finger_unchanged(self):
        jobs,digits,chord,_=fixture();chord[0].update(finger=2,finger_source='printed',source_fingering_state='printed');before=deepcopy(chord[0]);_protect_unowned_partial_chord_finger_evidence(jobs,digits);self.assertEqual(chord[0],before)
    def test_manual_or_confirmed_value_unchanged(self):
        for field,value in [('manual_fields',['finger']),('confirmed',True)]:
            jobs,digits,chord,_=fixture();chord[0][field]=value;before=deepcopy(chord);self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0);self.assertEqual(chord,before)
    def test_tuplet_digit_not_fingering_candidate(self):
        jobs,digits,chord,other=fixture(3);other['rhythm_evidence']['tuplet']={'marker_bbox':digits[0]['bbox']};self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_distinct_shafts_not_a_common_chord(self):
        jobs,digits,chord,_=fixture();chord[1]['rhythm_evidence']['stem']=[105.,100.,140.];self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_distant_or_other_column_digit_does_not_trigger(self):
        for box,x in [([120.,91.,124.,97.],120.),([100.,60.,104.,66.],100.)]:
            jobs,digits,chord,_=fixture();digits[0].update(bbox=box,x=x);self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_excluded_target_unchanged(self):
        jobs,digits,chord,_=fixture();chord[0]['excluded']=True;self.assertEqual(_protect_unowned_partial_chord_finger_evidence(jobs,digits),0)
    def test_music_and_original_finger_fields_never_changed(self):
        jobs,digits,chord,other=fixture();before=deepcopy([dict(id=n['id'],finger=n['finger'],origin=n['origin'],rhythm=n['rhythm_evidence']) for n in chord+[other]])
        _protect_unowned_partial_chord_finger_evidence(jobs,digits);self.assertEqual(before,[dict(id=n['id'],finger=n['finger'],origin=n['origin'],rhythm=n['rhythm_evidence']) for n in chord+[other]])
if __name__=='__main__':unittest.main()
