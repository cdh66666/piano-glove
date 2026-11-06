"""Synthetic bassa geometry: no customer score data or coordinates."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parent
HOST=ROOT.parents[2]/'repo/host'
sys.path.insert(0,str(HOST));sys.path.insert(0,str(ROOT/'candidate'))
from score_converter_engine import (_octave_regions,_octave_at,_octave_marker_staff,
                                    _text_octave_markers)


def geometry(label='8vb',scale=1,dx=0,dy=0):
    x=lambda n:n*scale+dx;y=lambda n:n*scale+dy
    staff=dict(id='upper',left=x(10),right=x(210),top=y(40),bottom=y(68),gap=7*scale,
               heads=[dict(x=x(63)),dict(x=x(96))])
    marker=dict(char='text:'+label,x=x(55),y=y(99),size=12*scale,
                bbox=[x(55),y(89),x(72),y(101)],octave_semitones=-12 if label=='8vb' else -24)
    line=(x(73),y(94),x(160),y(94),.6*scale)
    hook=(x(160),y(90),x(160),y(94),.6*scale)
    return staff,marker,[line,hook]


class LowerOctaveTests(unittest.TestCase):
    def test_explicit_bassa_bounded_solid_lines(self):
        for label,shift in [('8vb',-12),('15mb',-24)]:
            with self.subTest(label=label):
                s,m,lines=geometry(label);r=_octave_regions(s,[m],lines)
                self.assertEqual(r[0]['shift'],shift)
                self.assertEqual(r[0]['endpoint'],'cap')
                self.assertEqual(_octave_at(100,r,7)[0],shift)
                self.assertEqual(_octave_at(40,r,7)[0],0)
                self.assertEqual(_octave_at(190,r,7)[0],0)

    def test_mirrored_terminal_hook_not_wrong_way_hook(self):
        s,m,lines=geometry();lines[1]=(160,94,160,98,.6)
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_unknown_end_is_not_extended_to_all_following_notes(self):
        s,m,lines=geometry()
        self.assertIsNone(_octave_regions(s,[m],lines[:1])[0]['shift'])
        self.assertIsNone(_octave_at(180,_octave_regions(s,[m],lines[:1]),7)[0])

    def test_dashed_bassa_with_upward_hook(self):
        s,m,_=geometry()
        lines=[(x,94,x+5,94,.6) for x in range(73,135,10)]+[(139,90,139,94,.6)]
        r=_octave_regions(s,[m],lines)
        self.assertEqual(r[0]['shift'],-12)
        self.assertEqual(r[0]['dash_count'],7)
        self.assertEqual(_octave_at(150,r,7)[0],0)

    def test_dashed_wrong_way_hook_stays_unknown(self):
        s,m,_=geometry()
        lines=[(x,94,x+5,94,.6) for x in range(73,135,10)]+[(139,94,139,99,.6)]
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_dash_gap_does_not_jump_an_unprinted_region(self):
        s,m,_=geometry()
        lines=[(73,94,78,94,.6),(83,94,88,94,.6),(120,94,125,94,.6),(130,94,135,94,.6),(139,90,139,94,.6)]
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_continuation_to_system_edge_is_bounded(self):
        s,m,_=geometry();s['right']=138
        lines=[(x,94,x+5,94,.6) for x in range(73,135,10)]
        r=_octave_regions(s,[m],lines)
        self.assertEqual(r[0]['shift'],-12)
        self.assertEqual(r[0]['endpoint'],'system_edge')

    def test_label_on_wrong_side_or_inside_staff_not_interpreted(self):
        for y in (25,50,70):
            s,m,lines=geometry();m['y']=y
            self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_unknown_music_glyph_is_not_assigned_bassa_semantics(self):
        s,m,lines=geometry();m.pop('octave_semitones');m['char']='ƶ'
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_cid_verified_aloisen_bassa_glyph_uses_same_bounded_line_rules(self):
        s,m,lines=geometry();m.pop('octave_semitones');m['char']='Ƶ'
        self.assertEqual(_octave_regions(s,[m],lines)[0]['shift'],-12)
        self.assertIsNone(_octave_regions(s,[m],[])[0]['shift'])

    def test_mismatched_text_label_and_shift_remain_unknown(self):
        s,m,lines=geometry();m['char']='text:8va'
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_bassa_between_staves_belongs_to_upper_staff(self):
        s,m,_=geometry();lower=dict(s,id='lower',top=105,bottom=133)
        # It is geometrically closer to the lower centre; only the explicit
        # bassa and below-upper placement disambiguate ownership.
        self.assertLess(abs(m['y']-119),abs(m['y']-54))
        self.assertIs(_octave_marker_staff(m,[s,lower]),s)

    def test_bassa_below_lower_staff_belongs_to_lower_staff(self):
        s,m,_=geometry();lower=dict(s,id='lower',top=105,bottom=133);m['y']=155
        self.assertIs(_octave_marker_staff(m,[s,lower]),lower)

    def test_inside_neighbor_staff_is_not_stolen(self):
        s,m,_=geometry();lower=dict(s,id='lower',top=90,bottom=118)
        self.assertIsNone(_octave_marker_staff(m,[s,lower]))

    def test_outside_horizontal_or_far_below_does_not_attach(self):
        s,m,_=geometry()
        for x,y in [(400,99),(55,150)]:
            n=dict(m,x=x,y=y)
            self.assertIsNone(_octave_marker_staff(n,[s]))

    def test_equal_staff_evidence_remains_ambiguous(self):
        s,m,_=geometry();same=dict(s,id='ambiguous')
        self.assertIsNone(_octave_marker_staff(m,[s,same]))

    def test_legacy_upper_ownership_is_unchanged(self):
        s,m,_=geometry();lower=dict(s,id='lower',top=105,bottom=133)
        m=dict(m,char='text:8va',octave_semitones=12,y=99)
        self.assertIs(_octave_marker_staff(m,[s,lower]),lower)

    def test_scaled_and_translated_bassa_geometry(self):
        for scale,dx,dy in [(1,0,0),(1.8,37,90),(.75,-16,41),(3,500,-100)]:
            s,m,lines=geometry('15mb',scale,dx,dy)
            r=_octave_regions(s,[m],lines)
            self.assertEqual(_octave_at(100*scale+dx,r,s['gap'])[0],-24)
            self.assertEqual(_octave_at(190*scale+dx,r,s['gap'])[0],0)

    def test_single_last_note_retains_existing_explicit_text_rule(self):
        s,m,_=geometry();s['heads']=[dict(x=63)]
        self.assertEqual(_octave_regions(s,[m],[])[0]['shift'],-12)
        s['heads'].append(dict(x=95))
        self.assertIsNone(_octave_regions(s,[m],[])[0]['shift'])

    def test_functions_do_not_mutate_source_geometry(self):
        s,m,lines=geometry();saved=deepcopy((s,m,lines))
        _octave_regions(s,[m],lines);_octave_marker_staff(m,[s])
        self.assertEqual((s,m,lines),saved)

    def test_text_parser_preserves_explicit_shift_and_ignores_ordinary_digits(self):
        def text(chars,y):
            return [dict(char=c,x=20+i*5,y=y,size=12,font='Times',bbox=[20+i*5,y-10,24+i*5,y+1]) for i,c in enumerate(chars)]
        class Page:
            def chars(self,music_only=False):return text('8vb',95)+text('15mb',130)+text('8',160)+text('15',190)
        markers=_text_octave_markers(Page())
        self.assertEqual([(m['char'],m['octave_semitones']) for m in markers],[('text:8vb',-12),('text:15mb',-24)])

if __name__=='__main__':unittest.main()
