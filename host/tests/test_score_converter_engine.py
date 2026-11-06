"""Synthetic coordinate cases for fixes, independent of filenames/answer keys."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _staves, _stem_and_duration, _rest_duration, _event_groups, _repeat_marks, _annotate_ties, _resolve_pickup, _meter_signature, _meter_changes, _octave_regions, _octave_at, _trim_opening_repeat_prefix, _resolve_explicit_voices, _ordinary_metric_extent, _head_staff, _nearest_staff, _stem_beams, _shared_staff_hands
from score_converter import recognize_pdf, export_reviewed
from score_converter_engine import _resolve_two_note_tremolo, _printed_finger_candidates, _align_shared_staff_onsets, _propagate_beamed_onsets
from score_converter_engine import _apply_printed_tuplets, _initial_printed_tempo, _has_grace_slash
from score_converter_engine import _apply_printed_hand_labels
from score_converter_engine import _assign_printed_finger_group, _assign_page_fingerings
from score_converter_engine import _recover_grace_principal_timing
from score_converter_engine import _apply_bracketed_tuplets
SAMPLES=Path(__file__).resolve().parents[4]/'piano-score-trainer'/'samples'

class GeometryTests(unittest.TestCase):
    def test_uneven_interstaff_digits_do_not_form_a_complete_chord_stack(self):
        group=[dict(origin=[100,y],hand='left',rhythm_evidence={'stem':[100,60,88],'stem_direction':'down'})
               for y in (60,67.5,72.5)]
        upper_head=dict(x=100,y=32.5)
        staff=dict(gap=5,heads=[]);upper=dict(gap=5,heads=[upper_head])
        chars=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2])
               for c,y in [('Ĳ',40),('ı',44.25),('ĳ',51.75)]]
        rhythms={id(upper_head):(.5,{'stem':[106,7.5,32.5]},[])}
        candidates=_printed_finger_candidates(group,[group],staff,[staff,upper],chars,set(),rhythms)
        self.assertNotIn(0,{i for i,_ in candidates})
    def test_complete_below_chord_stack_uses_stem_not_distant_heads(self):
        # Development source: a high down-stem dyad has 5/3 below its beam.
        group=[dict(id=str(i),origin=[100,y],hand='right',finger=None,issues=[],
                    rhythm_evidence={'stem':[100,0,40],'stem_direction':'down','beams':2})
               for i,y in enumerate((0,5))]
        other_head=dict(x=100,y=80)
        staff=dict(gap=5,heads=[]);other=dict(gap=5,heads=[other_head])
        chars=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2])
               for c,y in [('ĵ',45),('ĳ',52.5)]]
        rhythms={id(other_head):(.5,{'stem':[100,80,103]},[])}
        candidates=_printed_finger_candidates(group,[group],staff,[staff,other],chars,set(),rhythms)
        _assign_printed_finger_group(group,candidates,5,set())
        self.assertEqual([n['finger'] for n in group],[5,3])
    def test_complete_above_downstem_chord_anchors_at_heads(self):
        group=[dict(origin=[100,y],hand='left',rhythm_evidence={'stem':[100,60,90],'stem_direction':'down'})
               for y in (60,67.5,72.5)]
        other_head=dict(x=100,y=7.5)
        staff=dict(gap=5,heads=[]);other=dict(gap=5,heads=[other_head])
        chars=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2])
               for c,y in [('ı',37.5),('ĳ',45),('ĵ',52.5)]]
        rhythms={id(other_head):(.5,{'stem':[100,7.5,27]},[])}
        candidates=_printed_finger_candidates(group,[group],staff,[staff,other],chars,set(),rhythms)
        self.assertEqual({i for i,_ in candidates},{0,1,2})
        # The same complete column cannot jump to this chord if the other
        # staff's actual music envelope reaches its nearest digit.
        rhythms[id(other_head)]=(.5,{'stem':[100,7.5,52.5]},[])
        self.assertEqual(_printed_finger_candidates(group,[group],staff,[staff,other],chars,set(),rhythms),[])
    def test_complete_whole_chord_reserves_column_before_other_staff(self):
        group=[dict(id=str(i),origin=[100,y],hand='left',finger=None,issues=[],rhythm_evidence={'head':'whole'})
               for i,y in enumerate((60,67.5,77.5))]
        previous_head=dict(x=100,y=7.5)
        previous_note=dict(id='other',origin=[100,7.5],hand='right',finger=None,issues=[],
                           rhythm_evidence={'stem':[100,7.5,24]})
        staff=dict(gap=5,heads=[]);previous=dict(gap=5,heads=[previous_head])
        chars=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2])
               for c,y in [('ı',37.5),('Ĳ',45),('ĵ',52.5)]]
        rhythms={id(previous_head):(.5,previous_note['rhythm_evidence'],[])}
        _assign_page_fingerings([(previous,[previous_note],[[previous_note]]),(staff,group,[group])],
                               [staff,previous],chars,rhythms)
        self.assertEqual([n['finger'] for n in group],[1,2,5])
        self.assertIsNone(previous_note['finger'])
    def test_bracketed_mixed_triplet_preserves_outside_note_and_shared_tail(self):
        notes=[]
        for i,x,duration,direction in [(0,80,.25,'down'),(1,100,.0625,'down'),(2,120,.1875,'down'),
                                        (3,140,.125,'up'),(4,160,.125,'down')]:
            notes.append(dict(id=str(i),origin=[x,30 if direction=='down' else 10],measure=1,
                pitch_candidate='C5',duration=duration,rhythm_evidence={'stem_direction':direction,'beams':3,
                    'stem':[x,30,60] if direction=='down' else [x,0,10]},issues=[]))
        rest=dict(id='r',origin=[98,0],bbox=[98,-3,103,3],duration=.125,rhythm_evidence={})
        marker=dict(char='3',font='Text',bbox=[125,70,135,79])
        lines=[(100,75,122,75,.5),(138,75,165,75,.5),(100,75,100,72,.5),(165,75,165,72,.5)]
        _apply_bracketed_tuplets(notes,[rest],{'gap':5},lines,[marker])
        self.assertEqual(notes[0]['duration'],.25)
        self.assertEqual([n['duration'] for n in notes[1:]],[1/24,.125,1/12,1/12])
        self.assertEqual(rest['duration'],1/12)
    def test_unmeasured_prefix_keeps_main_rhythm_and_unknown_grace_duration(self):
        staves=[dict(id=s,gap=5,measures=[dict(measure=1,meter_beats=4,timing_resolved=complete)])
                for s,complete in [('rh',False),('lh',True)]]
        notes=[dict(id='g'+str(i),staff='rh',measure=1,pitch_candidate='D5',origin=[x,30],duration=.25,beats=.25,
                    measure_beat=None,rhythm_evidence={'stem':[x,10,30],'beams':2},issues=['small_notated_note_requires_review'])
               for i,x in enumerate((100,106))]
        notes += [dict(id='m'+str(i),staff='rh',measure=1,pitch_candidate='C5',origin=[x,30],duration=1,measure_beat=None,
                       rhythm_evidence={},issues=['measure_timing_unresolved']) for i,x in enumerate((116,136,156,176))]
        notes += [dict(id='l'+str(i),staff='lh',measure=1,pitch_candidate='C3',origin=[x,80],duration=1,
                       measure_beat=i,rhythm_evidence={},issues=[]) for i,x in enumerate((116,136,156,176))]
        _recover_grace_principal_timing(staves,notes,[(100,10,106,10,2.25)])
        self.assertEqual([n['measure_beat'] for n in notes[2:6]],[0,1,2,3])
        self.assertEqual([n['duration'] for n in notes[:2]],[None,None])
        self.assertEqual(notes[0]['main_anchor_id'],'m0')
        self.assertEqual(notes[0]['grace_nominal_duration_beats'],.25)
    def test_partial_chord_keeps_only_unambiguous_printed_upper_digit(self):
        group=[dict(id=str(i),origin=[100,y],hand='right',finger=None,issues=[]) for i,y in enumerate((30,42.5))]
        digit=dict(char='ĵ',x=100,y=22.5,bbox=[100,19,104,24])
        _assign_printed_finger_group(group,[(0,digit)],5,set())
        self.assertEqual([n['finger'] for n in group],[5,None])
        self.assertTrue(group[0]['finger_evidence']['partial_chord'])
        self.assertIn('fingering_missing_or_ambiguous',group[1]['issues'])
    def test_partial_chord_equal_distance_digit_stays_unassigned(self):
        group=[dict(id=str(i),origin=[100,y],hand='right',finger=None,issues=[]) for i,y in enumerate((30,40))]
        digit=dict(char='ĳ',x=100,y=35,bbox=[100,32,104,37])
        _assign_printed_finger_group(group,[(0,digit)],5,set())
        self.assertEqual([n['finger'] for n in group],[None,None])
    def test_upstem_left_hand_chord_uses_its_complete_above_stack(self):
        group=[dict(origin=[100,y],hand='left',rhythm_evidence={'stem':[106,0,25],'stem_direction':'up'})
               for y in (20,25)]
        staff=dict(gap=5,heads=[])
        chars=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2])
               for c,y in [('ĵ',-10),('ĳ',-2.5),('ĵ',32.5)]]
        candidates=_printed_finger_candidates(group,[group],staff,[staff],chars,set(),{})
        self.assertEqual({i for i,_ in candidates},{0,1})
    def test_explicit_left_hand_label_changes_only_its_chord(self):
        notes=[dict(id=str(i),origin=[x,y],measure=1,hand='right',rhythm_evidence={'stem_direction':direction})
               for i,x,y,direction in [(1,100,30,'up'),(2,100,35,'up'),(3,100,55,'down'),(4,130,30,'up')]]
        chars=[dict(char=c,x=94+i*3,y=20,size=6,font='Text',bbox=[94+i*3,15,97+i*3,21]) for i,c in enumerate('L.H.')]
        _apply_printed_hand_labels(notes,{'gap':5},chars)
        self.assertEqual([n['hand'] for n in notes],['left','left','right','right'])
    def test_small_size_does_not_establish_grace_without_slash(self):
        rhythm={'stem':[100,10,30]}
        self.assertFalse(_has_grace_slash(rhythm,[(100,10,120,10,2.25)],5))
        self.assertTrue(_has_grace_slash(rhythm,[(97,17,104,12,.5)],5))
    def test_explicit_metronome_note_preserves_quarter_tempo(self):
        chars=[dict(char='=',x=40,y=20,size=10,bbox=[40,12,46,21],font='Text'),
               dict(char='6',x=50,y=20,size=10,bbox=[50,12,56,21],font='Text'),
               dict(char='2',x=56,y=20,size=10,bbox=[56,12,62,21],font='Text'),
               dict(char='Ŵ',x=72,y=22,size=10,bbox=[72,19,78,25],font='Aloisen')]
        staff=dict(top=40,bottom=60,gap=5,left=0,right=300)
        result=_initial_printed_tempo(chars,[staff],[(78,2,78,22,.5)])
        self.assertEqual(result['quarter_bpm'],62)
        self.assertIsNone(_initial_printed_tempo(chars[:-1],[staff],[]))
    def test_triplet_requires_printed_number_and_three_actual_stems(self):
        notes=[dict(id=str(i),origin=[x,30],measure=1,duration=.25,beats=.25,
                    rhythm_evidence={'stem':[x,10,30],'stem_direction':'up'},issues=[])
               for i,x in enumerate((100,110,120))]
        marker=dict(char='3',font='Times',x=108,y=6,bbox=[108,2,112,6])
        _apply_printed_tuplets(notes,{'gap':5},[(100,10,120,10,2.25)],[marker])
        self.assertTrue(all(abs(n['duration']-1/6)<1e-9 for n in notes))
        self.assertEqual(notes[0]['rhythm_evidence']['tuplet']['actual'],3)
    def test_finger_or_unanchored_number_cannot_make_triplet(self):
        for count,font in ((2,'Times'),(3,'Aloisen')):
            notes=[dict(id=str(i),origin=[x,30],measure=1,duration=.25,beats=.25,
                        rhythm_evidence={'stem':[x,10,30],'stem_direction':'up'},issues=[])
                   for i,x in enumerate((100,110,120)[:count])]
            marker=dict(char='3',font=font,x=108,y=6,bbox=[108,2,112,6])
            _apply_printed_tuplets(notes,{'gap':5},[(100,10,120,10,2.25)],[marker])
            self.assertTrue(all(n['duration']==.25 for n in notes))
    def test_actual_beam_propagates_from_both_neighbor_anchors(self):
        staff=dict(id='rh',gap=5,measures=[dict(measure=1,meter_beats=4)])
        def note(i,x,beat):return dict(id=str(i),staff='rh',measure=1,pitch_candidate='C5',origin=[x,30],
            duration=.25,measure_beat=beat,rhythm_evidence={'stem':[x,10,30],'beams':2},issues=['measure_timing_unresolved'])
        notes=[note(1,100,1),note(2,110,None),note(3,120,1.5)]
        _propagate_beamed_onsets([staff],notes,[(100,10,120,10,2.25)])
        self.assertEqual([n['measure_beat'] for n in notes],[1,1.25,1.5])
        notes=[note(1,100,1),note(2,110,None),note(3,120,1.75)]
        _propagate_beamed_onsets([staff],notes,[(100,10,120,10,2.25)])
        self.assertIsNone(notes[1]['measure_beat'])
        notes=[note(1,100,None),note(2,110,None),note(3,120,1.5)]
        _propagate_beamed_onsets([staff],notes,[(100,10,120,10,2.25)])
        self.assertEqual([n['measure_beat'] for n in notes],[1,1.25,1.5])
    def test_unattached_beam_does_not_interpolate_note_spacing(self):
        staff=dict(id='rh',gap=5,measures=[dict(measure=1,meter_beats=4)])
        notes=[dict(id=str(i),staff='rh',measure=1,pitch_candidate='C5',origin=[x,30],duration=.25,
                    measure_beat=beat,rhythm_evidence={'stem':[x,10,30],'beams':2},issues=[])
               for i,x,beat in [(1,100,1),(2,120,None)]]
        _propagate_beamed_onsets([staff],notes,[(100,0,120,0,2.25)])
        self.assertIsNone(notes[1]['measure_beat'])
    def test_incomplete_voice_can_follow_complete_paired_column(self):
        staves=[dict(id=s,gap=5,bars=[0,100],measures=[dict(measure=1,timing_resolved=resolved)])
                for s,resolved in [('rh',False),('lh',True)]]
        notes=[dict(id=s,staff=s,measure=1,origin=[50,30],duration=.5,measure_beat=beat,
                    issues=['measure_timing_unresolved'] if beat is None else []) for s,beat in [('rh',None),('lh',2.5)]]
        _align_shared_staff_onsets(staves,notes)
        self.assertEqual(notes[0]['measure_beat'],2.5)
        self.assertEqual(notes[0]['onset_evidence']['anchor_ids'],['lh'])
        notes[0]['measure_beat']=None;staves[1]['bars']=[0,120]
        _align_shared_staff_onsets(staves,notes)
        self.assertIsNone(notes[0]['measure_beat'])
    def test_printed_finger_below_own_note_is_kept(self):
        note=dict(origin=[100,30],hand='right',rhythm_evidence={'stem':[106,10,30]})
        staff=dict(gap=5,heads=[])
        digit=dict(char='ĳ',x=100,y=40,size=6,bbox=[100,37,104,42])
        result=_printed_finger_candidates([note],[[note]],staff,[staff],[digit],set(),{})
        self.assertEqual(result,[(0,digit)])
    def test_fingering_above_long_bass_stem_not_borrowed_by_right_hand(self):
        note=dict(origin=[100,30],hand='right',rhythm_evidence={'stem':[100,30,47]})
        bass_head=dict(x=100,y=114)
        staff=dict(gap=5,heads=[]);bass=dict(gap=5,heads=[bass_head])
        digit=dict(char='ĵ',x=100,y=72,size=6,bbox=[100,69,104,74])
        rhythms={id(bass_head):(.5,{'stem':[106,77,114]},[])}
        self.assertEqual(_printed_finger_candidates([note],[[note]],staff,[staff,bass],[digit],set(),rhythms),[])
    def test_long_beam_finger_beats_a_nearer_head_on_previous_system(self):
        note=dict(origin=[100,100],hand='right',rhythm_evidence={'stem':[106,65,100],'stem_direction':'up','beams':2})
        other_head=dict(x=100,y=30)
        staff=dict(gap=5,heads=[]);previous=dict(gap=5,heads=[other_head])
        digit=dict(char='Ĳ',x=100,y=59.5,size=6,bbox=[100,56.5,104,61.5])
        rhythms={id(other_head):(.5,{'stem':[100,30,48]},[])}
        self.assertEqual(_printed_finger_candidates([note],[[note]],staff,[staff,previous],[digit],set(),rhythms),[(0,digit)])
        # The actual other stem/beam reaching the number still wins ownership.
        rhythms[id(other_head)]=(.5,{'stem':[100,30,59]},[])
        self.assertEqual(_printed_finger_candidates([note],[[note]],staff,[staff,previous],[digit],set(),rhythms),[])
    def test_complete_chord_finger_stack_anchors_at_its_free_stem_end(self):
        group=[dict(origin=[100,y],hand='right',rhythm_evidence={'stem':[106,60,90],'stem_direction':'up','beams':0})
               for y in (78,83,90)]
        previous_head=dict(x=100,y=12)
        staff=dict(gap=5,heads=[]);previous=dict(gap=5,heads=[previous_head])
        chars=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2])
               for c,y in [('Ĵ',39.5),('Ĳ',47),('ı',54.5)]]
        rhythms={id(previous_head):(.5,{'stem':[100,12,24]},[])}
        result=_printed_finger_candidates(group,[group],staff,[staff,previous],chars,set(),rhythms)
        self.assertEqual({i for i,_ in result},{0,1,2})
        # An incomplete column is not silently reconstructed into a chord.
        result=_printed_finger_candidates(group,[group],staff,[staff,previous],chars[:1]+chars[2:],set(),rhythms)
        self.assertEqual([c['char'] for _,c in result],['ı'])
    def test_tall_chord_fingering_measured_from_nearest_head(self):
        group=[dict(origin=[100,y],hand='right',rhythm_evidence={'stem':[100,30,70]}) for y in (30,37.5,42.5)]
        staff=dict(gap=5,heads=[])
        digits=[dict(char=c,x=100,y=y,size=6,bbox=[100,y-3,104,y+2]) for c,y in [('ĵ',-10),('Ĳ',-2.5),('ı',5)]]
        self.assertEqual(len(_printed_finger_candidates(group,[group],staff,[staff],digits,set(),{})),3)
    def test_neighbor_column_digit_is_not_consumed_early(self):
        group=[dict(origin=[100,30],hand='right',rhythm_evidence={})]
        neighbor=[dict(origin=[106,30],hand='right',rhythm_evidence={})]
        staff=dict(gap=5,heads=[])
        digit=dict(char='ĳ',x=106,y=20,size=6,bbox=[106,17,110,22])
        self.assertEqual(_printed_finger_candidates(group,[group,neighbor],staff,[staff],[digit],set(),{}),[])
    def test_two_whole_note_tremolo_has_one_common_span(self):
        notes=[dict(id=str(i),origin=[x,y],measure=1,duration=4,
                    rhythm_evidence={'head':'whole'},issues=['measure_timing_unresolved'])
               for i,(x,y) in enumerate(((100,30),(100,40),(140,35)))]
        strokes=[(110,y,130,y,2.25) for y in (30,33.5,37)]
        self.assertIsNotNone(_resolve_two_note_tremolo(notes,[],{'gap':5},4,strokes))
        self.assertEqual([n['measure_beat'] for n in notes],[0,0,0])
        self.assertEqual([n['tremolo_side'] for n in notes],[0,0,1])
        self.assertTrue(all(n['tremolo_step_beats']==.125 and n['tremolo_span_beats']==4 for n in notes))
    def test_arbitrary_horizontal_lines_do_not_make_tremolo(self):
        notes=[dict(id=str(i),origin=[x,30],measure=1,duration=4,
                    rhythm_evidence={'head':'whole'},issues=[]) for i,x in enumerate((100,140))]
        self.assertIsNone(_resolve_two_note_tremolo(notes,[],{'gap':5},4,[(110,30,130,30,.5),(110,33,130,33,.5)]))
    def test_long_cross_staff_stem_requires_attached_beam(self):
        head={'char':'Ŵ','x':100,'y':80}
        stem=(106,10,106,80,.5)
        self.assertIsNone(_stem_and_duration(head,{'gap':5},[stem],[])[0])
        beams=[(80,10,120,10,2.5),(80,13.5,120,13.5,2.5)]
        duration,evidence,issues=_stem_and_duration(head,{'gap':5},[stem]+beams,[])
        self.assertEqual(duration,.25)
        self.assertEqual(evidence['stem_direction'],'up')
        self.assertEqual(issues,[])
    def test_shared_staff_requires_opposed_columns_and_vacant_other_staff(self):
        events=[]
        for x in (100,120):
            for y,direction in ((20,'up'),(40,'down')):
                events.append(dict(origin=[x,y],measure=1,hand=None,
                    rhythm_evidence={'stem_direction':direction},issues=['cross_staff_hand_unresolved']))
        self.assertFalse(_shared_staff_hands(events,5,[{'x':100},{'x':120}]))
        self.assertTrue(all(e['hand'] is None for e in events))
        self.assertTrue(_shared_staff_hands(events,5))
        self.assertEqual([e['hand'] for e in events],['right','left','right','left'])
    def test_alternating_single_voice_does_not_establish_two_hands(self):
        events=[dict(origin=[x,y],measure=1,hand=None,rhythm_evidence={'stem_direction':direction},issues=[])
                for x,y,direction in ((100,20,'up'),(120,40,'down'))]
        self.assertFalse(_shared_staff_hands(events,5))
    def test_short_secondary_beam_hook_counts_as_sixteenth(self):
        # Primary beam and a 0.9-space secondary hook on the same down stem.
        count,_,issues=_stem_beams((100,20,40),20,5,
            [(60,40,100,40,2.5),(95.5,36.5,100,36.5,2.5)])
        self.assertEqual(count,2)
        self.assertEqual(issues,[])
    def test_short_thin_tenuto_is_not_a_secondary_beam(self):
        count,_,issues=_stem_beams((100,20,40),20,5,
            [(60,40,100,40,2.5),(95.5,36.5,100,36.5,.5)])
        self.assertEqual(count,1)
        self.assertEqual(issues,[])
    def test_short_hook_rounding_does_not_erase_sixteenth(self):
        count,_,issues=_stem_beams((100,20,40),40,5,
            [(70,22.9,100,20,2.25),(99.75,24,95.3,24.5,2.25)])
        self.assertEqual(count,2)
        self.assertFalse(issues)
    def test_four_real_beams_are_a_sixty_fourth(self):
        head=dict(char='Ŵ',x=100,y=30)
        beams=[(100,y,125,y,2.25) for y in (50,46,42,38)]
        duration,evidence,issues=_stem_and_duration(head,{'gap':5},[(100,30,100,50,.5)]+beams,[])
        self.assertEqual(duration,1/16)
        self.assertEqual(evidence['beams'],4)
        self.assertFalse(issues)
    def test_shortened_beam_endpoint_meets_stem_within_ink_width(self):
        count,_,issues=_stem_beams((100,20,40),20,5,
            [(70,40,98.7,40,2.25),(88,36.5,100,36.5,1.75)])
        self.assertEqual(count,2)
        self.assertFalse(issues)
    def test_small_notated_head_uses_its_own_minimum_stem_length(self):
        head=dict(char='Ŵ',x=100,y=20,size=7)
        duration,_,issues=_stem_and_duration(head,{'gap':5},[(100,20,100,29.8,.5)],[])
        self.assertEqual(duration,1)
        self.assertFalse(issues)
    def test_incomplete_staff_not_invented(self):
        lines=[(0,y,300,y,.5) for y in [10,15,20,25]]
        self.assertEqual(_staves(lines,300),[])
    def test_staff_line_spacing(self):
        lines=[(0,y,300,y,.5) for y in [10,15,20,25,30]]
        result=_staves(lines,300)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['gap'],5)
    def test_magnified_pdf_canvas_preserves_staff_geometry(self):
        for scale in (1, 5.2, 8):
            with self.subTest(scale=scale):
                lines=[(40*scale,y*scale,570*scale,y*scale,.5*scale)
                       for y in (100,105,110,115,120)]
                result=_staves(lines,612*scale)
                self.assertEqual(len(result),1)
                self.assertEqual(result[0]['gap'],5*scale)
                self.assertEqual(result[0]['top'],100*scale)
                self.assertEqual(result[0]['right'],570*scale)
    def test_unknown_stem_no_fake_quarter(self):
        head={'char':'Ŵ','x':100,'y':20}
        duration,_,issues=_stem_and_duration(head,{'gap':5},[],[])
        self.assertIsNone(duration);self.assertIn('stem_not_resolved',issues)
    def test_octave_chord_heads_share_the_real_free_stem_tip(self):
        heads=[dict(char='Ŵ',x=100,y=y) for y in (25,45)]
        lines=[(106,10,106,45,.5),(106,10,130,10,2.25),(106,13.5,130,13.5,2.25)]
        for head in heads:
            duration,evidence,issues=_stem_and_duration(head,{'gap':5},lines,heads)
            self.assertEqual(duration,.25)
            self.assertEqual(evidence['stem_direction'],'up')
            self.assertFalse(issues)
    def test_shifted_flag_origin_uses_actual_stem_tip(self):
        head={'char':'Ŵ','x':100,'y':30}
        flag={'char':'ŉ','x':100,'y':27,'bbox':[105.5,9,111,25]}
        duration,evidence,issues=_stem_and_duration(head,{'gap':5},[(106,30,106,10,.5)],[flag])
        self.assertEqual(duration,.5);self.assertEqual(evidence['beams'],1);self.assertFalse(issues)
    def test_displaced_chord_head_shares_physical_flag(self):
        head={'char':'Ŵ','x':105.5,'y':27.5}
        flag={'char':'ŉ','x':100,'y':27,'bbox':[105.5,9,111,25]}
        self.assertEqual(_stem_and_duration(head,{'gap':5},[(106,30,106,10,.5)],[flag])[0],.5)
    def test_other_flag_cannot_change_stem_duration(self):
        flag={'char':'ŉ','x':130,'y':30,'bbox':[135,9,141,25]}
        self.assertEqual(_stem_and_duration({'char':'Ŵ','x':100,'y':30},{'gap':5},[(106,30,106,10,.5)],[flag])[0],1)
    def test_whole_measure_rest_follows_meter(self):
        rest={'char':'š','x':20,'y':10}
        self.assertEqual(_rest_duration(rest,5,[],2,True)[0],2)
        self.assertEqual(_rest_duration(rest,5,[],3,True)[0],3)
        self.assertIsNone(_rest_duration(rest,5,[],None,True)[0])
    def test_dotted_whole_note_is_six_quarter_beats(self):
        head=dict(char='Ł',x=100,y=30)
        duration,evidence,issues=_stem_and_duration(head,{'gap':5},[],[dict(char='Ǉ',x=112,y=27.5)])
        self.assertEqual(duration,6)
        self.assertEqual(evidence['dots'],1)
        self.assertFalse(issues)
    def test_stacked_chord_dots_count_as_one_column(self):
        head=dict(char='Ŵ',x=100,y=30)
        dots=[dict(char='Ǉ',x=110,y=y) for y in (27.5,32.5)]
        duration,evidence,issues=_stem_and_duration(head,{'gap':5},[(106,10,106,30,.5)],dots)
        self.assertEqual(duration,1.5)
        self.assertEqual(evidence['dots'],1)
        self.assertFalse(issues)
    def test_double_dot_requires_two_horizontal_columns(self):
        head=dict(char='Ŵ',x=100,y=30)
        dots=[dict(char='Ǉ',x=x,y=27.5) for x in (110,114)]
        self.assertEqual(_stem_and_duration(head,{'gap':5},[(106,10,106,30,.5)],dots)[0],1.75)
    def test_neighbor_note_augmentation_dot_is_not_borrowed(self):
        head=dict(char='Ŵ',x=100,y=30)
        neighbor=dict(char='Ŵ',x=110,y=27.5)
        dot=dict(char='Ǉ',x=116.5,y=27.5)
        duration,evidence,_=_stem_and_duration(head,{'gap':5},[(100,30,100,50,.5)],[head,neighbor,dot])
        self.assertEqual(duration,1)
        self.assertEqual(evidence['dots'],0)
    def test_staccato_over_following_head_is_not_augmentation_dot(self):
        head=dict(char='Ŵ',x=100,y=30)
        following=dict(char='Ŵ',x=108,y=33)
        staccato=dict(char='Ǉ',x=110.4,y=29.5)
        duration,evidence,_=_stem_and_duration(head,{'gap':5},[(100,30,100,50,.5)],[head,following,staccato])
        self.assertEqual(duration,1)
        self.assertEqual(evidence['dots'],0)
    def test_displaced_chord_neighbor_does_not_steal_shared_dot(self):
        head=dict(char='Ŵ',x=100,y=30)
        neighbor=dict(char='Ŵ',x=106,y=27.5)
        dot=dict(char='Ǉ',x=112,y=27.5)
        self.assertEqual(_stem_and_duration(head,{'gap':5},[(106,10,106,30,.5)],[head,neighbor,dot])[0],1.5)
    def test_printed_thirty_second_flag_and_rest(self):
        head=dict(char='Ŵ',x=100,y=30)
        flag=dict(char='ŋ',x=100,y=30,bbox=[105,9,112,29])
        self.assertEqual(_stem_and_duration(head,{'gap':5},[(106,10,106,30,.5)],[flag])[0],.125)
        self.assertEqual(_rest_duration(dict(char='Ŧ',x=20,y=10),5,[],4)[0],.125)
    def test_half_and_unknown_rest(self):
        self.assertEqual(_rest_duration({'char':'Ţ','x':20,'y':10},5,[],4)[0],2)
        self.assertIsNone(_rest_duration({'char':'unmapped-rest','x':20,'y':10},5,[],4)[0])
    def test_close_sequential_heads_not_chord(self):
        events=[dict(origin=[100,30],measure=1,rhythm_evidence={'stem':[106,10,30]}),
                dict(origin=[106,25],measure=1,rhythm_evidence={'stem':[112,5,25]})]
        self.assertEqual(len(_event_groups(events,5)),2)
        events[1]['rhythm_evidence']['stem']=[106,10,30]
        self.assertEqual(len(_event_groups(events,5)),1)
    def test_interlocking_whole_second_is_one_chord(self):
        events=[dict(origin=[100,30],measure=1,glyph_bbox=[100,27,109,33],rhythm_evidence={'head':'whole'}),
                dict(origin=[107,27.5],measure=1,glyph_bbox=[107,25,116,30],rhythm_evidence={'head':'whole'})]
        self.assertEqual(len(_event_groups(events,5)),1)
        events[1]['measure']=2
        self.assertEqual(len(_event_groups(events,5)),2)
    def test_repeat_requires_two_dots_on_correct_side(self):
        staff={'top':10,'bottom':30,'gap':5}
        heavy=(100,10,100,30,2)
        self.assertEqual(_repeat_marks(staff,[heavy],[0,100,200]),[])
        marks=_repeat_marks(staff,[heavy,(104,17.5,104,17.5,2),(104,22.5,104,22.5,2)],[0,100,200])
        self.assertEqual([(m['kind'],m['boundary']) for m in marks],[('start',1)])
    def test_opening_repeat_header_is_not_empty_measure(self):
        staff={'top':10,'bottom':30,'gap':5}
        lines=[(20,10,20,30,2),(24,17.5,24,17.5,2),(24,22.5,24,22.5,2)]
        self.assertEqual(_trim_opening_repeat_prefix(staff,lines,[0,20,100],[{'x':40}]),[20,100])
        self.assertEqual(_trim_opening_repeat_prefix(staff,lines,[0,20,100],[{'x':10},{'x':40}]),[0,20,100])
        self.assertEqual(_trim_opening_repeat_prefix(staff,lines[:1],[0,20,100],[{'x':40}]),[0,20,100])
    def test_opening_repeat_dots_can_be_music_font_glyphs(self):
        staff={'top':10,'bottom':30,'gap':5,'chars':[dict(char='Ǉ',x=24,y=y) for y in (17.5,22.5)]}
        self.assertEqual(_trim_opening_repeat_prefix(staff,[(20,10,20,30,2)],[0,20,100],[{'x':40}]),[20,100])
    def test_tie_candidate_does_not_match_across_intervening_note(self):
        events=[dict(id=i,pitch=p,origin=[x,30],measure=1,rhythm_evidence={},issues=[])
                for i,p,x in [(1,'C4',100),(2,'D4',120),(3,'C4',140)]]
        _annotate_ties(events,[[103,31,143,39]],5)
        self.assertFalse(any(e.get('tie_to_candidate') for e in events))
    def test_tie_candidate_stays_unconfirmed(self):
        events=[dict(id=i,pitch='C4',origin=[x,30],measure=1,rhythm_evidence={},issues=[],confirmed=False)
                for i,x in [(1,100),(2,140)]]
        _annotate_ties(events,[[103,31,143,39]],5)
        self.assertEqual(events[0]['tie_to_candidate'],2)
        self.assertFalse(events[0]['confirmed'])
    def test_matching_paired_short_opening_supports_pickup(self):
        staves=[dict(id=s,gap=5,measures=[dict(measure=1,total_beats=.5,timing_resolved=False)]) for s in ('rh','lh')]
        notes=[dict(staff='rh',measure=1,origin=[x,30],duration=.25,pitch_candidate='C4',rhythm_evidence={},issues=['measure_timing_unresolved']) for x in (100,120)]
        notes.append(dict(staff='lh',measure=1,origin=[100,80],duration=.5,rhythm_evidence={},issues=['measure_timing_unresolved']))
        self.assertEqual(_resolve_pickup(staves,notes,1.5),.5)
        self.assertEqual([n['measure_beat'] for n in notes],[0,.25,0])
        self.assertTrue(staves[0]['measures'][0]['pickup'])
        self.assertIn('pickup_measure_requires_review',notes[0]['issues'])
    def test_inconsistent_short_voice_does_not_invent_pickup(self):
        staves=[dict(id=s,gap=5,measures=[dict(measure=1,total_beats=d,timing_resolved=False)]) for s,d in [('rh',.5),('lh',.75)]]
        self.assertIsNone(_resolve_pickup(staves,[],1.5))
    def test_meter_reads_multidigit_rows(self):
        def digit(n,x,y):return dict(char=chr(0x130+n),x=x,y=y,bbox=[x,y-3,x+5,y+2])
        meter,evidence=_meter_signature({'top':10,'gap':5},[digit(1,20,15),digit(2,27,15),digit(8,23,25)])
        self.assertEqual(meter,6)
        self.assertEqual((evidence['numerator'],evidence['denominator']),(12,8))
        meter,_=_meter_signature({'top':10,'gap':5},[digit(1,20,15),digit(0,27,15),digit(1,20,25),digit(6,27,25)])
        self.assertEqual(meter,2.5)
    def test_meter_rejects_disconnected_or_incomplete_numerals(self):
        staff={'top':10,'gap':5}
        digits=[dict(char='ı',x=20,y=15,bbox=[20,12,25,17]),dict(char='Ĳ',x=70,y=15,bbox=[70,12,75,17]),
                dict(char='ĸ',x=23,y=25,bbox=[23,22,28,27])]
        self.assertIsNone(_meter_signature(staff,digits)[0])
        self.assertIsNone(_meter_signature(staff,digits[:1])[0])
    def test_meter_changes_read_separate_mid_system_signatures(self):
        def digit(n,x,y):return dict(char=chr(0x130+n),x=x,y=y,size=10,bbox=[x,y-3,x+5,y+2])
        chars=[digit(1,20,15),digit(2,27,15),digit(8,23,25),digit(4,180,15),digit(4,180,25)]
        changes=_meter_changes({'top':10,'gap':5},chars)
        self.assertEqual([(c['x'],c['beats']) for c in changes],[(20,6),(180,4)])
    def octave_geometry(self):
        staff={'top':30,'bottom':50,'gap':5,'right':200}
        marker={'char':'ƴ','x':50,'y':20,'bbox':[50,12,62,20]}
        lines=[(x,16,x+3,16,0) for x in range(63,105,6)]+[(106,16,106,19,.5)]
        return staff,marker,lines
    def test_bounded_octave_shifts_only_its_dash_span(self):
        staff,marker,lines=self.octave_geometry()
        regions=_octave_regions(staff,[marker],lines)
        self.assertEqual(regions[0]['shift'],12)
        self.assertEqual(_octave_at(75,regions,5)[0],12)
        self.assertEqual(_octave_at(40,regions,5)[0],0)
        self.assertEqual(_octave_at(130,regions,5)[0],0)
    def test_octave_without_resolved_endpoint_stays_unknown(self):
        staff,marker,lines=self.octave_geometry()
        regions=_octave_regions(staff,[marker],lines[:-1])
        self.assertIsNone(_octave_at(75,regions,5)[0])
        self.assertEqual(_octave_at(40,regions,5)[0],0)
    def test_cut_time_symbol_sets_four_quarter_beats(self):
        staff={'top':30,'bottom':50,'gap':5}
        changes=_meter_changes(staff,[dict(char='Ƌ',x=40,y=40,size=20)])
        self.assertEqual(changes[0]['beats'],4.0)
        self.assertEqual(changes[0]['evidence'],{'symbol':'cut_time'})
    def test_continuous_octave_line_needs_marker_and_terminal_hook(self):
        staff,marker,_=self.octave_geometry()
        line=(63,16,150,16,.5)
        hook=(150,16,150,17.5,.5)
        regions=_octave_regions(staff,[marker],[line,hook])
        self.assertEqual(_octave_at(100,regions,5)[0],12)
        self.assertEqual(_octave_at(170,regions,5)[0],0)
        self.assertEqual(regions[0]['line_type'],'continuous')
        self.assertIsNone(_octave_regions(staff,[marker],[line])[0]['shift'])
        short=_octave_regions(staff,[marker],[(63,16,70,16,.5),(70,16,70,17.5,.5)])
        self.assertEqual(_octave_at(65,short,5)[0],12)
        self.assertEqual(_octave_at(80,short,5)[0],0)
    def test_octave_label_offset_from_first_note_includes_that_column(self):
        staff,marker,_=self.octave_geometry()
        staff['heads']=[{'x':39},{'x':55}]
        regions=_octave_regions(staff,[marker],[(63,16,150,16,.5),(150,16,150,18,.5)])
        self.assertEqual(_octave_at(39,regions,5)[0],12)
        staff['heads'].insert(0,{'x':20})
        regions=_octave_regions(staff,[marker],[(63,16,150,16,.5),(150,16,150,18,.5)])
        self.assertEqual(_octave_at(39,regions,5)[0],0)
    def test_text_fifteenth_only_resolves_unambiguous_final_note(self):
        staff={'top':30,'bottom':50,'gap':5,'right':200,'heads':[{'x':55}]}
        marker=dict(char='text:15ma',x=50,y=20,bbox=[50,12,65,20],octave_semitones=24)
        self.assertEqual(_octave_regions(staff,[marker],[])[0]['shift'],24)
        staff['heads'].append({'x':90})
        self.assertIsNone(_octave_regions(staff,[marker],[])[0]['shift'])
    def test_other_octave_symbol_or_overlap_not_guessed(self):
        staff,marker,lines=self.octave_geometry();marker['char']='Ƶ'
        self.assertIsNone(_octave_regions(staff,[marker],lines)[0]['shift'])
        marker['char']='ƴ';regions=_octave_regions(staff,[marker,marker],lines)
        self.assertIsNone(_octave_at(75,regions,5)[0])
    def voice_note(self,ident,x,duration,direction):
        y=20 if direction=='up' else 30
        return dict(id=ident,origin=[x,y],measure=1,duration=duration,measure_beat=None,
            rhythm_evidence={'head':'filled','stem_direction':direction,'stem':[x,0,y] if direction=='up' else [x,y,50]},
            issues=['measure_timing_unresolved'])
    def test_parallel_voices_have_independent_durations_and_onsets(self):
        notes=[self.voice_note('u'+str(i),100+i*20,1,'up') for i in range(4)]
        notes += [self.voice_note('d'+str(i),100+i*40,2,'down') for i in range(2)]
        self.assertIsNotNone(_resolve_explicit_voices(notes,[],{'gap':5,'top':10},4))
        self.assertEqual([n['measure_beat'] for n in notes],[0,1,2,3,0,2])
        self.assertEqual([n['duration'] for n in notes],[1,1,1,1,2,2])
    def test_sustained_whole_voice_and_rest_then_beamed_voice(self):
        notes=[dict(id='whole',origin=[100,0],measure=1,duration=4,measure_beat=None,
                    rhythm_evidence={'head':'whole'},issues=['measure_timing_unresolved'])]
        notes += [self.voice_note(str(i),110+i*10,.5,'up') for i in range(7)]
        rest=dict(id='r',origin=[100,20],duration=.5,measure_beat=None,rhythm_evidence={},issues=[])
        self.assertIsNotNone(_resolve_explicit_voices(notes,[rest],{'gap':5,'top':10},4))
        self.assertEqual(notes[0]['measure_beat'],0)
        self.assertEqual([n['measure_beat'] for n in notes[1:]],[.5,1,1.5,2,2.5,3,3.5])
    def test_partial_voice_branches_from_verified_half_note_column(self):
        notes=[self.voice_note('u1',100,2,'up'),self.voice_note('u2',140,2,'up'),
               self.voice_note('d1',140,1,'down'),self.voice_note('d2',160,1,'down')]
        self.assertIsNotNone(_resolve_explicit_voices(notes,[],{'gap':5,'top':10},4))
        self.assertEqual([n['measure_beat'] for n in notes],[0,2,2,3])
        self.assertEqual(notes[-1]['onset_evidence']['method'],'anchored_partial_explicit_voice')
    def test_centered_rests_get_only_unique_complete_voice_allocation(self):
        notes=[self.voice_note('u1',120,1,'up'),self.voice_note('u2',160,1,'up')]
        notes += [self.voice_note('d'+str(i),100+20*i,1,'down') for i in range(4)]
        rests=[dict(id='r'+str(i),origin=[x,20],duration=1,measure_beat=None,rhythm_evidence={},issues=[])
               for i,x in enumerate((100,140))]
        self.assertIsNotNone(_resolve_explicit_voices(notes,rests,{'gap':5,'top':10},4))
        self.assertEqual([n['measure_beat'] for n in notes[:2]],[1,3])
        self.assertEqual([r['measure_beat'] for r in rests],[0,2])
    def test_partial_voice_onsets_only_follow_unique_alignment(self):
        notes=[self.voice_note('u1',100,1,'up'),self.voice_note('u2',129,1,'up')]
        notes += [self.voice_note('d'+str(i),100+i*20,1,'down') for i in range(4)]
        self.assertIsNotNone(_resolve_explicit_voices(notes,[],{'gap':5,'top':10},4))
        self.assertEqual(notes[0]['measure_beat'],0)
        self.assertIsNone(notes[1]['measure_beat'])
    def test_stem_direction_changes_without_simultaneity_not_two_voices(self):
        notes=[self.voice_note('u1',100,2,'up'),self.voice_note('u2',140,2,'up'),
               self.voice_note('d1',120,2,'down'),self.voice_note('d2',160,2,'down')]
        self.assertIsNone(_resolve_explicit_voices(notes,[],{'gap':5,'top':10},4))
        self.assertTrue(all(n['measure_beat'] is None for n in notes))
    def test_voice_sums_cannot_override_contradictory_note_columns(self):
        notes=[self.voice_note('u1',100,1,'up'),self.voice_note('u2',140,1,'up'),
               self.voice_note('d1',100,2,'down'),self.voice_note('d2',140,2,'down')]
        rest=dict(id='r',origin=[120,10],duration=2,measure_beat=None,rhythm_evidence={},issues=['measure_timing_unresolved'])
        self.assertIsNone(_resolve_explicit_voices(notes,[rest],{'gap':5,'top':10},4))
        self.assertTrue(all(n['measure_beat'] is None for n in notes))
    def ordinary_bar(self):
        staves=[dict(gap=5,top=top,bottom=top+20,bars=[0,100,200,300],
            measures=[dict(measure=2,total_beats=total,timing_resolved=False)]) for top,total in [(10,4.125),(60,4.25)]]
        lines=[(x,10,x,80,.6) for x in (100,200)]
        return staves,lines
    def test_ordinary_bar_extent_does_not_require_local_rhythm_resolution(self):
        staves,lines=self.ordinary_bar()
        evidence=_ordinary_metric_extent(staves,lines,2,4)
        self.assertEqual(evidence['quarter_beats'],4)
        self.assertFalse(evidence['local_note_onsets_verified'])
        self.assertTrue(all(not s['measures'][0]['timing_resolved'] for s in staves))
    def test_metric_extent_needs_shared_thin_physical_boundaries(self):
        staves,lines=self.ordinary_bar()
        self.assertIsNone(_ordinary_metric_extent(staves,lines[:1],2,4))
        self.assertIsNone(_ordinary_metric_extent(staves,[(x,10,x,30,.6) for x in (100,200)],2,4))
        self.assertIsNone(_ordinary_metric_extent(staves,[(x,10,x,80,2) for x in (100,200)],2,4))
        staves[1]['bars'][1]=105
        self.assertIsNone(_ordinary_metric_extent(staves,lines,2,4))
    def test_metric_extent_rejects_paired_irregular_lengths_and_exceptions(self):
        staves,lines=self.ordinary_bar()
        self.assertIsNone(_ordinary_metric_extent(staves,lines,2,4,excluded=True))
        self.assertIsNone(_ordinary_metric_extent(staves,lines,2,None))
        for length in (1,5):
            for staff in staves:staff['measures'][0]['total_beats']=length
            self.assertIsNone(_ordinary_metric_extent(staves,lines,2,4))
    def test_aligned_separate_staff_barlines_establish_same_meter(self):
        staves,_=self.ordinary_bar()
        lines=[(x,top,x,top+20,.6) for x in (100,200) for top in (10,60)]
        self.assertEqual(_ordinary_metric_extent(staves,lines,2,4)['quarter_beats'],4)
    def test_explicit_measure_meter_resolves_after_a_printed_change(self):
        staves,lines=self.ordinary_bar()
        for staff in staves:
            staff['later_meter_change']=True
            staff['measures'][0]['meter_beats']=4
        self.assertEqual(_ordinary_metric_extent(staves,lines,2,4)['quarter_beats'],4)
    def test_later_meter_change_prevents_inherited_metric_extent(self):
        staves,lines=self.ordinary_bar();staves[0]['later_meter_change']=True
        self.assertIsNone(_ordinary_metric_extent(staves,lines,2,4))
    def test_complete_ledger_chain_overrides_nearer_neighbor_staff(self):
        staves=[dict(top=10,bottom=30,gap=5,left=0,right=300),dict(top=60,bottom=80,gap=5,left=0,right=300)]
        head=dict(x=100,y=50)
        lines=[(99,y,108,y,.5) for y in (35,40,45,50)]
        self.assertIs(_nearest_staff(head,staves),staves[1])
        owner,evidence=_head_staff(head,staves,lines)
        self.assertIs(owner,staves[0]);self.assertEqual(evidence['ledger_lines'],4)
        self.assertTrue(evidence['nearest_staff_reassigned'])
        owner,evidence=_head_staff(head,staves,lines[1:])
        self.assertIs(owner,staves[1]);self.assertIsNone(evidence)
    def test_two_complete_ledger_chains_remain_ambiguous(self):
        staves=[dict(top=10,bottom=30,gap=5,left=0,right=300),dict(top=60,bottom=80,gap=5,left=0,right=300)]
        _,evidence=_head_staff(dict(x=100,y=50),staves,[(99,y,108,y,.5) for y in (35,40,45,50,55)])
        self.assertTrue(evidence['ambiguous'])
    def test_crossing_nonparallel_beam_not_counted_as_extra_flag(self):
        lines=[(90,10,120,10,2.5),(90,13.5,120,13.5,2.5),(90,10.5,120,13.5,2.5)]
        count,_,issues=_stem_beams((100,10,30),30,5,lines)
        self.assertEqual(count,2);self.assertFalse(issues)
    def test_competing_attachment_or_irregular_beam_spacing_stays_unknown(self):
        count,_,issues=_stem_beams((100,10,30),30,5,[(90,10,120,10,2.5),(90,9,120,12,2.5)])
        self.assertIsNone(count);self.assertIn('beam_attachment_ambiguous',issues)
        count,_,issues=_stem_beams((100,10,30),30,5,[(90,y,120,y,2.5) for y in (10,13.5,20)])
        self.assertIsNone(count);self.assertIn('beam_spacing_conflict',issues)

@unittest.skipUnless(SAMPLES.exists(),'Original PDF corpus is external to the source repository')
class RealScoreTests(unittest.TestCase):
    def project(self,prefix):return recognize_pdf(next(SAMPLES.glob(prefix+'*.pdf')))
    def test_czerny65_original_opening(self):
        notes=self.project('1002307')['notes'][:12]
        self.assertEqual([n['pitch'] for n in notes],['D5','E5']*6)
        self.assertEqual([n['finger'] for n in notes],[1,2]*6)
        self.assertEqual([n['duration_beats'] for n in notes],[.25]*12)
    def test_rain_original_below_fingering_retained_for_review(self):
        notes=self.project('1219102')['notes'][:2]
        self.assertEqual([n['pitch'] for n in notes],['G#4','B4'])
        self.assertEqual([n['finger'] for n in notes],[3,5])
    def test_pumpkin_right_does_not_borrow_bass_finger(self):
        notes=[n for n in self.project('1003497')['notes'] if n['page']==1 and n['system']==1 and n['measure']==3 and n['hand']=='right']
        self.assertEqual([n['finger'] for n in notes],[1,2,3,1,2,3])
    def test_verified_polka_beats_survive_slur_warning(self):
        notes=self.project('1007271')['notes'][:7]
        self.assertEqual([n['beat'] for n in notes],[0,.5,.75,1,1.5,2,3])
        self.assertIn('tie_or_slur_requires_review',notes[1]['issues'])
        self.assertFalse(notes[1]['confirmed'])
    def test_explicit_shared_staff_voices_recover_right_hand(self):
        project=self.project('1002604')
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual(len(right),225)
        self.assertEqual([n['pitch'] for n in right[:8]],['C3','E3','A3','G3','F3','G3','F3','E3'])
        self.assertEqual([n['beat'] for n in right[:8]],[i*.25 for i in range(8)])
        self.assertFalse(any(n['confirmed'] for n in right))
    def test_voice_switching_between_staves_preserves_entire_measure(self):
        project=self.project('1002602')
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual(len(right),225)
        self.assertTrue(all(n['finger'] is not None and n['beat'] is not None for n in right))
        transition=sorted((n for n in right if n['page']==2 and n['system']==3 and n['measure']==3),key=lambda n:n['beat'])
        self.assertEqual([n['pitch'] for n in transition],['F4','E4','F4','C4','A3','B3','C4','D4'])
        self.assertEqual([n['finger'] for n in transition],[5,4,5,2,1,2,3,4])
        self.assertEqual([n['beat'] for n in transition],[44+i*.25 for i in range(8)])
        self.assertEqual(project['repeat_sections'][0]['end_beat'],56)
    def test_plain_text_15ma_is_not_ignored(self):
        project=self.project('1078144')
        final=[n for n in project['notes'] if n['hand']=='right'][-1]
        self.assertEqual((final['written_pitch'],final['pitch'],final['octave_shift']),('A5','A7',24))
        self.assertIn('octave_line_requires_review',final['issues'])
    def test_whole_rest_bars_and_repeat_start_preserve_written_onsets(self):
        project=self.project('969886')
        notes=[n for n in project['notes'] if n['page']==1 and n['system']==1 and n['hand']=='right']
        self.assertEqual(notes[0]['beat'],4)
        self.assertEqual(notes[19]['duration'],.5)
        self.assertEqual(project['repeat_sections'][0]['start_beat'],4)
        self.assertFalse(project['repeat_sections'][0]['confirmed'])
    def test_displaced_second_chord_is_simultaneous(self):
        notes=[n for n in self.project('1003497')['notes'] if n['page']==1 and n['system']==2 and n['hand']=='right']
        self.assertEqual([n['duration'] for n in notes[3:5]],[.5,.5])
        self.assertEqual([n['beat'] for n in notes[3:5]],[13.5,13.5])
    def test_tied_continuation_does_not_borrow_bass_finger(self):
        project=self.project('969886')
        note=next(n for n in project['notes'] if n['page']==1 and n['system']==2 and n['measure']==3 and n['hand']=='right')
        self.assertIsNone(note['finger'])
        self.assertTrue(note.get('tie_from_candidate'))
    def test_verified_pickup_uses_short_metric_length(self):
        project=self.project('939323')
        notes=[n for n in project['notes'] if n['page']==1 and n['system']==1 and n['hand']=='right']
        self.assertEqual(project['pickup_beats'],.5)
        self.assertEqual([n['beat'] for n in notes[:3]],[0,.25,.5])
        self.assertFalse(notes[0]['confirmed'])
    def test_reviewed_first_and_second_endings_preserve_source_coordinates(self):
        project=self.project('969886')
        repeat=project['repeat_sections'][0]
        self.assertEqual([repeat['first_ending_start_beat'],repeat['end_beat'],repeat['second_ending_end_beat']],[18,20,22])
        for note in project['notes']:note['confirmed']=True
        project['selection'].update(range_reviewed=True,start_page=1,end_page=1,start_system=1,end_system=2,
            end_measure=5,end_beat=22,repeat_mode='unfold',repeats_reviewed=True,apply_tie_candidates=True,ties_reviewed=True)
        score=export_reviewed(project)
        self.assertEqual(score['duration_ms'],18000)
        self.assertEqual(len(score['source_notes']),len(score['notes']))
        self.assertTrue(all(n.get('page')==1 and n.get('bbox') for n in score['source_notes']))
    def test_opening_repeat_on_later_page_preserves_global_position(self):
        project=self.project('1002307')
        note=next(n for n in project['notes'] if n['page']==2 and n['hand']=='right')
        self.assertEqual(note['measure'],1)
        self.assertEqual(note['beat'],24)
    def test_whole_arpeggio_chord_is_not_unknown_rest(self):
        project=self.project('979359')
        notes=[n for n in project['notes'] if n['page']==1 and n['system']==1 and n['measure']==1 and n['hand']=='right']
        self.assertEqual([n['pitch'] for n in notes],['G6','B5','C6'])
        self.assertEqual([n['finger'] for n in notes],[5,1,2])
        self.assertEqual([n['beat'] for n in notes],[0,0,0])
        self.assertEqual([n['duration'] for n in notes],[4,4,4])
        self.assertFalse(any(r['rhythm_evidence']['glyph']=='Ƭ' for r in project['rests']))
        self.assertTrue(any('arpeggio_requires_review' in n['issues'] for n in notes))
    def test_actual_sustained_upper_voice_does_not_serialize_lower_voice(self):
        project=self.project('1002169')
        notes=[n for n in project['notes'] if n['page']==2 and n['system']==2 and n['measure']==1 and n['hand']=='right']
        self.assertEqual([n['pitch'] for n in notes],['F5','B4','C5'])
        self.assertEqual([n['finger'] for n in notes],[4,1,1])
        self.assertEqual([n['duration'] for n in notes],[4,2,2])
        self.assertEqual([n['measure_beat'] for n in notes],[0,0,2])
        self.assertEqual([n['beat'] for n in notes],[40,40,42])
        self.assertTrue(all(not n['confirmed'] for n in notes))
    def test_complete_bass_voice_preserves_bar_after_unknown_right_notes(self):
        project=self.project('30483')
        unknown=[n for n in project['notes'] if n['hand']=='right' and n['page']==1 and n['system']==3 and n['measure']==2]
        self.assertTrue(all(n['beat'] is not None for n in unknown))
        triplets=[n for n in unknown if n['rhythm_evidence'].get('tuplet')]
        self.assertEqual(len(triplets),3)
        self.assertEqual([n['beat'] for n in triplets],[23,23.083333,23.166667])
        self.assertTrue(all(abs(n['duration']-1/12)<1e-9 for n in triplets))
        staff=next(s for s in project['staves'] if s['id']=='p1-s5')
        self.assertTrue(staff['measures'][1]['timing_resolved'])
        bass=next(s for s in project['staves'] if s['id']=='p1-s6')
        self.assertTrue(bass['measures'][1]['timing_resolved'])
        self.assertEqual(bass['measures'][1]['length_beats'],4)
        following=next(n for n in project['notes'] if n['hand']=='right' and n['page']==1 and n['system']==4)
        self.assertEqual(following['measure_beat'],0)
        self.assertEqual(following['beat'],24)
        self.assertFalse(following['confirmed'])
    def test_deep_ledger_opening_uses_printed_rh_staff_and_parallel_beams(self):
        project=self.project('941398')
        notes=[n for n in project['notes'] if n['page']==1 and n['system']==1 and n['measure']==1 and n['hand']=='right']
        self.assertEqual([n['pitch'] for n in notes],['G#2','C#3','E3','G#3','C#3','E3','G#3','C#4','G#3','C#4','E4','E4','G#3','C#4','E4'])
        self.assertEqual([n['finger'] for n in notes],[1,2,3,5,1,2,3,4,1,4,5,5,1,2,3])
        self.assertEqual([n['duration'] for n in notes],[.25]*15)
        self.assertEqual([n['beat'] for n in notes],[.25+i*.25 for i in range(15)])
        self.assertFalse(any(n['confirmed'] for n in notes))

DEVELOPMENT_MANIFEST=Path(__file__).resolve().parents[3]/'evidence/customer-pdf-r4-20261025/input-manifest.json'

@unittest.skipUnless(DEVELOPMENT_MANIFEST.exists(),'Prior fourteen development PDFs are external test data')
class DevelopmentLayoutTests(unittest.TestCase):
    projects={}
    def project(self,identity):
        import json
        from score_converter_engine import recognize
        if identity not in self.projects:
            records=json.loads(DEVELOPMENT_MANIFEST.read_text(encoding='utf-8'))['items']
            path=next(row['path'] for row in records if row['id']==identity)
            self.projects[identity]=recognize(path)
        return self.projects[identity]
    def test_printed_below_dyad_keeps_both_digits_in_pitch_order(self):
        project=self.project('new-04')
        notes={n['id']:n for n in project['notes']}
        self.assertEqual([notes[i]['finger'] for i in ('p2-n280','p2-n281')],[5,3])
    def test_complete_left_chord_columns_do_not_supply_right_fingers(self):
        project=self.project('new-02');notes={n['id']:n for n in project['notes']}
        self.assertEqual([notes[i]['finger'] for i in ('p2-n488','p2-n489','p2-n490')],[1,3,5])
        self.assertEqual([notes[i]['finger'] for i in ('p3-n703','p3-n704','p3-n705')],[1,2,3])
        self.assertIsNone(notes['p3-n670']['finger'])
    def test_whole_left_chord_preserves_its_complete_printed_stack(self):
        project=self.project('new-13');notes={n['id']:n for n in project['notes']}
        self.assertEqual([notes[i]['finger'] for i in ('p3-n497','p3-n498','p3-n499')],[1,2,5])
    def test_close_two_hand_digits_keep_separate_uneven_columns(self):
        from score_converter_engine import recognize
        project=recognize(Path(__file__).resolve().parents[1]/'assets/score-library/1013091.pdf')
        notes={n['id']:n for n in project['notes']}
        self.assertEqual([notes[i]['finger'] for i in ('p3-n1384','p3-n1385')],[5,2])
        self.assertEqual([notes[i]['finger'] for i in ('p3-n1413','p3-n1414','p3-n1415')],[1,3,5])
    def test_complete_arpeggio_columns_survive_previous_system_processing(self):
        project=self.project('new-02')
        for ids in (('p1-n118','p1-n119','p1-n120'),('p1-n131','p1-n132','p1-n133')):
            notes=[next(n for n in project['notes'] if n['id']==identifier) for identifier in ids]
            self.assertEqual([n['finger'] for n in notes],[5,3,1])
            self.assertTrue(all(n['finger_source']=='printed' for n in notes))
    def test_unprinted_right_notes_do_not_take_adjacent_left_hand_stack(self):
        project=self.project('new-02')
        for identifier in ('p2-n434','p2-n470','p4-n1075','p4-n1127','p5-n1208','p5-n1244'):
            note=next(n for n in project['notes'] if n['id']==identifier)
            self.assertIsNone(note['finger'],identifier)
    def test_partial_printed_dyad_does_not_invent_lower_finger(self):
        project=self.project('new-14')
        for ids in (('p2-n319','p2-n320'),('p2-n362','p2-n363')):
            notes=[next(n for n in project['notes'] if n['id']==identifier) for identifier in ids]
            self.assertEqual([n['finger'] for n in notes],[5,None])
    def test_true_graces_keep_unknown_time_without_moving_principal_notes(self):
        for identity,ids,anchor,kind in [('new-02',('p4-n1063','p4-n1064'),220,'unmeasured_prefix'),
                                        ('new-14',('p6-n1069',),219,'slashed')]:
            project=self.project(identity)
            for identifier in ids:
                note=next(n for n in project['notes'] if n['id']==identifier)
                self.assertIsNone(note['duration']);self.assertIsNone(note['beat'])
                self.assertEqual(note['main_anchor_beat'],anchor)
                self.assertEqual(note['grace_kind'],kind)
                principal=next(n for n in project['notes'] if n['id']==note['main_anchor_id'])
                self.assertEqual(principal['beat'],anchor)
    def test_mixed_bracketed_tuplet_matches_independent_symbol_reading(self):
        project=self.project('new-04')
        ids=('p2-n305','p2-n307','p2-n309','p2-n310','p2-n311')
        notes=[next(n for n in project['notes'] if n['id']==identifier) for identifier in ids]
        for note,value in zip(notes,(.25,1/24,.125,1/12,1/12)):
            self.assertAlmostEqual(note['duration'],value)
        for note,value in zip(notes,(75.5,75.75,75+19/24,75+5/6,75+11/12)):
            self.assertAlmostEqual(note['beat'],value,places=5)
    @unittest.skipUnless(SAMPLES.exists(),'Original Polka PDF is external test data')
    def test_pdf_translation_and_scaling_preserve_music_and_printed_fingers(self):
        import json
        from tempfile import TemporaryDirectory
        from pypdf import PdfReader,PdfWriter,Transformation
        from pypdf.generic import RectangleObject
        from score_converter_engine import recognize
        records=json.loads(DEVELOPMENT_MANIFEST.read_text(encoding='utf-8'))['items']
        sources=[next(SAMPLES.glob('1007271*.pdf')),Path(next(r['path'] for r in records if r['id']=='new-07'))]
        def signature(project):
            return [(n['page'],n['staff'],n['hand'],n['pitch'],n['finger'],
                     round(n['duration'],6) if n['duration'] is not None else None,
                     round(n['beat'],6) if n['beat'] is not None else None) for n in project['notes']]
        with TemporaryDirectory() as folder:
            for source in sources:
                expected=signature(recognize(source))
                for scale,dx,dy in ((.5,0,0),(1,37,53),(1.7,21,35),(3,0,0)):
                    with self.subTest(source=source.name,scale=scale,dx=dx,dy=dy):
                        reader=PdfReader(source);writer=PdfWriter()
                        for page in reader.pages:
                            page=writer.add_page(page)
                            width=float(page.mediabox.width)*scale+2*dx;height=float(page.mediabox.height)*scale+2*dy
                            page.add_transformation(Transformation((scale,0,0,scale,dx,dy)))
                            page.mediabox=RectangleObject([0,0,width,height]);page.cropbox=RectangleObject([0,0,width,height])
                        target=Path(folder)/'transformed.pdf'
                        with target.open('wb') as stream:
                            writer.write(stream)
                        self.assertEqual(signature(recognize(target)),expected)

if __name__=='__main__':unittest.main()
