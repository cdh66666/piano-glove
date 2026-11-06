"""Independent repeat/rest/clock and editability checks; no customer fixture values."""
from pathlib import Path
from copy import deepcopy
import importlib.util,json,sys,unittest

ROOT=Path(__file__).resolve().parent;HOST=ROOT.parent
sys.path.insert(0,str(HOST))
from score_realization import realize_project,compile_practice_score
from score_codec import encode,decode
import boundary_fixtures_r23 as fixtures
spec=importlib.util.spec_from_file_location('before_boundary_fix',ROOT/'fixtures/score_realization_before_boundary_r23.py')
before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)

class BoundaryFix(unittest.TestCase):
    def run_source(self,p,allow_errors=False):
        original=deepcopy(p);result=realize_project(p);self.assertEqual(p,original)
        if not allow_errors:self.assertFalse(result['errors'])
        return result

    def test_repeat_boundary_preserves_both_actual_prebeat_attacks_and_occurrences(self):
        p=fixtures.grace(1,1);old=before.realize_project(p);result=self.run_source(p)
        self.assertEqual(sum(e['source_note_ids']==['small'] for e in old['audio_events']),1)
        small=[e for e in result['audio_events'] if e['source_note_ids']==['small']]
        main=[e for e in result['audio_events'] if e['source_note_ids']==['main']]
        self.assertEqual([e['t_ms'] for e in small],[420,1420])
        self.assertEqual([e['t_ms'] for e in main],[500,1500])
        self.assertEqual([e['occurrence'] for e in small],[e['occurrence'] for e in main])
        self.assertEqual(result['duration_ms'],old['duration_ms'])
        self.assertTrue(result['performance_complete'])
        decode(encode(compile_practice_score(p)))

    def test_repeat_interior_negative_control_identical(self):
        p=fixtures.grace(1,2);self.assertEqual(before.realize_project(p)['audio_events'],self.run_source(p)['audio_events'])

    def test_more_than_two_repetitions_preserves_every_small_attack(self):
        p=fixtures.grace(1,1);p['repeat_sections'][0]['count']=3;r=self.run_source(p)
        self.assertEqual([e['t_ms'] for e in r['audio_events'] if e['source_note_ids']==['small']],[420,1420,2420])

    def test_selected_repeat_start_borrows_on_beat_without_negative_time(self):
        p=fixtures.grace(1,1);p['selection']['start_beat']=1;r=self.run_source(p)
        small=[e for e in r['audio_events'] if e['source_note_ids']==['small']]
        self.assertEqual(len(small),2);self.assertTrue(all(e['t_ms']>=0 for e in r['audio_events']))
        self.assertEqual(next(f for f in r['features'] if f['kind']=='grace_short')['parameters']['placement'],'on')

    def test_left_fermata_over_right_rest_really_delays_later_attack(self):
        p=fixtures.fermata('left_over_silence');old=before.realize_project(p);r=self.run_source(p)
        t=lambda a:next(e['t_ms'] for e in a['audio_events'] if e['source_note_ids']==['after'])
        self.assertEqual(t(old),1500);self.assertEqual(t(r),1750)
        self.assertEqual(len([f for f in r['features'] if f['kind']=='fermata']),1)

    def test_existing_right_rest_and_sounding_left_controls_unchanged(self):
        for kind in ('right_rest','left_over_sound','none'):
            with self.subTest(kind=kind):
                p=fixtures.fermata(kind);self.assertEqual(before.realize_project(p)['audio_events'],self.run_source(p)['audio_events'])

    def test_terminal_empty_measure_uses_explicit_right_clock_and_preserves_source(self):
        p=fixtures.fermata('terminal_empty_measure')
        p['right_hand_timing']={'measures':[dict(page=1,system=1,measure=2,start_beat=1,length_beats=2,timing_estimated=True)]}
        r=self.run_source(p);self.assertEqual(r['duration_ms'],2000)
        f=next(f for f in r['features'] if f['kind']=='fermata')
        self.assertEqual(f['parameters']['pause_end_beat'],3);self.assertTrue(f['estimated'])
        self.assertFalse(any('left' in e['source_note_ids'] for e in r['audio_events']))

    def test_unlocatable_shared_fermata_blocks_instead_of_silent_success(self):
        p=fixtures.fermata('terminal_empty_measure');r=self.run_source(p,True)
        self.assertTrue(r['errors']);self.assertNotIn('audio_events',r)
        self.assertIn('右手时间锚',r['errors'][0]['message'])

    def test_conflicting_right_clocks_block(self):
        p=fixtures.fermata('left_over_silence');p['right_hand_timing']={'measures':[dict(page=1,system=1,measure=2,start_beat=9,length_beats=2)]}
        self.assertTrue(self.run_source(p,True)['errors'])

    def test_duplicate_shared_fermata_pauses_once(self):
        p=fixtures.fermata('left_over_silence');n=deepcopy(p['notes'][-1]);n['id']='left2';p['notes'].append(n)
        r=self.run_source(p)
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if e['source_note_ids']==['after']),1750)

    def test_competing_ornaments_remain_blocked_but_existing_editor_can_choose(self):
        p=fixtures.project([fixtures.note('one','C4',0,1,marks=[fixtures.mark('trill','tr'),fixtures.mark('mordent_lower','wave')])])
        r=self.run_source(p,True);self.assertTrue(r['errors'])
        state=r['note_states']['one'];self.assertIn('kind',state['editable_fields'])
        self.assertEqual(set(state['parameters']['candidates']),{'trill','mordent_lower'})
        self.assertFalse(state['realized']);self.assertIn('请选择',state['message'].replace('请在练习解释中选一种','请选择'))
        for kind in ('trill','mordent_lower'):
            with self.subTest(kind=kind):
                chosen=deepcopy(p);chosen['notes'][0]['performance_override']={'kind':kind}
                result=self.run_source(chosen)
                self.assertTrue(result['performance_complete'])
                self.assertEqual(set(result['note_states']['one']['parameters']['candidates']),{'trill','mordent_lower'})
                self.assertEqual(len(chosen['notes'][0]['performance_marks']),2)

if __name__=='__main__':unittest.main(verbosity=2)
