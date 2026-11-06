from pathlib import Path
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_converter_engine import _other_voice_owns_flag,_explicit_flag_shaft_tip
def fixture():
    head=lambda y:dict(char='Ŵ',font='Aloisen',x=100.,y=float(y),size=10.,bbox=[100.,y-2,106.,y+2])
    target=head(100);owner=head(105);endpoint_other=head(130)
    flag=dict(char='ř',font='Aloisen',x=100.,y=105.,size=10.,bbox=[100.,107.,106.,130.])
    lines=[(100.2,105,100.2,130,.5)];own=(105.5,70.,100.)
    return target,owner,endpoint_other,flag,lines,own
class ExplicitFlagTipTests(unittest.TestCase):
    def test_other_voice_head_on_flag_tip_does_not_hide_explicit_ownership(self):
        t,o,e,f,l,s=fixture();self.assertTrue(_other_voice_owns_flag(f,s,t,[t,o,e],l,5.))
    def test_missing_actual_head_origin_still_not_owned(self):
        t,o,e,f,l,s=fixture();self.assertFalse(_other_voice_owns_flag(f,s,t,[t,e],l,5.))
    def test_missing_actual_shaft_still_not_owned(self):
        t,o,e,f,l,s=fixture();self.assertFalse(_other_voice_owns_flag(f,s,t,[t,o,e],[],5.))
    def test_head_centre_path_not_engraved_attachment_edge(self):
        t,o,e,f,l,s=fixture();self.assertIsNone(_explicit_flag_shaft_tip(f,(103,105,130),o,.5,5.))
    def test_shaft_far_endpoint_outside_flag_glyph_not_owned(self):
        t,o,e,f,l,s=fixture();self.assertIsNone(_explicit_flag_shaft_tip(f,(100.2,105,150),o,.5,5.))
    def test_flag_ink_straddling_head_not_a_directional_proof(self):
        t,o,e,f,l,s=fixture();f['bbox']=[100,100,106,130];self.assertIsNone(_explicit_flag_shaft_tip(f,(100.2,105,130),o,.5,5.))
if __name__=='__main__':unittest.main()
