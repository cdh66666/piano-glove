"""Independent synthetic notation controls, unrelated to user-PDF answers."""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent.parent.parent/'repo/host'))
sys.path.insert(0,str(HERE))
from score_converter_engine import _apply_printed_tuplets, _apply_omitted_tuplet_numbers
from score_timing import reflow_right_hand_timing

METER={'numerator':4,'denominator':4,'digit_bboxes':[[10,70,15,90]]}

def fixture(*,measure=1,measure_count=2,page=1,system=1,staff_id='staff-a',hand='right',
            counts=(3,3,3,3),directions=None,depth=1,scale=1,dx=0,dy=0,actual=3,printed=False):
    """Regular note columns and real attached beams; no score-specific data."""
    directions=directions or ['down']*len(counts)
    staff={'id':staff_id,'hand':hand,'system':system,'gap':10*scale}
    notes=[];lines=[];markers=[];x=50
    for group_index,count in enumerate(counts):
        direction=directions[group_index]
        tip=130 if direction=='down' else 50
        start=x
        for column in range(count):
            stem=[(x+dx)*scale,(min(tip,90)+dy)*scale,(max(tip,90)+dy)*scale]
            note={'id':f'neutral-{page}-{staff_id}-{measure}-{len(notes)}',
                  'page':page,'system':system,'staff':staff_id,'measure':measure,'hand':hand,
                  'origin':[(x+dx)*scale,(90+dy)*scale],'duration':2.0**(-depth),
                  'beats':2.0**(-depth),'issues':[],'confirmed':False,
                  'rhythm_evidence':{'head':'filled','beams':depth,'dots':0,'flag_bboxes':[],
                                     'stem':stem,'stem_direction':direction}}
            notes.append(note);x+=18
        end=x-18
        lines.append([(start+dx)*scale,(tip+dy)*scale,(end+dx)*scale,(tip+dy)*scale,5*scale])
        if printed:
            for offset in range(0,count,actual):
                if offset+actual>count:continue
                cx=start+18*(offset+(actual-1)/2)
                cy=tip+(10 if direction=='down' else -10)
                markers.append({'char':str(actual),'font':'Independent-Test-Numerals',
                    'bbox':[(cx-2+dx)*scale,(cy-3+dy)*scale,(cx+2+dx)*scale,(cy+3+dy)*scale],
                    'x':(cx-2+dx)*scale,'y':(cy+3+dy)*scale,'size':8*scale})
        x+=25
    if printed:_apply_printed_tuplets(notes,staff,lines,markers)
    return {'notes':notes,'rests':[],'staff':staff,'lines':lines,'meter':4,
            'meter_evidence':copy.deepcopy(METER),'measure':measure,'measure_count':measure_count}

def apply(part,state):
    _apply_omitted_tuplet_numbers(**part,continuations=state)

def seeded(**kwargs):
    state={};source=fixture(printed=True,**kwargs);apply(source,state)
    if not state:raise AssertionError('Synthetic printed source did not establish a seed')
    return state,source

