"""Independent engraving constructions, unrelated to user PDF coordinates."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
ROOT=Path(__file__).resolve().parent;HOST=ROOT.parent
sys.path.insert(0,str(HOST))
from recognizer_geometry import subdivided_beam_tuplets


def fixture(count,centers,scale=1,dx=0,dy=0,numeral='3'):
    gap=10*scale;base_x=100*scale+dx;head_y=40*scale+dy;tip=80*scale+dy
    notes=[dict(id='n'+str(i),origin=[base_x+20*i*scale,head_y],hand='right',measure=1,
        duration=.5,beats=.5,confirmed=False,issues=[],finger=None,
        rhythm_evidence={'head':'filled','beams':1,'stem':[base_x+20*i*scale,head_y,tip],'stem_direction':'down'})
        for i in range(count)]
    line=(base_x,tip,base_x+20*(count-1)*scale,tip,4.5*scale)
    markers=[dict(char=numeral,font='Text',bbox=[base_x+(c-3)*scale,tip+8*scale,base_x+(c+3)*scale,tip+16*scale]) for c in centers]
    return notes,{'gap':gap},[line],markers


class PartialTupletPrefixTests(unittest.TestCase):
    def test_eight_stems_two_marked_triplets_keep_two_ordinary_tail_notes(self):
        for scale,dx,dy in [(1,0,0),(.5,73,-20),(3,-200,150)]:
            notes,staff,lines,markers=fixture(8,[20,80],scale,dx,dy)
            subdivided_beam_tuplets(notes,staff,lines,markers)
            self.assertEqual([n['duration'] for n in notes],[1/3]*6+[.5]*2)
            self.assertTrue(all('tuplet' not in n['rhythm_evidence'] for n in notes[-2:]))

    def test_five_stems_one_unique_triplet_keeps_two_ordinary_tail_notes(self):
        notes,staff,lines,markers=fixture(5,[20])
        subdivided_beam_tuplets(notes,staff,lines,markers)
        self.assertEqual([n['duration'] for n in notes],[1/3]*3+[.5]*2)

    def test_nine_stems_three_markers_keep_complete_tiling_behavior(self):
        notes,staff,lines,markers=fixture(9,[20,80,140])
        subdivided_beam_tuplets(notes,staff,lines,markers)
        self.assertEqual([n['duration'] for n in notes],[1/3]*9)

    def test_overlapping_windows_or_a_marker_with_two_possible_windows_are_ambiguous(self):
        for centers in ([20,40],[30,90],[20,20,80]):
            notes,staff,lines,markers=fixture(8,centers);before=deepcopy(notes)
            subdivided_beam_tuplets(notes,staff,lines,markers)
            self.assertEqual(notes,before,centers)

    def test_a_missing_marker_before_a_full_residual_group_stays_unresolved(self):
        for count,centers in [(6,[20]),(8,[20]),(9,[20,80])]:
            notes,staff,lines,markers=fixture(count,centers);before=deepcopy(notes)
            subdivided_beam_tuplets(notes,staff,lines,markers)
            self.assertEqual(notes,before,(count,centers))

    def test_single_finger_glyph_head_side_text_and_digit_run_are_not_tuplet_markers(self):
        for kind in ('music_finger','head_side_text','text_run'):
            notes,staff,lines,markers=fixture(5,[20])
            if kind=='music_finger':markers[0].update(char='ĳ',font='Aloisen')
            elif kind=='head_side_text':markers[0]['bbox']=[117,22,123,30]
            else:
                markers=[dict(char=c,font='Text',bbox=[117+4*i,88,120+4*i,96]) for i,c in enumerate('321321')]
            before=deepcopy(notes);subdivided_beam_tuplets(notes,staff,lines,markers)
            self.assertEqual(notes,before,kind)

    def test_note_spaced_finger_row_is_excluded_even_with_empty_or_mixed_font_names(self):
        for mixed in (False,True):
            for font_origin_shift in (0,-6):
                notes,staff,lines,_=fixture(4,[])
                chars=[]
                for index,value in enumerate((5,3,2,1)):
                    music=mixed and index!=1
                    chars.append(dict(char=chr(0x130+value) if music else str(value),font='Aloisen' if music else '',
                        x=100+20*index+font_origin_shift,bbox=[100+20*index,88,106+20*index,96]))
                before=deepcopy(notes);subdivided_beam_tuplets(notes,staff,lines,chars)
                self.assertEqual(notes,before,(mixed,font_origin_shift))

    def test_fingering_row_can_follow_a_sloped_beam(self):
        notes,staff,_,_=fixture(4,[])
        for index,n in enumerate(notes):n['rhythm_evidence']['stem'][2]+=6*index
        lines=[(100,80,160,98,4.5)]
        chars=[dict(char=str(value),font='',x=94+20*index,
                    bbox=[100+20*index,88+6*index,106+20*index,96+6*index])
               for index,value in enumerate((5,3,2,1))]
        before=deepcopy(notes);subdivided_beam_tuplets(notes,staff,lines,chars)
        self.assertEqual(notes,before)

    def test_a_partial_finger_row_is_already_ambiguous_with_one_companion_column(self):
        notes,staff,lines,markers=fixture(4,[20])
        markers.append(dict(char='5',font='OtherFont',x=94,bbox=[100,88,106,96]))
        before=deepcopy(notes);subdivided_beam_tuplets(notes,staff,lines,markers)
        self.assertEqual(notes,before)

    def test_explicit_user_duration_or_confirmation_is_preserved(self):
        for mode in ('duration','duration_beats','confirmed'):
            notes,staff,lines,markers=fixture(5,[20])
            if mode=='confirmed':notes[1]['confirmed']=True
            else:notes[1]['manual_fields']=[mode]
            notes[1]['finger']=4;notes[1]['finger_source']='manual'
            before=deepcopy(notes);subdivided_beam_tuplets(notes,staff,lines,markers)
            self.assertEqual(notes,before,mode)

    def test_unknown_or_already_tupleted_stem_cannot_be_skipped_to_forge_a_window(self):
        for mode in ('unknown','already_tupleted'):
            notes,staff,lines,markers=fixture(5,[20])
            if mode=='unknown':notes[1]['duration']=None
            else:notes[1]['rhythm_evidence']['tuplet']={'actual':3,'normal':2}
            before=deepcopy(notes);subdivided_beam_tuplets(notes,staff,lines,markers)
            self.assertEqual(notes,before,mode)

    def test_printed_count_is_generic_and_not_a_triplet_only_remainder_rule(self):
        notes,staff,lines,markers=fixture(7,[40],numeral='5')
        subdivided_beam_tuplets(notes,staff,lines,markers)
        self.assertEqual([n['duration'] for n in notes],[.4]*5+[.5]*2)

    def test_a_marked_middle_window_does_not_establish_a_prefix(self):
        notes,staff,lines,markers=fixture(5,[40]);before=deepcopy(notes)
        subdivided_beam_tuplets(notes,staff,lines,markers)
        self.assertEqual(notes,before)


if __name__=='__main__':unittest.main(verbosity=2)
