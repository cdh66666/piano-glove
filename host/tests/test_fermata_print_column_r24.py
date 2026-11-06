"""Independent source-column clock inference; no customer constants."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
from score_realization import realize_project

def note(ident,pitch,beat,duration,x,hand='right',measure=1,local=None,marks=()):
    return dict(id=ident,hand=hand,page=1,system=1,measure=measure,staff='rh' if hand=='right' else 'lh',origin=[x,20 if hand=='right' else 100],
        pitch=pitch,finger=2,source_fingering_state='printed',duration_beats=duration,duration=duration,beat=beat,
        measure_beat=beat if local is None and beat is not None else local,measure_start_beat=0 if hand=='right' else None,
        performance_marks=list(marks))
def mark(group):return dict(kind='fermata',group_id=group,options={})
def make(rest=True):
    a=note('a','C4',0,1,100);b=note('after','D4',3,1,250,measure=2,local=0);b['measure_start_beat']=3
    lh=note('lh-pause','C3',None,1,150,'left',marks=[mark('lower-pause')])
    p=dict(name='Independent source columns',source_kind='manual',recognition_performed=False,notes=[a,b,lh],
        staves=[dict(id='rh',lines=[0,10,20,30,40]),dict(id='lh',lines=[80,90,100,110,120])],rests=[],
        performance_policy=dict(mode='practice'),selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
    target=note('rh-anchor','E4',1,1,150)
    if rest:
        target.pop('pitch');target.pop('finger');p['rests'].append(target)
    else:p['notes'].append(target)
    return p

class FermataColumnTests(unittest.TestCase):
    def test_unique_unmarked_rh_rest_column_delays_after_without_creating_a_sound(self):
        p=make();before=deepcopy(p);r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'after' in e['source_note_ids']),1750)
        self.assertEqual(len(r['audio_events']),2);self.assertEqual(p,before)
        f=next(f for f in r['features'] if f['kind']=='fermata')
        self.assertEqual(f['parameters']['right_hand_clock']['anchor_source_ids'],['rh-anchor'])
        self.assertTrue(f['estimated'])

    def test_unique_unmarked_rh_note_column_is_a_clock_without_a_second_printed_fermata(self):
        r=realize_project(make(False));self.assertFalse(r['errors'])
        self.assertEqual(next(e['duration_ms'] for e in r['audio_events'] if 'rh-anchor' in e['source_note_ids']),750)

    def test_different_source_durations_cannot_be_assumed_equivalent(self):
        p=make();p['rests'][0]['duration_beats']=2;p['rests'][0]['duration']=2
        self.assertTrue(realize_project(p)['errors'])

    def test_different_printed_column_does_not_supply_an_arbitrary_time(self):
        p=make();p['rests'][0]['origin'][0]=165;self.assertTrue(realize_project(p)['errors'])

    def test_conflicting_known_clocks_at_one_column_remain_blocked(self):
        p=make();p['notes'].append(note('other-voice','F4',2,1,150))
        self.assertTrue(realize_project(p)['errors'])

    def test_known_lh_local_position_remains_authoritative_relative_to_rh_measure(self):
        p=make();p['notes'][2]['measure_beat']=0;r=realize_project(p);self.assertFalse(r['errors'])
        f=next(f for f in r['features'] if f['kind']=='fermata');self.assertEqual(f['parameters']['pause_start_beat'],0)

    def test_explicitly_cleared_lh_start_is_not_reinferred(self):
        p=make();p['notes'][2]['manual_fields']=['beat'];self.assertTrue(realize_project(p)['errors'])

    def test_known_lh_global_without_local_is_not_overwritten_by_column_inference(self):
        p=make();p['notes'][2]['beat']=2;self.assertTrue(realize_project(p)['errors'])

    def test_separate_existing_rh_fermata_is_not_merged_into_the_later_rest_pause(self):
        p=make();p['notes'][0]['performance_marks']=[mark('earlier')];r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'after' in e['source_note_ids']),2000)
        self.assertEqual(sorted(f['parameters']['pause_end_beat'] for f in r['features'] if f['kind']=='fermata'),[1,2])

    def test_known_local_pause_ignores_a_conflicting_same_column_candidate(self):
        p=make();p['notes'][2]['measure_beat']=0;p['notes'].append(note('other-voice','F4',2,1,150))
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual(next(f['parameters']['pause_start_beat'] for f in r['features'] if f['kind']=='fermata'),0)

if __name__=='__main__':unittest.main()
