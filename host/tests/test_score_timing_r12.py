"""Independent synthetic musical structures for right-hand reflow."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_timing import reflow_right_hand_timing
from score_automatic import prepare_automatic_project,export_automatic
from score_codec import decode,encode
from test_score_timing_r11 import event,score


class RightHandStructureTests(unittest.TestCase):
    def test_shared_stem_groups_laterally_displaced_chord_heads(self):
        stem=[26,0,40]
        a=event('a',20,rhythm_evidence=dict(stem=stem),finger=1)
        b=event('b',29,rhythm_evidence=dict(stem=stem),finger=2,pitch='D4')
        c=event('c',50,rhythm_evidence=dict(stem=[56,0,40]),finger=3,pitch='E4')
        p=score([a,b,c]);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,0,1])
        self.assertEqual(p['written_duration_beats'],2)
        p['notes'][0].update(beat=2,manual_fields=['beat']);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[2,2,3])

    def test_manual_conflicting_chord_beats_are_preserved_and_flagged(self):
        stem=[26,0,40]
        p=score([event('a',20,0,rhythm_evidence=dict(stem=stem)),
                 event('b',29,0,rhythm_evidence=dict(stem=stem)),event('c',50,1)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][0].update(beat=2,manual_fields=['beat'])
        p['notes'][1].update(beat=3,manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[2,3,3])
        self.assertIn('手动起拍不同',p['notes'][0]['timing_warning'])
        self.assertIn('手动起拍不同',p['notes'][1]['timing_warning'])
        self.assertEqual(p['notes'][0]['manual_fields'],['beat'])
        self.assertEqual(p['notes'][1]['manual_fields'],['beat'])

    def test_cleared_manual_beat_and_duration_remain_unset(self):
        p=score([event('a',20,0),event('b',40,1),event('c',60,2)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][1].update(beat=None,duration_beats=None,manual_fields=['beat','duration_beats'])
        reflow_right_hand_timing(p)
        self.assertIsNone(p['notes'][1]['beat'])
        self.assertIsNone(p['notes'][1]['duration_beats'])
        self.assertEqual(p['notes'][2]['beat'],2)
        self.assertTrue(p['notes'][1]['timing_warning'])

    def test_shared_stem_accepts_an_interleaved_distinct_voice(self):
        stem=[26,0,40]
        a=event('a',20,0,2,voice='down',rhythm_evidence=dict(stem=stem))
        b=event('b',29,0,2,voice='down',rhythm_evidence=dict(stem=stem))
        c=event('c',25,0,1,voice='up',rhythm_evidence=dict(stem=[30,0,40]))
        d=event('d',50,1,1,voice='up',rhythm_evidence=dict(stem=[56,0,40]))
        p=score([a,b,c,d],length=4);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,0,0,1])

    def test_conflicting_independent_positions_on_shared_stem_are_visible(self):
        stem=[26,0,40]
        p=score([event('a',20,1,rhythm_evidence=dict(stem=stem)),
                 event('b',29,2,rhythm_evidence=dict(stem=stem))],length=4)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[1,1])
        self.assertTrue(any(n['timing_warning'] for n in p['notes']))

    def test_grace_has_no_automatic_meter_duration_and_follows_main_anchor(self):
        p=score([event('a',20,0),
                 event('g',30,None,None,grace_kind='slashed',main_anchor_id='b',main_anchor_measure_beat=1),
                 event('b',40,1),event('c',60,2),event('d',80,3)],length=4)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1,1,2,3])
        self.assertEqual(p['written_duration_beats'],4)
        self.assertIsNone(p['notes'][1]['duration_beats'])
        self.assertEqual(p['notes'][1]['main_anchor_beat'],p['notes'][2]['beat'])
        self.assertEqual(p['right_hand_timing']['warning_note_ids'],['g'])
        self.assertIn('装饰音',p['notes'][1]['timing_warning'])
        self.assertIsNone(p['notes'][2]['timing_warning'])
        self.assertFalse(p['notes'][2]['timing_estimated'])
        self.assertFalse(p['notes'][1]['timing_anchor_inferred'])
        p['notes'][2].update(beat=1.25,manual_fields=['beat']);reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1.25,1.25,2.25,3.25])
        self.assertEqual(p['notes'][1]['main_anchor_beat'],1.25)
        prior=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,prior)

    def test_recognized_grace_infers_a_unique_nearby_principal(self):
        p=score([event('a',20,0),event('g',30,None,None,grace_kind='slashed'),
                 event('b',40,1),event('c',60,2),event('d',80,3)],length=4)
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][1]['timing_main_anchor_id'],'b')
        self.assertTrue(p['notes'][1]['timing_anchor_inferred'])
        self.assertEqual(p['notes'][1]['main_anchor_beat'],1)
        self.assertEqual(p['written_duration_beats'],4)

    def test_grace_with_two_conflicting_nearby_principals_stays_ambiguous(self):
        p=score([event('a',20,0),event('g',30,None,None,grace_kind='slashed'),
                 event('b',40,1,voice='up'),event('c',41,2,voice='down')],length=4)
        reflow_right_hand_timing(p)
        self.assertNotIn('timing_main_anchor_id',p['notes'][1])
        self.assertTrue(p['notes'][1]['timing_warning'])

    def test_normal_short_note_is_never_inferred_to_be_a_grace(self):
        p=score([event('a',20,0),event('short',30,None,.125,
                        issues=['small_notated_note_requires_review']),
                 event('b',40,None),event('c',60,None),event('d',80,None)],length=4)
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][1]['duration_beats'],.125)
        self.assertEqual(p['notes'][2]['beat'],1.125)
        self.assertNotIn('timing_main_anchor_id',p['notes'][1])

    def test_user_supplied_grace_duration_moves_main_but_stays_an_attack(self):
        p=score([event('a',20,0),
                 event('g',30,None,None,grace_kind='slashed',main_anchor_id='b'),
                 event('b',40,1),event('c',60,2),event('d',80,3)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][1].update(duration_beats=.25,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1,1.25,2.25,3.25])
        self.assertEqual(p['notes'][1]['main_anchor_beat'],1.25)

    def test_unfingered_grace_warns_but_leaves_principal_export_playable(self):
        p=score([event('a',20,0,finger=1),
                 event('g',30,None,None,grace_kind='slashed',main_anchor_id='b',
                       finger=None,source_fingering_state='unmarked'),
                 event('b',40,1,finger=2),event('c',60,2,finger=3),event('d',80,3,finger=4)],length=4)
        p.update(name='合成倚音',selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
        prepare_automatic_project(p)
        self.assertTrue(p['automatic']['ready'])
        self.assertEqual(p['automatic']['timing_warning_note_ids'],['g'])
        self.assertIsNone(p['notes'][1]['duration_beats'])
        result=decode(encode(export_automatic(p)))
        self.assertEqual([n['t_ms'] for n in result['notes']],[0,500,1000,1500])
        self.assertEqual(result['duration_ms'],2000)
        p['notes'][1].update(finger=5,manual_fields=['finger'])
        prepare_automatic_project(p)
        self.assertFalse(p['automatic']['ready'])
        self.assertIn('选择音值',p['notes'][1]['automatic_reasons'])

    def test_two_partial_measure_tremolos_occupy_one_span_each_and_export(self):
        def t(ident,x,span,side,group,pitch,finger):
            return event(ident,x,None,span,tremolo_group=group,tremolo_side=side,
                         tremolo_span_beats=span,tremolo_step_beats=.125,pitch=pitch,finger=finger)
        p=score([t('a',20,2,0,'t0','C4',1),t('b',40,2,1,'t0','G4',5),
                 t('c',60,1,0,'t1','D4',2),t('d',80,1,1,'t1','F4',4),
                 event('e',100,None,1,pitch='E4',finger=3),
                 event('f',20,0,1,measure=2,pitch='F4',finger=4)],length=None,
                rests=[event('rest',40,1,3,measure=2)])
        p['staves'][0]['measures'][1].update(timing_resolved=True,length_beats=4)
        p.update(name='独立震音合成谱',selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
        prepare_automatic_project(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,0,2,2,3,4])
        result=decode(encode(export_automatic(p)))
        self.assertEqual(len(result['notes']),25+1)
        self.assertEqual(result['notes'][0]['t_ms'],0)
        self.assertEqual(result['notes'][16]['t_ms'],1000)
        self.assertEqual(result['notes'][24]['t_ms'],1500)
        self.assertEqual(result['notes'][25]['t_ms'],2000)

    def test_incomplete_tremolo_does_not_silently_collapse(self):
        p=score([event('a',20,None,2,tremolo_group='t',tremolo_side=0,
                       tremolo_span_beats=2,tremolo_step_beats=.125),
                 event('b',40,None,2,tremolo_group='t',tremolo_side=0,
                       tremolo_span_beats=2,tremolo_step_beats=.125)])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,2])

    def test_r11_basis_upgrade_preserves_original_evidence_and_manual_edits(self):
        p=score([event('a',20,0),event('b',40,1)],length=4)
        reflow_right_hand_timing(p)
        p['right_hand_timing']['version']=1
        p['notes'][0].update(beat=2,manual_fields=['beat'])
        # The live beat/measure fields are already derived and must not become
        # the underlying source after loading an older workspace.
        p['notes'][1].update(beat=5,measure_beat=5)
        reflow_right_hand_timing(p)
        self.assertEqual(p['right_hand_timing']['version'],2)
        self.assertEqual([n['beat'] for n in p['notes']],[2,3])

    def test_r11_basis_upgrade_accepts_new_tremolo_without_losing_manual_values(self):
        p=score([event('a',20,0,2),event('b',40,2,2),event('c',60,0,1,measure=2)],length=4)
        reflow_right_hand_timing(p)
        p['right_hand_timing']['version']=1
        p['notes'][0].update(beat=3,duration_beats=2,manual_fields=['beat','duration_beats'])
        for side,n in enumerate(p['notes'][:2]):
            n.update(tremolo_group='new',tremolo_side=side,tremolo_span_beats=2,tremolo_step_beats=.125)
        reflow_right_hand_timing(p)
        self.assertEqual(p['right_hand_timing']['version'],2)
        self.assertEqual([n['beat'] for n in p['notes']],[3,3,7])
        self.assertEqual(p['notes'][0]['duration_beats'],2)
        self.assertEqual(p['notes'][0]['manual_fields'],['beat','duration_beats'])

    def test_manual_arrangement_with_staff_geometry_is_not_reinterpreted(self):
        stem=[26,0,40]
        p=score([event('a',20,0,rhythm_evidence=dict(stem=stem),beat=0),
                 event('b',29,2,rhythm_evidence=dict(stem=stem),beat=2)],length=4)
        p.update(source_kind='manual',recognition_performed=False)
        before=deepcopy(p)
        reflow_right_hand_timing(p)
        self.assertEqual(p,before)

    def test_source_identity_and_uniform_geometry_scale_do_not_change_rhythm(self):
        stem=[26,0,40]
        p=score([event('a',20,rhythm_evidence=dict(stem=stem)),
                 event('b',29,rhythm_evidence=dict(stem=stem)),event('c',50)],length=None)
        variant=deepcopy(p)
        p.update(name='one',source_sha256='a'*64)
        variant.update(name='another',source_sha256='b'*64)
        for i,n in enumerate(variant['notes']):
            n['id']='renamed-'+str(i)
            n['origin']=[v*2.5+7 for v in n['origin']]
            if n.get('rhythm_evidence',{}).get('stem'):
                n['rhythm_evidence']['stem']=[v*2.5+7 for v in n['rhythm_evidence']['stem']]
        variant['staves'][0]['lines']=[v*2.5+7 for v in variant['staves'][0]['lines']]
        reflow_right_hand_timing(p);reflow_right_hand_timing(variant)
        self.assertEqual([n['beat'] for n in p['notes']],[n['beat'] for n in variant['notes']])

    def test_pickup_uses_right_hand_rest_and_keeps_uncertainty_visible(self):
        p=score([event('a',30,None,.5),event('b',50,None,.5),event('c',70,None,.5)],
                rests=[event('rest',10,None,.5)])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[.5,1,1.5])
        self.assertEqual(p['written_duration_beats'],2)
        self.assertEqual(p['right_hand_timing']['warning_notes'],1)


if __name__=='__main__':unittest.main()
