from pathlib import Path
from copy import deepcopy
import json,sys,unittest
ROOT=Path(__file__).resolve().parent;HOST=ROOT.parent
sys.path.insert(0,str(HOST))
from score_automatic import prepare_automatic_project,export_automatic,check_project
from score_codec import encode,decode
from test_score_realization_r23 import note,mark,project

class AutomaticPracticeTests(unittest.TestCase):
    def test_practice_exports_whole_source_with_grace_overlap_and_unknown_finger(self):
        a=note('a',marks=[mark('trill')]);b=note('b','E4',finger=3);c=note('g','D4',1,None,2,marks=[mark('grace_short',anchor_id='m')]);d=note('m','G4',1,1,None);d['source_fingering_state']='unresolved'
        p=project([a,b,c,d]);before=deepcopy(p);prepared=prepare_automatic_project(p)
        self.assertTrue(prepared['automatic']['ready']);self.assertFalse(prepared['automatic']['recognition_ready'])
        self.assertEqual(prepared['automatic']['attention_notes'],0)
        score=export_automatic(p);self.assertEqual(score['performance']['coverage']['selected_sources'],4)
        self.assertEqual(score['performance']['coverage']['sounded_sources'],4)
        self.assertNotIn('partial_export',score);decode(encode(score))
        for actual,original in zip(p['notes'],before['notes']):
            self.assertEqual({k:actual.get(k) for k in ('pitch','finger','duration_beats','measure_beat')},{k:original.get(k) for k in ('pitch','finger','duration_beats','measure_beat')})

    def test_legacy_project_without_policy_keeps_strict_missing_time(self):
        p=project([note(duration=None)]);p.pop('performance_policy');r=prepare_automatic_project(p)
        self.assertFalse(r['automatic']['ready']);self.assertIsNone(p['notes'][0]['duration_beats'])
        with self.assertRaises(ValueError):export_automatic(p)

    def test_explicit_strict_keeps_overlap_rejection(self):
        p=project([note('a'),note('b','E4')]);p['performance_policy']={'mode':'strict'}
        self.assertFalse(prepare_automatic_project(p)['automatic']['ready'])

    def test_check_returns_only_light_performance_summary_and_states(self):
        p=project([note(marks=[mark('trill'),mark('accent')])]);r=check_project(p)
        self.assertTrue(r['automatic']['ready']);self.assertIn('performance',r)
        self.assertNotIn('audio_events',r['performance']);self.assertNotIn('motion_events',r['performance'])
        kinds={s['kind'] for s in r['notes'][0]['performance_state']['items']};self.assertIn('trill',kinds);self.assertIn('accent',kinds)
        json.dumps(r,allow_nan=False)

    def test_estimate_acknowledgement_does_not_change_artifact_identity(self):
        p=project([note(marks=[mark('trill')])]);a=export_automatic(p)
        p['notes'][0]['performance_override']={'reviewed':True};b=export_automatic(p)
        self.assertEqual(a['title'],b['title']);self.assertEqual(encode(a),encode(b))
        self.assertTrue(b['performance']['estimates'])

    def test_written_override_still_exposes_detected_mark_and_can_switch_back(self):
        n=note(marks=[mark('trill')]);n['performance_override']={'mode':'written','reviewed':True};p=project([n]);r=check_project(p)
        self.assertEqual(r['notes'][0]['performance_state']['kind'],'trill');self.assertFalse(r['notes'][0]['performance_state']['realized'])
        self.assertEqual(len(export_automatic(p)['performance']['audio_events']),1)

    def test_gray_unmarked_notes_preserved_in_audio_and_source_coverage(self):
        p=project([note(),note('gray','E4',1,1,None)]);r=prepare_automatic_project(p)
        self.assertTrue(r['automatic']['ready']);self.assertTrue(r['notes'][1]['unfingered'])
        score=export_automatic(p);self.assertEqual(len(score['performance']['audio_events']),2);self.assertEqual(len(score['notes']),1)
        self.assertIsNone(p['notes'][1]['finger'])

    def test_invalid_pitch_still_blocks_practice_not_skipped(self):
        p=project([note(pitch='broken')]);self.assertFalse(prepare_automatic_project(p)['automatic']['ready'])
        with self.assertRaises(ValueError):export_automatic(p)

    def test_arpeggio_source_duration_gap_is_local_attention_not_global_exception(self):
        p=project([note('a',duration=None,marks=[mark('arpeggio','a')]),note('b','E4',duration=None,finger=2,marks=[mark('arpeggio','a')]),note('next','G4',1,1,3)])
        r=prepare_automatic_project(p);self.assertFalse(r['automatic']['practice_ready'])
        self.assertEqual(set(r['automatic']['attention_note_ids']),{'a','b'})
        self.assertFalse(any('min()' in m for m in r['automatic']['messages']))
        with self.assertRaisesRegex(ValueError,'音值'):export_automatic(p)

    def test_unknown_hand_and_invalid_explicit_finger_are_not_silently_omitted(self):
        p=project([note(),dict(note('unknown','E4'),hand=None)])
        r=prepare_automatic_project(p);self.assertFalse(r['automatic']['ready'])
        self.assertIn('unknown',r['automatic']['attention_note_ids'])
        with self.assertRaises(ValueError):export_automatic(p)
        p=project([note(finger=6)])
        self.assertFalse(prepare_automatic_project(p)['automatic']['ready'])

    def test_source_state_json_is_acyclic_and_original_times_untouched(self):
        p=project([note('a',marks=[mark('arpeggio','c')]),note('b','E4',finger=2,marks=[mark('arpeggio','c')])]);r=check_project(p)
        json.dumps(r,allow_nan=False);self.assertEqual([n['beat'] for n in p['notes']],[0,0])

    def test_group_grace_type_edit_does_not_turn_principal_into_grace(self):
        g=note('g','D4',0,None,2,marks=[mark('grace_unspecified','gr',anchor_id='m')]);m=note('m')
        g['performance_override']={'kind':'grace_long'};m['performance_override']={'kind':'grace_long'}
        p=project([g,m]);score=export_automatic(p)
        self.assertEqual([(e['pitch'],e['duration_ms']) for e in score['performance']['audio_events']],[(62,250),(60,250)])
        self.assertEqual(m['performance_marks'],[])

if __name__=='__main__':unittest.main()
