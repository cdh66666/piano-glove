"""Independent abstract note/rest cases; no PDF, gold, title or score coordinates."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
from score_timing import reflow_right_hand_timing


def attack(identity, x, duration=1, local=None, **extra):
    n=dict(id=identity,page=1,system=1,measure=1,staff='upper',hand='right',
           pitch='C4',finger=1,origin=[x,40],duration=duration,
           duration_beats=duration,measure_beat=local,beat=None)
    n.update(extra)
    return n


def fixture(notes,rests=(),meter=4):
    return dict(notes=notes,rests=list(rests),staves=[dict(id='upper',hand='right',page=1,system=1,
        lines=[10,22,34,46,58],meter_beats=meter,
        measures=[dict(measure=1,timing_resolved=True,length_beats=meter,meter_beats=meter)])])


class GeneralOrnamentMeterTests(unittest.TestCase):
    def test_stale_grace_local_never_advances_principal_cursor(self):
        p=fixture([attack('start',11),attack('ornament',33,None,local=17,
                   grace_kind='slashed',main_anchor_id='main'),attack('main',55),attack('tail',77,2)])
        reflow_right_hand_timing(p)
        self.assertEqual([n['measure_beat'] for n in p['notes']],[0,1,1,2])
        self.assertEqual(p['written_duration_beats'],4)
        self.assertIsNone(p['notes'][1]['duration_beats'])
        self.assertTrue(p['notes'][1]['timing_warning'])

    def test_recognizer_nominal_flags_do_not_create_measured_time(self):
        p=fixture([attack('start',11),attack('ornament',33,.25,local=17,
                   grace_kind='unmeasured_prefix',main_anchor_id='main'),attack('main',55),attack('tail',77,2)])
        reflow_right_hand_timing(p)
        self.assertEqual([p['notes'][i]['beat'] for i in [0,2,3]],[0,1,2])
        self.assertEqual(p['notes'][1]['duration_beats'],.25)  # not overwritten by this timing layer
        self.assertTrue(p['notes'][1]['timing_warning'])

    def test_explicit_unmeasured_kind_uses_the_same_contract(self):
        p=fixture([attack('ornament',11,None,grace_kind='unmeasured',main_anchor_id='main'),
                   attack('main',33,4)])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,0])
        self.assertEqual(p['written_duration_beats'],4)

    def test_small_normal_note_still_occupies_its_written_value(self):
        p=fixture([attack('start',11),attack('short',33,.125,issues=['small_notated_note_requires_review']),
                   attack('main',55),attack('tail',77,1.875)])
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][2]['beat'],1.125)
        self.assertNotIn('timing_main_anchor_id',p['notes'][1])

    def test_cue_label_does_not_silently_become_an_ornament(self):
        p=fixture([attack('cue',11,.25,grace_kind='cue'),attack('main',33,3.75)])
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][1]['beat'],.25)

    def test_explicit_duration_edit_still_moves_main_and_successors(self):
        p=fixture([attack('start',11),attack('ornament',33,None,grace_kind='slashed',main_anchor_id='main'),
                   attack('main',55),attack('tail',77,2)])
        reflow_right_hand_timing(p)
        p['notes'][1].update(duration_beats=.125,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1,1.125,2.125])
        self.assertEqual(p['notes'][1]['main_anchor_beat'],1.125)

    def test_unanchored_ornament_stays_uncertain_without_meter_occupancy(self):
        p=fixture([attack('start',11),attack('ornament',33,None,local=23,grace_kind='slashed'),
                   attack('main',155),attack('tail',177,2)])
        reflow_right_hand_timing(p)
        self.assertEqual([p['notes'][i]['beat'] for i in [0,2,3]],[0,1,2])
        self.assertTrue(p['notes'][1]['timing_warning'])
        self.assertNotIn('timing_main_anchor_id',p['notes'][1])

    def test_recapture_old_basis_drops_stale_grace_time_and_keeps_manual_main(self):
        prod=Path(__file__).resolve().parent/'fixtures/score_timing_before_r21.py'
        spec=importlib.util.spec_from_file_location('prior_timing_for_test',prod)
        prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
        p=fixture([attack('start',11),attack('ornament',33,None,local=17,
                   grace_kind='slashed',main_anchor_id='main'),attack('main',55),attack('tail',77,2)])
        prior.reflow_right_hand_timing(p)
        self.assertGreater(p['notes'][2]['beat'],1)
        p['notes'][0].update(beat=3,manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[3,4,4,5])
        self.assertEqual(p['notes'][0]['manual_fields'],['beat'])

    def test_fresh_reflow_is_idempotent(self):
        p=fixture([attack('start',11),attack('ornament',33,None,local=17,
                   grace_kind='slashed',main_anchor_id='main'),attack('main',55),attack('tail',77,2)])
        reflow_right_hand_timing(p);before=deepcopy(p);reflow_right_hand_timing(p)
        self.assertEqual(p,before)

    def test_identity_translation_and_scale_do_not_change_timing(self):
        p=fixture([attack('start',11),attack('ornament',33,None,local=17,
                   grace_kind='slashed',main_anchor_id='main'),attack('main',55),attack('tail',77,2)])
        q=deepcopy(p);q.update(name='unrelated name',source_sha256='0'*64)
        for n in q['notes']:
            n['id']='other-'+n['id'];n['origin']=[v*1.7+19 for v in n['origin']]
            if n.get('main_anchor_id'):n['main_anchor_id']='other-'+n['main_anchor_id']
        q['staves'][0]['lines']=[v*1.7+19 for v in q['staves'][0]['lines']]
        reflow_right_hand_timing(p);reflow_right_hand_timing(q)
        self.assertEqual([n['beat'] for n in p['notes']],[n['beat'] for n in q['notes']])

    def test_multiple_confirmed_prefix_heads_share_main_anchor(self):
        p=fixture([attack('start',11),attack('ornament-a',28,None,local=11,grace_kind='unmeasured_prefix',main_anchor_id='main'),
                   attack('ornament-b',36,None,local=12,grace_kind='unmeasured_prefix',main_anchor_id='main'),
                   attack('main',55),attack('tail',77,2)])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1,1,1,2])
        self.assertIsNone(p['notes'][1]['duration_beats']);self.assertIsNone(p['notes'][2]['duration_beats'])

    def test_recognized_tuplet_rest_and_notes_keep_supplied_ratio(self):
        rest=attack('rest',11,1/6)
        p=fixture([attack('triplet-a',33,1/6),attack('triplet-b',55,1/6),attack('tail',77,1.5)],
                  rests=[rest],meter=2)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[.166667,.333333,.5])
        self.assertEqual([n['duration_beats'] for n in p['notes']],[1/6,1/6,1.5])

    def test_missing_tuplet_evidence_is_not_invented_from_total(self):
        p=fixture([attack('a',11,.25),attack('b',33,.25),attack('tail',55,1.5)],meter=2)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,.25,.5])
        self.assertEqual(p['notes'][0]['duration_beats'],.25)

    def test_known_parallel_voice_onsets_are_preserved(self):
        p=fixture([attack('sustain',11,4,0,voice='lower'),attack('ornament',24,None,17,
                   grace_kind='slashed',main_anchor_id='main',voice='upper'),
                   attack('main',33,1,0,voice='upper'),attack('next',55,3,1,voice='upper')])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,0,0,1])


if __name__=='__main__':unittest.main()