class TupletContinuationControls(unittest.TestCase):
    def assert_inferred(self,part,count=None):
        notes=part['notes']
        self.assertEqual(count if count is not None else len(notes),sum(n.get('duration_estimated',False) for n in notes))
        for n in notes:
            t=n['rhythm_evidence']['tuplet']
            self.assertTrue(n['timing_estimated'])
            self.assertAlmostEqual(n['duration'],t['nominal_duration_beats']*t['normal']/t['actual'])
            self.assertTrue(t['estimated']);self.assertNotIn('marker_bbox',t)
            self.assertTrue(t['source_printed_tuplet']['marker_bboxes'])

    def assert_unchanged(self,part,state):
        before=copy.deepcopy(part['notes']);apply(part,state)
        self.assertEqual(before,part['notes'])
        self.assertFalse(state.get(part['staff']['hand']))

    def test_complete_explicit_measure_then_matching_beams(self):
        state,source=seeded()
        target=fixture(measure=2);apply(target,state);self.assert_inferred(target)
        self.assertTrue(all(not n.get('duration_estimated') for n in source['notes']))

    def test_direction_may_change_between_serial_complete_groups(self):
        state,_=seeded();target=fixture(measure=2,directions=['up','down','up','down'])
        apply(target,state);self.assert_inferred(target)

    def test_left_hand_continuation_is_also_marked_estimated(self):
        state,_=seeded(hand='left');target=fixture(measure=2,hand='left')
        apply(target,state);self.assert_inferred(target)

    def test_six_stem_source_with_two_printed_triplet_subgroups(self):
        state,_=seeded(counts=(6,6))
        target=fixture(measure=2,counts=(6,6));apply(target,state);self.assert_inferred(target)

    def test_six_stem_source_may_continue_explicit_subgroup_size(self):
        state,_=seeded(counts=(6,6))
        target=fixture(measure=2,counts=(3,3,3,3));apply(target,state);self.assert_inferred(target)

    def test_unobserved_six_stem_grouping_is_conservative(self):
        state,_=seeded();self.assert_unchanged(fixture(measure=2,counts=(6,6)),state)

    def test_five_in_four_uses_its_printed_ratio(self):
        state,_=seeded(actual=5,counts=(5,5))
        target=fixture(measure=2,counts=(5,5));apply(target,state);self.assert_inferred(target)
        self.assertTrue(all(abs(n['duration']-.4)<1e-9 for n in target['notes']))

    def test_scale_and_translation_invariance(self):
        for scale,dx,dy in ((.5,-30,17),(1.8,713,-260),(3.25,-12,1024)):
            with self.subTest(scale=scale):
                state,_=seeded(scale=scale,dx=dx,dy=dy)
                target=fixture(measure=2,scale=scale,dx=dx,dy=dy,directions=['up','down','up','down'])
                apply(target,state);self.assert_inferred(target)

    def test_adjacent_system_preserves_same_hand(self):
        state,_=seeded(measure=2,measure_count=2)
        target=fixture(measure=1,system=2,staff_id='staff-b');apply(target,state);self.assert_inferred(target)

    def test_adjacent_page_preserves_same_hand(self):
        state,_=seeded(measure=2,measure_count=2,system=5)
        target=fixture(measure=1,page=2,system=1,staff_id='staff-b');apply(target,state);self.assert_inferred(target)

    def test_no_printed_marker_even_when_ratio_would_fill_measure(self):
        self.assert_unchanged(fixture(measure=2),{})

    def test_partial_numbered_measure_does_not_seed(self):
        source=fixture(printed=True)
        for n in source['notes'][3:]:n['duration']=n['beats']=.5;n['rhythm_evidence'].pop('tuplet',None)
        state={};apply(source,state);self.assertFalse(state)
        self.assert_unchanged(fixture(measure=2),state)

    def test_incomplete_explicit_measure_does_not_seed(self):
        state={};source=fixture(printed=True,counts=(3,3,3));apply(source,state)
        self.assertFalse(state);self.assert_unchanged(fixture(measure=2),state)

    def test_bracketed_mixed_source_does_not_seed(self):
        source=fixture(printed=True)
        for n in source['notes']:n['rhythm_evidence']['tuplet']['method']='explicit_capped_bracket_and_mixed_beamed_voice'
        state={};apply(source,state);self.assertFalse(state)

    def test_nominal_complete_ordinary_measure_stops_continuation(self):
        state,_=seeded();ordinary=fixture(measure=2,measure_count=3,counts=(2,2,2,2))
        self.assert_unchanged(ordinary,state)
        self.assert_unchanged(fixture(measure=3,measure_count=3),state)

    def test_rest_stops_passage(self):
        state,_=seeded();part=fixture(measure=2);part['rests']=[{'duration':1}]
        self.assert_unchanged(part,state)

    def test_incomplete_unmarked_measure_stops_passage(self):
        state,_=seeded();self.assert_unchanged(fixture(measure=2,counts=(3,3,3)),state)

    def test_missing_beam_cannot_be_replaced_by_meter_sum(self):
        state,_=seeded();part=fixture(measure=2);part['lines']=part['lines'][:-1]
        self.assert_unchanged(part,state)

    def test_true_simultaneous_voices_rejected_despite_matching_total(self):
        state,_=seeded()
        lower=fixture(measure=2,counts=(3,3),directions=['down','down'])
        upper=fixture(measure=2,counts=(3,3),directions=['up','up'])
        for n in upper['notes']:n['id']='other-'+n['id']
        lower['notes']+=upper['notes'];lower['lines']+=upper['lines']
        self.assertAlmostEqual(sum(n['duration'] for n in lower['notes'])*2/3,4)
        self.assert_unchanged(lower,state)

    def test_explicit_voice_label_stops_unqualified_stream(self):
        state,_=seeded();part=fixture(measure=2)
        for i,n in enumerate(part['notes']):n['voice']=i%2+1
        self.assert_unchanged(part,state)

    def test_mixed_direction_inside_one_beam_group_is_not_single_voice(self):
        state,_=seeded();part=fixture(measure=2)
        part['notes'][0]['rhythm_evidence']['stem_direction']='up'
        self.assert_unchanged(part,state)

    def test_beam_depth_change_stops_passage(self):
        state,_=seeded();self.assert_unchanged(fixture(measure=2,depth=2,counts=(3,)*8),state)

    def test_mixed_beam_depth_stops_passage(self):
        state,_=seeded();part=fixture(measure=2);part['notes'][3]['rhythm_evidence']['beams']=2
        self.assert_unchanged(part,state)

    def test_same_quarter_beats_but_different_meter_signature_stops(self):
        state,_=seeded();part=fixture(measure=2);part['meter_evidence']={'numerator':2,'denominator':2}
        self.assert_unchanged(part,state)

    def test_new_meter_cannot_choose_new_ratio(self):
        state,_=seeded();part=fixture(measure=2,counts=(3,3,3));part['meter']=3
        part['meter_evidence']={'numerator':3,'denominator':4};self.assert_unchanged(part,state)

    def test_unknown_meter_signature_stops(self):
        state,_=seeded();part=fixture(measure=2);part['meter_evidence']=None
        self.assert_unchanged(part,state)

    def test_nonadjacent_measure_stops(self):
        state,_=seeded();self.assert_unchanged(fixture(measure=3,measure_count=3),state)

    def test_skipped_system_stops(self):
        state,_=seeded(measure=2,measure_count=2)
        self.assert_unchanged(fixture(system=3,staff_id='staff-c'),state)

    def test_skipped_page_stops(self):
        state,_=seeded(measure=2,measure_count=2)
        self.assert_unchanged(fixture(page=3,staff_id='staff-c'),state)

    def test_same_ratio_does_not_cross_hands(self):
        state,_=seeded();part=fixture(measure=2,hand='left');before=copy.deepcopy(part['notes'])
        apply(part,state);self.assertEqual(part['notes'],before)

    def test_protected_values_remain_unchanged_and_stop_chain(self):
        for key,value in (('confirmed',True),('reviewed',True),('manual_fields',['duration_beats']),('manual_fields',['finger'])):
            with self.subTest(key=key,value=value):
                state,_=seeded();part=fixture(measure=2);part['notes'][0][key]=value
                self.assert_unchanged(part,state)

    def test_new_explicit_measure_can_restart_after_interruption(self):
        state,_=seeded();part=fixture(measure=2,measure_count=4,counts=(3,3,3));apply(part,state)
        source=fixture(printed=True,measure=3,measure_count=4);apply(source,state)
        target=fixture(measure=4,measure_count=4);apply(target,state);self.assert_inferred(target)

    def test_reflow_retains_estimated_status_and_one_warning_per_measure(self):
        state,_=seeded();part=fixture(measure=2);apply(part,state)
        for i,n in enumerate(part['notes']):
            n.update(measure_beat=i/3,beat=4+i/3,written_beat=4+i/3,duration_beats=n['duration'])
        staff={**part['staff'],'page':1,'bbox':[0,70,500,110],'lines':[70,80,90,100,110],
               'measures':[{'measure':2,'meter_beats':4,'length_beats':4,'timing_resolved':True}]}
        project={'notes':part['notes'],'rests':[],'staves':[staff]}
        reflow_right_hand_timing(project)
        self.assertTrue(all(n.get('timing_estimated') for n in part['notes']))
        self.assertEqual(sum(bool(n.get('timing_warning')) for n in part['notes']),1)
        self.assertIn('省略连音编号',part['notes'][0]['timing_warning'])
        warning=part['notes'][0]['timing_warning'];reflow_right_hand_timing(project)
        self.assertEqual(part['notes'][0]['timing_warning'],warning)

if __name__=='__main__':
    runner=unittest.TextTestRunner(verbosity=2)
    result=runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(TupletContinuationControls))
    (HERE/'synthetic-results.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'actual_native_exe':False,'uses_user_pdfs':False},indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
