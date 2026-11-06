"""Independent source geometry controls, not positions copied from test PDFs."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_converter_engine import _stem_and_duration,_recover_explicit_physical_rhythms

def head(x=100,y=100,char='Ŵ',size=10):return dict(x=float(x),y=float(y),char=char,font='Aloisen',size=float(size),bbox=[float(x),y-2.,x+6.,y+2.])
def run(heads,lines,extra=(),unknown=None):
    staff=dict(gap=5.,heads=heads);chars=heads+list(extra)
    rhythms={id(h):_stem_and_duration(h,staff,lines,chars) for h in heads}
    if unknown:
        for i in unknown:rhythms[id(heads[i])]=(None,{'head':'filled'},['stem_not_resolved'])
    original=deepcopy(rhythms)
    count=_recover_explicit_physical_rhythms([staff],rhythms,lines,chars)
    return rhythms,count,original
def flag_other_fixture():
    hs=[head(),head(y=105)];lines=[(105.5,70,105.5,100,.5),(105.5,70,140,70,2.),(100.2,105,100.2,130,.5)]
    flag=dict(char='ř',font='Aloisen',x=100.,y=105.,size=10.,bbox=[100.,107.,106.,130.])
    return hs,lines,[flag]

class PhysicalRhythmTests(unittest.TestCase):
    def test_flag_owned_by_other_real_opposed_voice_not_a_blocker(self):
        hs,lines,flags=flag_other_fixture();r,count,before=run(hs,lines,flags)
        self.assertIsNone(before[id(hs[0])][0]);self.assertEqual(r[id(hs[0])][0],.5)
        self.assertEqual(len(r[id(hs[0])][1]['beam_recovery']['discarded_other_voice_flags']),1)
    def test_unowned_nearby_flag_remains_unknown(self):
        hs,lines,flags=flag_other_fixture();r,_,_=run(hs[:1],lines[:2],flags)
        self.assertIsNone(r[id(hs[0])][0])
    def test_other_notehead_without_physical_own_flag_shaft_is_not_enough(self):
        hs,lines,flags=flag_other_fixture();r,_,_=run(hs,lines[:2],flags)
        self.assertIsNone(r[id(hs[0])][0])
    def test_unmatched_flag_from_other_font_not_claimed(self):
        hs,lines,flags=flag_other_fixture();hs[1]['font']='Other';r,_,_=run(hs,lines,flags)
        self.assertIsNone(r[id(hs[0])][0])
    def test_double_beam_uses_actual_count(self):
        hs,lines,flags=flag_other_fixture();lines.append((105.5,73,140,73,2.));r,_,_=run(hs,lines,flags)
        self.assertEqual(r[id(hs[0])][0],.25)
    def test_known_rhythms_are_never_replaced(self):
        hs,lines,flags=flag_other_fixture();r,_,before=run(hs,lines,flags)
        for h in hs:
            if before[id(h)][0] is not None:self.assertEqual(r[id(h)],before[id(h)])
    def test_short_normal_stem_actual_beam_recovers(self):
        hs=[head()];lines=[(105.5,92.5,105.5,100,.5),(105.5,92.5,140,92.5,2.)];r,_,before=run(hs,lines)
        self.assertIsNone(before[id(hs[0])][0]);self.assertEqual(r[id(hs[0])][0],.5)
    def test_short_stem_without_beam_is_not_inferred_quarter(self):
        hs=[head()];r,_,_=run(hs,[(105.5,92.5,105.5,100,.5)])
        self.assertIsNone(r[id(hs[0])][0])
    def test_small_cue_not_recovered_as_normal_short_stem(self):
        hs=[head(size=6)];lines=[(105.5,92.5,105.5,100,.5),(105.5,92.5,140,92.5,2.)];r,_,_=run(hs,lines,unknown=[0])
        self.assertIsNone(r[id(hs[0])][0])
    def test_long_chord_shaft_actual_beam_recovers_interior(self):
        hs=[head(y=y) for y in (100,115,130)];lines=[(105.5,80,105.5,130,.5),(105.5,80,140,80,2.)];r,_,_=run(hs,lines)
        self.assertEqual([r[id(h)][0] for h in hs],[.5]*3)
    def test_long_chord_shaft_with_actual_flag_tip_recovers(self):
        hs=[head(y=y) for y in (100,120,140)];lines=[(105.5,70,105.5,140,.5)]
        flag=dict(char='ŉ',font='Aloisen',x=100.,y=90.,size=10.,bbox=[105.,70.,111.,90.]);r,_,_=run(hs,lines,[flag])
        self.assertEqual([r[id(h)][0] for h in hs],[.5]*3)
    def test_long_unflagged_unbeamed_line_still_not_a_quarter(self):
        hs=[head(y=y) for y in (100,120,140)];r,_,_=run(hs,[(105.5,70,105.5,140,.5)])
        self.assertTrue(all(r[id(h)][0] is None for h in hs))
    def test_open_head_chooses_independent_half_voice_not_shared_other_beam(self):
        hs=[head(char='ż')];lines=[(105.5,80,105.5,99.5,.5),(100.2,100.3,100.2,120,.5),(100.2,120,140,120,2.)]
        r,_,_=run(hs,lines);self.assertEqual(r[id(hs[0])][0],2.);self.assertEqual(r[id(hs[0])][1]['stem_direction'],'up')
    def test_only_open_beamed_head_is_not_arbitrarily_made_half_note(self):
        hs=[head(char='ż')];lines=[(100.2,100.3,100.2,120,.5),(100.2,120,140,120,2.)];r,_,_=run(hs,lines)
        self.assertIsNone(r[id(hs[0])][0])
    def test_open_tremolo_endpoints_not_misread_as_ordinary_beamed_halves(self):
        hs=[head(char='ż'),head(x=140,char='ż')];lines=[(105.5,75,105.5,100,.5),(145.5,75,145.5,100,.5),(105.5,75,145.5,75,2.),(105.5,78,145.5,78,2.)]
        r,_,_=run(hs,lines);self.assertTrue(all(r[id(h)][0] is None for h in hs))
    def test_ambiguous_two_valid_filled_voices_not_forced_to_one(self):
        hs=[head()];lines=[(105.5,75,105.5,99.5,.5),(105.5,75,140,75,2.),(105.5,78,140,78,2.),(100.2,100.3,100.2,120,.5),(100.2,120,140,120,2.)]
        r,_,_=run(hs,lines,unknown=[0]);self.assertIsNone(r[id(hs[0])][0])
    def test_actual_slash_keeps_grace_path(self):
        hs=[head()];lines=[(105.5,92.5,105.5,100,.5),(105.5,92.5,140,92.5,2.),(101,97,110,92,.5)]
        r,_,_=run(hs,lines);self.assertIsNone(r[id(hs[0])][0])
    def test_input_chars_geometry_not_mutated(self):
        hs,lines,flags=flag_other_fixture();before=deepcopy((hs,lines,flags));run(hs,lines,flags);self.assertEqual((hs,lines,flags),before)

def crossing_fixture():
    hs=[head(),head(x=84.5,y=155),head(x=104.5,y=155)]
    lines=[(100.2,100,100.2,125,.5),(70,120,100.5,125,2.),(90,126.75,110,123.75,2.),(90,126.75,90,155,.5),(110,123.75,110,155,.5)]
    return hs,lines
class CrossVoiceBeamTests(unittest.TestCase):
    def test_actual_two_opposed_endpoint_shafts_disambiguate_crossing(self):
        hs,lines=crossing_fixture();r,_,before=run(hs,lines)
        self.assertIsNone(before[id(hs[0])][0]);self.assertEqual(r[id(hs[0])][0],.5)
        self.assertEqual(len(r[id(hs[0])][1]['beam_recovery']['discarded_opposed_beams']),1)
    def test_one_unverified_crossing_endpoint_is_not_discarded(self):
        hs,lines=crossing_fixture();r,_,_=run(hs,lines[:-1]);self.assertIsNone(r[id(hs[0])][0])
    def test_crossing_without_endpoint_heads_not_discarded(self):
        hs,lines=crossing_fixture();r,_,_=run(hs[:1],lines);self.assertIsNone(r[id(hs[0])][0])
    def test_same_direction_endpoint_voices_not_discarded(self):
        hs,lines=crossing_fixture();hs[1]['y']=100;hs[1]['bbox']=[84.5,98,90.5,102];hs[2]['y']=100;hs[2]['bbox']=[104.5,98,110.5,102]
        lines[-2:]=[(90,100,90,126.75,.5),(110,100,110,123.75,.5)];r,_,_=run(hs,lines);self.assertIsNone(r[id(hs[0])][0])

if __name__=='__main__':unittest.main()
