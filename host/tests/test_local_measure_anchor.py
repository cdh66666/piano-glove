"""Local-vs-global anchor semantics; independent synthetic scores only."""
import unittest
from copy import deepcopy
from pathlib import Path
import tempfile
from score_timing import reflow_right_hand_timing
from score_automatic import check_project, export_automatic
from score_codec import encode,decode
from workspace_store import WorkspaceStore
from test_score_timing_r11 import event,score

def set_local(n,beat,local):
    n.update(beat=beat,measure_beat=local,manual_fields=['beat'],timing_anchor_scope='measure')

class MeasureAnchorTests(unittest.TestCase):
    def test_first_note_local_edit_does_not_move_measure_start(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25),event('c',60,.5,.25)],length=4)
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[.25,.5,.75])
        self.assertEqual(p['notes'][0]['measure_start_beat'],0)
        self.assertEqual(p['notes'][0]['measure_beat'],.25)
        saved=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,saved)

    def test_old_unmarked_global_anchor_retains_original_absolute_semantics(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25)],length=4)
        reflow_right_hand_timing(p);p['notes'][0].update(beat=.25,manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][0]['measure_start_beat'],.25)
        self.assertEqual(p['notes'][0]['measure_beat'],0)
        self.assertEqual([n['beat'] for n in p['notes']],[.25,.5])

    def test_local_anchor_moves_with_prior_measure_and_follows_itself(self):
        p=score([event('a',20,0,1),event('b',40,1,1),
                 event('c',20,0,.25,measure=2),event('d',40,.25,.25,measure=2),
                 event('e',20,0,1,measure=3)],length=4)
        reflow_right_hand_timing(p);set_local(p['notes'][2],4.25,.25);reflow_right_hand_timing(p)
        self.assertEqual((p['notes'][2]['measure_start_beat'],p['notes'][2]['measure_beat'],p['notes'][3]['beat']),(4,.25,4.5))
        p['notes'][0].update(duration_beats=2,manual_fields=['duration_beats']);reflow_right_hand_timing(p)
        self.assertEqual((p['notes'][2]['measure_start_beat'],p['notes'][2]['measure_beat'],p['notes'][2]['beat'],p['notes'][3]['beat']),(5,.25,5.25,5.5))
        self.assertEqual(p['notes'][4]['measure_start_beat'],9.25)

    def test_later_global_anchor_remains_absolute_when_prior_local_changes(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25),event('c',60,.5,.25)],length=4)
        reflow_right_hand_timing(p);p['notes'][2].update(beat=2,manual_fields=['beat']);reflow_right_hand_timing(p)
        set_local(p['notes'][0],.25,.25);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[.25,.5,2])

    def test_later_local_anchor_is_a_fixed_position_not_a_live_previous_note_link(self):
        p=score([event('a',20,0,1),event('b',40,1,1),event('c',60,2,1)],length=4)
        reflow_right_hand_timing(p);set_local(p['notes'][1],1,1);reflow_right_hand_timing(p)
        p['notes'][0].update(duration_beats=2,manual_fields=['duration_beats']);reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][1]['measure_beat'],1)
        self.assertEqual(p['notes'][1]['beat'],1)

    def test_later_measure_global_anchor_stays_absolute_when_earlier_bar_changes(self):
        p=score([event('a',20,0,1),event('b',40,1,1),
                 event('c',20,0,.25,measure=2),event('d',40,.25,.25,measure=2)],length=4)
        reflow_right_hand_timing(p);p['notes'][2].update(beat=8,manual_fields=['beat']);reflow_right_hand_timing(p)
        p['notes'][0].update(duration_beats=2,manual_fields=['duration_beats']);reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][2]['beat'],8)
        self.assertEqual(p['notes'][2]['measure_start_beat'],8)

    def test_conflicting_same_chord_local_inputs_are_preserved_with_warning(self):
        stem=[26,0,40]
        p=score([event('a',20,0,.25,rhythm_evidence=dict(stem=stem)),
                 event('b',29,0,.25,rhythm_evidence=dict(stem=stem)),event('c',50,.25,.25)],length=4)
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25);set_local(p['notes'][1],.5,.5)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes'][:2]],[.25,.5])
        self.assertEqual([n['measure_beat'] for n in p['notes'][:2]],[.25,.5])
        self.assertTrue(all('手动起拍不同' in n['timing_warning'] for n in p['notes'][:2]))
        saved=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,saved)

    def test_local_edit_preserves_current_repeat_start_and_maps_later_end(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25),event('c',20,0,1,measure=2)],length=4)
        p['repeat_markers']=[dict(page=1,system=1,boundary=0,kind='start',written_beat=0),
                             dict(page=1,system=1,boundary=2,kind='end',written_beat=8)]
        p['repeat_sections']=[dict(start_beat=0,end_beat=8,count=2,marker_indices=[0,1])]
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25);reflow_right_hand_timing(p)
        self.assertEqual((p['repeat_sections'][0]['start_beat'],p['repeat_sections'][0]['end_beat']),(0,8.25))

    def test_local_confirmation_keeps_inherited_unknown_previous_measure(self):
        p=score([event('a',20,None,1),event('b',40,None,1),event('c',20,0,1,measure=2),event('d',40,1,1,measure=2)])
        p['staves'][0]['measures'][1].update(timing_resolved=True,length_beats=4)
        reflow_right_hand_timing(p);self.assertTrue(p['notes'][0]['timing_warning'])
        self.assertTrue(p['notes'][2]['timing_estimated'])
        start=p['notes'][2]['measure_start_beat'];set_local(p['notes'][2],start+.25,.25)
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][2]['measure_start_beat'],start)
        self.assertEqual(p['notes'][2]['measure_beat'],.25)
        self.assertTrue(p['notes'][0]['timing_warning'])
        self.assertTrue(p['notes'][2]['timing_estimated'])
        self.assertEqual(p['notes'][2]['timing_source_id'],'a')

    def test_same_measure_anchor_resolves_local_but_not_missing_duration(self):
        p=score([event('a',20,None,None),event('b',40,None,1),event('c',60,None,1)],length=4)
        reflow_right_hand_timing(p);self.assertTrue(p['notes'][0]['timing_warning'])
        set_local(p['notes'][1],1,1);reflow_right_hand_timing(p)
        self.assertTrue(p['notes'][0]['timing_warning'])
        self.assertFalse(p['notes'][1]['timing_estimated'])
        self.assertEqual([n['beat'] for n in p['notes']],[0,1,2])

    def test_same_local_confirmation_does_not_clear_unknown_duration(self):
        p=score([event('a',20,None,None),event('b',40,None,1)])
        reflow_right_hand_timing(p);set_local(p['notes'][0],0,0);reflow_right_hand_timing(p)
        self.assertIsNone(p['notes'][0]['duration_beats']);self.assertTrue(p['notes'][0]['timing_warning'])

    def test_local_same_value_does_not_create_quantization_drift(self):
        p=score([event(str(i),20*i+20,None,1/3) for i in range(6)],length=4)
        reflow_right_hand_timing(p);before=[n['beat'] for n in p['notes']]
        set_local(p['notes'][1],p['notes'][1]['beat'],p['notes'][1]['measure_beat'])
        reflow_right_hand_timing(p);self.assertEqual([n['beat'] for n in p['notes']],before)

    def test_validation_response_and_workspace_persist_scope(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25)],length=4)
        p.update(name='合成测试',source_sha256='a'*64,selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25)
        check=check_project(p);n=next(x for x in check['notes'] if x['id']=='a')
        self.assertEqual((n['timing_anchor_scope'],n['measure_start_beat'],n['measure_beat'],n['beat']),('measure',0,.25,.25))
        with tempfile.TemporaryDirectory(prefix='measure-anchor-synthetic-') as tmp:
            store=WorkspaceStore(Path(tmp));store.save({'project':p,'ui':{}});saved=store.review('a'*64)
            self.assertEqual((saved['notes'][0]['timing_anchor_scope'],saved['notes'][0]['measure_beat']),('measure',.25))

    def test_actual_pgl_export_reflects_local_timing_but_is_not_editable_project(self):
        p=score([event('a',20,0,.25,pitch='C4',finger=1),event('b',40,.25,.25,pitch='D4',finger=2)],length=4)
        p.update(name='合成测试',selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25)
        result=export_automatic(p);roundtrip=decode(encode(result))
        self.assertEqual([n['t_ms'] for n in roundtrip['notes']],[125,250])

    def test_explicit_local_edit_into_known_tail_rest_warns_source_and_followers(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25),event('next',20,0,1,measure=2)],
                length=4,rests=[event('tail',60,.5,3.5)])
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[.25,.5,4.25])
        self.assertEqual((p['rests'][0]['beat'],p['rests'][0]['duration_beats']),(.75,3.5))
        self.assertIn('本小节超过4拍',p['notes'][0]['timing_warning'])
        self.assertIn('末尾休止',p['notes'][0]['timing_warning'])
        self.assertEqual(p['notes'][0]['timing_source_id'],'a')
        self.assertTrue(p['notes'][2]['timing_estimated'])
        self.assertEqual(p['notes'][2]['timing_source_id'],'a')
        self.assertIsNone(p['notes'][2]['timing_warning'])
        check=check_project(p)
        self.assertIn('本小节超过4拍',next(n for n in check['notes'] if n['id']=='a')['timing_warning'])
        set_local(p['notes'][0],0,0);reflow_right_hand_timing(p)
        self.assertIsNone(p['notes'][0]['timing_warning'])
        self.assertEqual(p['notes'][2]['beat'],4)

    def test_known_full_bar_without_tail_rest_also_warns_after_local_edit(self):
        p=score([event('a',20,0,1),event('b',40,1,1),event('c',60,2,1),event('d',80,3,1)],length=4)
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25);reflow_right_hand_timing(p)
        self.assertIn('本小节超过4拍',p['notes'][0]['timing_warning'])
        self.assertIn('末尾音长',p['notes'][0]['timing_warning'])

    def test_no_warning_for_full_original_or_old_absolute_anchor(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25),event('next',20,0,1,measure=2)],
                length=4,rests=[event('tail',60,.5,3.5)])
        reflow_right_hand_timing(p);before=deepcopy(p);reflow_right_hand_timing(p)
        self.assertEqual(p,before);self.assertIsNone(p['notes'][0]['timing_warning'])
        p['notes'][0].update(beat=.25,manual_fields=['beat']);reflow_right_hand_timing(p)
        self.assertIsNone(p['notes'][0]['timing_warning'])

    def test_pickup_and_originally_overfull_measures_do_not_gain_new_warning(self):
        pickup=score([event('a',20,0,.25),event('next',20,0,1,measure=2)],
                     rests=[event('tail',60,.25,3.5)])
        reflow_right_hand_timing(pickup);set_local(pickup['notes'][0],.5,.5);reflow_right_hand_timing(pickup)
        self.assertNotIn('本小节超过',pickup['notes'][0]['timing_warning'] or '')
        preexisting=score([event('a',20,0,.25),event('b',40,.25,.25),event('next',20,0,1,measure=2)],
                          length=4,rests=[event('tail',60,.5,3.75)])
        reflow_right_hand_timing(preexisting);set_local(preexisting['notes'][0],.25,.25);reflow_right_hand_timing(preexisting)
        self.assertNotIn('本小节超过',preexisting['notes'][0]['timing_warning'] or '')

    def test_tie_and_multiple_voices_are_not_falsely_classified_as_overfull(self):
        tied=score([event('a',20,0,.25,tie_to='next'),event('b',40,.25,.25),event('next',20,0,1,measure=2)],
                   length=4,rests=[event('tail',60,.5,3.5)])
        reflow_right_hand_timing(tied);set_local(tied['notes'][0],.25,.25);reflow_right_hand_timing(tied)
        self.assertNotIn('本小节超过',tied['notes'][0]['timing_warning'] or '')
        voices=score([event('a',20,0,.25,voice='upper'),event('b',40,.25,.25,voice='lower'),event('next',20,0,1,measure=2)],
                     length=4,rests=[event('tail',60,.5,3.5,voice='upper')])
        reflow_right_hand_timing(voices);set_local(voices['notes'][0],.25,.25);reflow_right_hand_timing(voices)
        self.assertNotIn('本小节超过',voices['notes'][0]['timing_warning'] or '')

    def test_unlabelled_overlapping_voice_is_not_assumed_single_layer(self):
        p=score([event('a',20,0,2),event('b',40,.5,.5),event('next',20,0,1,measure=2)],
                length=4,rests=[event('tail',60,1,3)])
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25);reflow_right_hand_timing(p)
        self.assertNotIn('本小节超过',p['notes'][0]['timing_warning'] or '')

    def test_duration_cleared_after_capture_remains_unknown_not_proven_overfull(self):
        p=score([event('a',20,0,.25),event('b',40,.25,.25),event('next',20,0,1,measure=2)],
                length=4,rests=[event('tail',60,.5,3.5)])
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25)
        p['notes'][1].update(duration_beats=None,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertNotIn('本小节超过',p['notes'][0]['timing_warning'] or '')
        self.assertTrue(p['notes'][1]['timing_warning'])

    def test_manual_duration_increase_beyond_known_meter_warns_edited_note(self):
        p=score([event('a',20,0,1),event('next',20,0,1,measure=2)],length=4,
                rests=[event('tail',40,1,3)])
        reflow_right_hand_timing(p)
        p['notes'][0].update(duration_beats=1.5,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][0]['duration_beats'],1.5)
        self.assertEqual((p['rests'][0]['beat'],p['rests'][0]['duration_beats']),(1.5,3))
        self.assertEqual(p['notes'][1]['beat'],4.5)
        self.assertIn('本小节超过4拍',p['notes'][0]['timing_warning'])
        self.assertIn('音长',p['notes'][0]['timing_warning'])
        self.assertEqual((p['notes'][1]['timing_estimated'],p['notes'][1]['timing_source_id']),(True,'a'))
        check=check_project(p)
        self.assertIn('本小节超过4拍',next(n for n in check['notes'] if n['id']=='a')['timing_warning'])
        saved=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,saved)

    def test_duration_source_is_highlighted_even_with_existing_local_edit(self):
        p=score([event('a',20,0,1),event('b',40,1,1),event('next',20,0,1,measure=2)],
                length=4,rests=[event('tail',60,2,2)])
        reflow_right_hand_timing(p);set_local(p['notes'][0],.25,.25)
        p['notes'][1].update(duration_beats=1.5,manual_fields=['duration_beats']);reflow_right_hand_timing(p)
        self.assertIn('本小节超过4拍',p['notes'][1]['timing_warning'])
        self.assertIn('音长',p['notes'][1]['timing_warning'])
        self.assertEqual(p['notes'][2]['timing_source_id'],'b')

    def test_shortened_equal_or_cleared_duration_is_not_new_overfull_warning(self):
        for edited in (.5,1,None):
            p=score([event('a',20,0,1),event('next',20,0,1,measure=2)],length=4,
                    rests=[event('tail',40,1,3)])
            reflow_right_hand_timing(p);p['notes'][0].update(duration_beats=edited,manual_fields=['duration_beats'])
            reflow_right_hand_timing(p)
            self.assertNotIn('本小节超过',p['notes'][0]['timing_warning'] or '')
            if edited is None:self.assertTrue(p['notes'][0]['timing_warning'])

    def test_manual_duration_does_not_newly_warn_preexisting_overflow_or_tie(self):
        for tied in (False,True):
            p=score([event('a',20,0,1,**({'tie_to':'next'} if tied else {})),event('next',20,0,1,measure=2)],
                    length=4,rests=[event('tail',40,1,3 if tied else 3.25)])
            reflow_right_hand_timing(p);p['notes'][0].update(duration_beats=1.5,manual_fields=['duration_beats'])
            reflow_right_hand_timing(p)
            self.assertNotIn('本小节超过',p['notes'][0]['timing_warning'] or '')

    def test_manual_duration_does_not_guess_pickup_or_unlabelled_overlapping_voices(self):
        pickup=score([event('a',20,0,.25),event('next',20,0,1,measure=2)],
                     rests=[event('tail',40,.25,3.5)])
        reflow_right_hand_timing(pickup);pickup['notes'][0].update(duration_beats=.75,manual_fields=['duration_beats'])
        reflow_right_hand_timing(pickup)
        self.assertNotIn('本小节超过',pickup['notes'][0]['timing_warning'] or '')
        overlapping=score([event('a',20,0,2),event('b',40,.5,.5),event('next',20,0,1,measure=2)],
                          length=4,rests=[event('tail',60,1,3)])
        reflow_right_hand_timing(overlapping);overlapping['notes'][0].update(duration_beats=2.5,manual_fields=['duration_beats'])
        reflow_right_hand_timing(overlapping)
        self.assertNotIn('本小节超过',overlapping['notes'][0]['timing_warning'] or '')

    def test_unmarked_duration_update_does_not_create_new_overfull_warning(self):
        p=score([event('a',20,0,1),event('next',20,0,1,measure=2)],length=4,
                rests=[event('tail',40,1,3)])
        reflow_right_hand_timing(p);p['notes'][0]['duration_beats']=1.5;reflow_right_hand_timing(p)
        self.assertNotIn('本小节超过',p['notes'][0]['timing_warning'] or '')

if __name__=='__main__':unittest.main()
