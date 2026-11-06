from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_converter_engine import _stem_and_duration,_recover_secondary_beam_voice_ownership
def fixture():
    hs=[dict(char='Ŵ',font='Aloisen',x=100.,y=float(y),size=10.,bbox=[100.,y-2,106.,y+2]) for y in (100,110)]
    s=dict(gap=5.,heads=hs);lines=[(100.2,100,100.2,140,.5),(100.2,110,100.2,142,.5),
        (20,143.2,140,138.4,2.),(100,136.5,120,135.7,2.),(100,133,120,132.2,2.),
        (40,139,100.5,142.025,2.),(95,138.25,100.5,138.525,2.)]
    r={id(h):_stem_and_duration(h,s,lines,hs) for h in hs};return s,hs,lines,r
class SecondaryVoiceBeamsTests(unittest.TestCase):
    def test_short_hook_uses_uniquely_more_parallel_independent_parent(self):
        s,hs,l,r=fixture();self.assertIsNone(r[id(hs[0])][0]);self.assertEqual(r[id(hs[1])][0],.25);before=deepcopy(r[id(hs[1])])
        self.assertEqual(_recover_secondary_beam_voice_ownership([s],r,l,hs),1);self.assertEqual(r[id(hs[0])][0],.125);self.assertEqual(r[id(hs[1])],before)
    def test_no_original_known_other_voice_no_recovery(self):
        s,hs,l,r=fixture();r[id(hs[1])]=(None,{'head':'filled'},['stem_not_resolved']);self.assertEqual(_recover_secondary_beam_voice_ownership([s],r,l,hs),0)
    def test_wrong_other_nominal_count_not_used_as_anchor(self):
        s,hs,l,r=fixture();r[id(hs[1])]=(.5,r[id(hs[1])][1],[]);self.assertEqual(_recover_secondary_beam_voice_ownership([s],r,l,hs),0)
    def test_missing_other_physical_shaft_no_recovery(self):
        s,hs,l,r=fixture();self.assertEqual(_recover_secondary_beam_voice_ownership([s],r,[x for x in l if x!=l[1]],hs),0)
    def test_small_cue_not_recovered_as_regular_note(self):
        s,hs,l,r=fixture();hs[0]['size']=6.;self.assertEqual(_recover_secondary_beam_voice_ownership([s],r,l,hs),0)
    def test_no_mutation_of_original_heads_or_lines(self):
        s,hs,l,r=fixture();before=deepcopy((hs,l));_recover_secondary_beam_voice_ownership([s],r,l,hs);self.assertEqual((hs,l),before)
    def test_hook_equally_parallel_to_two_parent_families_is_not_reassigned(self):
        s,hs,l,r=fixture();l[-1]=(95,138.25,100.5,138.2775,2.);self.assertEqual(_recover_secondary_beam_voice_ownership([s],r,l,hs),0)
if __name__=='__main__':unittest.main()
