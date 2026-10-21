"""Synthetic coordinate cases for fixes, independent of filenames/answer keys."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _staves, _stem_and_duration, _rest_duration, _event_groups, _repeat_marks, _annotate_ties, _resolve_pickup, _meter_signature, _octave_regions, _octave_at, _trim_opening_repeat_prefix, _resolve_explicit_voices, _ordinary_metric_extent, _head_staff, _nearest_staff, _stem_beams
from score_converter import recognize_pdf, export_reviewed
SAMPLES=Path(__file__).resolve().parents[4]/'piano-score-trainer'/'samples'

class GeometryTests(unittest.TestCase):
    def test_incomplete_staff_not_invented(self):
        lines=[(0,y,300,y,.5) for y in [10,15,20,25]]
        self.assertEqual(_staves(lines,300),[])
    def test_staff_line_spacing(self):
        lines=[(0,y,300,y,.5) for y in [10,15,20,25,30]]
        result=_staves(lines,300)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['gap'],5)
    def test_unknown_stem_no_fake_quarter(self):
        head={'char':'Ŵ','x':100,'y':20}
        duration,_,issues=_stem_and_duration(head,{'gap':5},[],[])
        self.assertIsNone(duration);self.assertIn('stem_not_resolved',issues)
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
    def test_unknown_cross_staff_not_executable(self):
        note=self.project('1002604')['notes'][0]
        self.assertIsNone(note['hand']);self.assertIsNone(note['beat'])
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
    def test_ordinary_internal_bar_unknown_notes_do_not_poison_next_bar(self):
        project=self.project('30483')
        unknown=[n for n in project['notes'] if n['hand']=='right' and n['page']==1 and n['system']==3 and n['measure']==2]
        self.assertTrue(all(n['beat'] is None for n in unknown))
        staff=next(s for s in project['staves'] if s['id']=='p1-s5')
        self.assertEqual(staff['measures'][1]['metric_extent_evidence']['quarter_beats'],4)
        self.assertFalse(staff['measures'][1]['timing_resolved'])
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

if __name__=='__main__':unittest.main()
