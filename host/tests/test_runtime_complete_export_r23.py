"""Independent group provenance, tail sustain and selected-hand controls."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
from score_realization import realize_project
from test_score_realization_r23 import note,mark,project

class RuntimeCompleteExportTests(unittest.TestCase):
    def grace(self,kind='grace_short',cluster=False):
        notes=[note('prior','B3',0,1,1)]
        for i in range(2 if cluster else 1):
            notes.append(note('small'+str(i),('D4','E4')[i],1,None,i+2,
                marks=[mark(kind,'detected-grace',anchor_id='main',member_ids=['small0','small1'] if cluster else ['small0'],order=i)]))
        notes.append(note('main','C4',1,1,1))
        return project(notes)

    def test_short_grace_audio_has_actual_detected_group_and_source_pitch(self):
        p=self.grace();before=deepcopy(p);r=realize_project(p);self.assertFalse(r['errors'])
        rows=[e for e in r['audio_events'] if 'small0' in e['source_note_ids']]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['group_id'],'detected-grace')
        self.assertEqual(rows[0]['pitch'],62);self.assertGreater(rows[0]['duration_ms'],0)
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'main' in e['source_note_ids']),500)
        self.assertEqual(p,before)

    def test_cluster_keeps_each_printed_head_in_one_group_and_order(self):
        r=realize_project(self.grace('grace_cluster',True));self.assertFalse(r['errors'])
        rows=[e for e in r['audio_events'] if e['group_id']=='detected-grace']
        self.assertEqual([e['pitch'] for e in rows],[62,64]);self.assertLess(rows[0]['t_ms'],rows[1]['t_ms'])
        self.assertTrue(all(e['duration_ms']>0 for e in rows))

    def test_after_grace_group_does_not_take_the_principal_attack(self):
        r=realize_project(self.grace('grace_after'));self.assertFalse(r['errors'])
        rows=[e for e in r['audio_events'] if e['group_id']=='detected-grace']
        self.assertEqual([e['source_note_ids'] for e in rows],[['small0']])
        self.assertEqual(rows[0]['t_ms']+rows[0]['duration_ms'],1000)
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'main' in e['source_note_ids']),500)

    def pedal(self,tail=True):
        span=dict(id='ped',kind='pedal',source_note_ids=['a','b'],start_note_id='a',end_note_id='b',
            options=dict(release_note_id=None if tail else 'b',release_position='before_anchor',
                endpoint='score_end_estimate' if tail else 'printed_release_anchor',end_estimated=tail))
        return project([note('a','C4',0,1,1),note('b','D4',2,1,2)],performance_spans=[span])

    def test_explicit_null_tail_release_reaches_score_end_and_keeps_motion_short(self):
        p=self.pedal();before=deepcopy(p);r=realize_project(p);self.assertFalse(r['errors'])
        first=next(e for e in r['audio_events'] if 'a' in e['source_note_ids'])
        self.assertEqual(first['duration_ms'],1500);self.assertEqual(r['duration_ms'],1500)
        self.assertEqual(r['motion_events'][0]['duration_ms'],500)
        feat=next(f for f in r['features'] if f['kind']=='pedal')
        self.assertTrue(feat['estimated']);self.assertEqual(feat['parameters']['end_beat'],3)
        self.assertEqual(p,before)

    def test_known_release_still_releases_before_anchor(self):
        r=realize_project(self.pedal(False));self.assertFalse(r['errors'])
        self.assertEqual(r['audio_events'][0]['duration_ms'],1000)

    def test_tail_pedal_includes_real_trailing_rest_budget(self):
        p=self.pedal();p['rests']=[dict(id='silent',hand='right',page=1,system=1,measure=1,beat=3,duration=1)]
        r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual(r['audio_events'][0]['duration_ms'],2000)
        self.assertEqual(len(r['audio_events']),2)

    def test_tail_pedal_uses_same_fermata_warp_as_the_actual_score_end(self):
        p=self.pedal();p['notes'][1]['performance_marks']=[mark('fermata','hold')]
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual(r['audio_events'][0]['duration_ms'],1750);self.assertEqual(r['duration_ms'],1750)

    def test_tail_pedal_written_mode_really_disables_the_span(self):
        p=self.pedal();p['notes'][0]['performance_override']=dict(mode='written')
        r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual(r['audio_events'][0]['duration_ms'],500)

    def test_single_selected_rh_arpeggio_is_explicitly_neutral_not_verified_roll(self):
        p=project([note('a',marks=[mark('arpeggio','wave')]),dict(note('left','C3',finger=2),hand='left')])
        r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual(len(r['audio_events']),1)
        f=next(f for f in r['features'] if f['kind']=='arpeggio')
        self.assertFalse(f['realized']);self.assertEqual(f['parameters']['effect'],'neutral_right_hand_subset')
        self.assertEqual(f['parameters']['selected_heads'],1)

    def test_multiple_rh_arpeggio_really_rolls_instead_of_becoming_neutral(self):
        p=project([note('a',marks=[mark('arpeggio','wave')]),note('b','E4',finger=2,marks=[mark('arpeggio','wave')])])
        r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual(len(r['audio_events']),2)
        self.assertLess(r['audio_events'][0]['t_ms'],r['audio_events'][1]['t_ms'])
        self.assertTrue(next(f for f in r['features'] if f['kind']=='arpeggio')['realized'])

    def test_two_distinct_ornaments_cannot_silently_drop_the_second(self):
        p=project([note(marks=[mark('mordent_upper','one'),mark('trill','two')])])
        r=realize_project(p);self.assertTrue(r['errors']);self.assertTrue(any('多个不同装饰奏法' in e['message'] for e in r['errors']))

    def test_explicit_practice_choice_resolves_conflicting_marks_in_both_directions(self):
        for kind in ('mordent_upper','trill'):
            p=project([note(marks=[mark('mordent_upper','one'),mark('trill','two')])])
            p['notes'][0]['performance_override']=dict(kind=kind,reviewed=True)
            before=deepcopy(p);r=realize_project(p);self.assertFalse(r['errors'])
            self.assertTrue(any(f['kind']==kind and f['realized'] for f in r['features']))
            self.assertGreater(len(r['audio_events']),1);self.assertEqual(p,before)

    def test_same_kind_duplicate_component_is_not_a_conflict_or_double_expansion(self):
        p=project([note(marks=[mark('trill','same'),mark('trill','same')])])
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual(sum(f['kind']=='trill' for f in r['features']),1)

if __name__=='__main__':unittest.main()
