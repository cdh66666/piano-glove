from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_converter_engine import _stem_and_duration,_recover_explicit_short_quarters
def fixture(length=2.5):
    h=dict(char='Ŵ',font='Aloisen',x=100.,y=100.,size=10.,bbox=[100.,97.5,106.,102.5]);s=dict(gap=5.,heads=[h]);lines=[(100.3,100.2,100.3,100.2+length,.5)];chars=[h]
    return s,h,lines,chars
def apply(s,h,l,c,unknown=None):
    r={id(h):_stem_and_duration(h,s,l,c)}
    if unknown:r[id(h)]=(None,{'head':'filled'},['stem_not_resolved'])
    count=_recover_explicit_short_quarters([s],r,l,c);return count,r[id(h)]
class ShortQuarterTests(unittest.TestCase):
    def test_normal_quarter_with_short_explicit_edge_shaft(self):
        s,h,l,c=fixture();self.assertEqual(apply(s,h,l,c)[1][0],1.)
    def test_longer_short_stem_dotted_quarter(self):
        s,h,l,c=fixture(6.);c.append(dict(char='Ǉ',font='Aloisen',x=108.,y=100.,size=10.,bbox=[108,99,109,101]));self.assertEqual(apply(s,h,l,c)[1][0],1.5)
    def test_upward_attachment_is_right_head_edge(self):
        s,h,l,c=fixture();l=[(105.7,97.3,105.7,99.8,.5)];self.assertEqual(apply(s,h,l,c)[1][0],1.)
    def test_tiny_path_shorter_than_three_stroke_widths_is_not_shaft(self):
        s,h,l,c=fixture(1.);self.assertIsNone(apply(s,h,l,c)[1][0])
    def test_path_inside_middle_of_head_not_attachment_edge(self):
        s,h,l,c=fixture();l=[(103,100.2,103,102.7,.5)];self.assertIsNone(apply(s,h,l,c)[1][0])
    def test_no_actual_stem_not_inferred_quarter(self):
        s,h,l,c=fixture();self.assertIsNone(apply(s,h,[],c)[1][0])
    def test_small_cue_head_not_promoted(self):
        s,h,l,c=fixture();h['size']=6.;self.assertIsNone(apply(s,h,l,c,True)[1][0])
    def test_actual_flag_rejects_quarter(self):
        s,h,l,c=fixture();c.append(dict(char='ř',font='Aloisen',x=100.,y=100.,size=10.,bbox=[100,103,106,125]));self.assertIsNone(apply(s,h,l,c,True)[1][0])
    def test_actual_beam_rejects_quarter(self):
        s,h,l,c=fixture();l.append((100.3,102.7,135,102.7,2.));self.assertIsNone(apply(s,h,l,c,True)[1][0])
    def test_two_possible_shafts_not_forced(self):
        s,h,l,c=fixture();l.append((105.7,97.3,105.7,99.8,.5));self.assertIsNone(apply(s,h,l,c,True)[1][0])
    def test_shared_head_group_not_filled_by_single_note_rule(self):
        s,h,l,c=fixture(5.);other=dict(h,y=103.);c.append(other);self.assertIsNone(apply(s,h,l,c,True)[1][0])
    def test_known_value_preserved(self):
        s,h,l,c=fixture();r={id(h):(.25,{'head':'filled','manual':True},[])};before=deepcopy(r);_recover_explicit_short_quarters([s],r,l,c);self.assertEqual(r,before)
    def test_diagonal_grace_slash_never_promoted_to_quarter(self):
        s,h,l,c=fixture(6.);l.append((97.,105.,104.,100.,.5));self.assertIsNone(apply(s,h,l,c,True)[1][0])
if __name__=='__main__':unittest.main()
