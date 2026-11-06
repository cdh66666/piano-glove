from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_converter_engine import _disambiguate_foreign_free_stem_digits
def fixture():
    rh=dict(id='r',page=1,system=1,staff='upper',hand='right',origin=[100.,100.],rhythm_evidence=dict(stem=[100.2,100.,125.],stem_direction='down',beams=2),finger=None,finger_candidates=[1],source_fingering_state='unresolved',
            source_fingering_evidence=dict(method='digit_overlaps_attached_music_beam',candidate_bboxes=[[100.,120.,104.,125.]]))
    lh=dict(id='l',page=1,system=1,staff='lower',hand='left',origin=[100.,155.],rhythm_evidence=dict(stem=[105.5,129.,155.],stem_direction='up',beams=0),finger=3,finger_source='printed',finger_bbox=[100,150,104,154],source_fingering_state='printed')
    digits=[dict(char='ı',font='Aloisen',x=100.,y=123.,size=7.,bbox=[100.,120.,104.,125.])]
    lines=[(100.2,100,100.2,125,.5),(100,125,160,120,2.),(100,121.5,105,121.1,2.),(105.5,129,105.5,155,.5)]
    jobs=[({'gap':5.},[rh],[[rh]]),({'gap':5.},[lh],[[lh]])];return jobs,digits,lines,rh,lh
class ForeignStemTests(unittest.TestCase):
    def test_true_other_staff_free_tip_label_removes_wrong_beam_warning_only(self):
        j,c,l,r,h=fixture();before=deepcopy(h);self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l),1)
        self.assertIsNone(r['finger']);self.assertEqual(r['source_fingering_state'],'unmarked');self.assertEqual(r['finger_candidates'],[]);self.assertEqual(h,before)
    def test_no_actual_other_shaft_keeps_warning(self):
        j,c,l,r,h=fixture();self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l[:-1]),0);self.assertEqual(r['source_fingering_state'],'unresolved')
    def test_other_staff_not_exact_free_tip_keeps_warning(self):
        j,c,l,r,h=fixture();h['rhythm_evidence']['stem'][0]=115.;self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l),0)
    def test_other_music_inside_same_staff_not_proof(self):
        j,c,l,r,h=fixture();h['staff']='upper';self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l),0)
    def test_without_actual_main_beam_and_hook_no_declassification(self):
        j,c,l,r,h=fixture();self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,[l[0],l[-1]]),0)
    def test_multiple_other_free_stem_columns_remain_unknown(self):
        j,c,l,r,h=fixture();other=deepcopy(h);other.update(id='l2',staff='third');other['rhythm_evidence']['stem']=[105.5,130.,155.];j.append(({'gap':5},[other],[[other]]));l.append((105.5,130,105.5,155,.5));self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l),0)
    def test_printed_or_manual_value_not_changed(self):
        for field,value in [('finger',2),('manual_fields',['finger']),('confirmed',True)]:
            j,c,l,r,h=fixture();r[field]=value;before=deepcopy(r);_disambiguate_foreign_free_stem_digits(j,c,l);self.assertEqual(r,before)
    def test_plain_unresolved_not_an_overlap_warning_unchanged(self):
        j,c,l,r,h=fixture();r['source_fingering_evidence']['method']='unassigned_visible_digit';self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l),0)
    def test_only_proved_candidates_removed(self):
        j,c,l,r,h=fixture();r['source_fingering_evidence']['candidate_bboxes'].append([101,90,104,95]);self.assertEqual(_disambiguate_foreign_free_stem_digits(j,c,l),1);self.assertEqual(r['source_fingering_state'],'unresolved');self.assertEqual(r['source_fingering_evidence']['candidate_bboxes'],[[101,90,104,95]])
if __name__=='__main__':unittest.main()
