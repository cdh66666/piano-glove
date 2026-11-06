"""Synthetic recognition and actual audio controls; no customer identifiers."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
HERE=Path(__file__).resolve().parent
HOST=HERE.parents[2]/'repo/host'
sys.path[:0]=[str(HERE),str(HOST)]
from score_compound import annotate_combinations,combination_pair,long_mordent_pair,LONG_MORDENT
from score_realization import realize_project

def mark(kind,gid,box=None,**options):
    return dict(kind=kind,group_id=gid,source=dict(method='printed_music_glyph',font='SyntheticMusic',bbox=box or [10,10,30,22]),options=options)
def note(ident,pitch,beat,duration=1,marks=(),**extra):
    return dict(id=ident,hand='right',page=1,system=1,measure=1,staff='r',pitch=pitch,finger=None,source_fingering_state='unmarked',
        beat=beat,duration_beats=duration,origin=[100+beat*100,100],performance_marks=list(marks),pitch_context=dict(key_signature={}),**extra)
def grace_project(ornament='trill',placement='on'):
    gm=mark('grace_after' if placement=='after' else 'grace_short' if placement=='before' else 'grace_unspecified','parent',anchor_id='a',member_ids=['g'],order=0)
    ns=[note('lead','C4',0),note('g','D4',1,None,[gm,mark(ornament,'child')],grace_kind='unmeasured',main_anchor_id='a'),note('a','E4',1),note('next','F4',2)]
    return dict(name='Synthetic hierarchy',source_kind='manual',recognition_performed=False,notes=ns,
        selection=dict(bpm=120,start_beat=0,repeat_mode='written'),performance_policy=dict(mode='practice'))

class CandidateTests(unittest.TestCase):
    def test_each_grace_placement_preserves_two_layers_actual_alternation_budget_and_next_beat(self):
        for placement in ('before','on','after'):
            with self.subTest(placement=placement):
                p=grace_project(placement=placement);before=deepcopy(p);r=realize_project(p)
                self.assertFalse(r['errors']);self.assertEqual(p,before)
                rows=[e for e in r['audio_events'] if e['source_note_ids']==['g']]
                self.assertEqual([e['pitch'] for e in rows],[62,64]);self.assertEqual({e['group_id'] for e in rows},{'child'})
                self.assertEqual({e['parent_group_id'] for e in rows},{'parent'})
                anchor=next(e for e in r['audio_events'] if e['source_note_ids']==['a'])
                right=1000 if placement=='after' else anchor['t_ms'];left=right-80
                self.assertTrue(all(left<=e['t_ms'] and e['t_ms']+e['duration_ms']<=right for e in rows))
                self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if e['source_note_ids']==['next']),1000)
                features={f['group_id']:f for f in r['features']}
                self.assertTrue(features['parent']['realized']);self.assertTrue(features['child']['realized'])
                self.assertTrue(features['parent']['estimated']);self.assertTrue(features['child']['estimated'])
                self.assertEqual(features['child']['parameters']['parent_group_id'],'parent')
    def test_mordents_and_turns_use_borrowed_window_without_extra_plain_attack(self):
        for kind,pitches in [('mordent_upper',[62,64,62]),('mordent_lower',[62,60,62]),('turn',[64,62,60,62]),('inverted_turn',[60,62,64,62])]:
            with self.subTest(kind=kind):
                r=realize_project(grace_project(kind));self.assertFalse(r['errors'])
                rows=[e for e in r['audio_events'] if e['source_note_ids']==['g']]
                self.assertEqual([e['pitch'] for e in rows],pitches)
                self.assertTrue(all(500<=e['t_ms'] and e['t_ms']+e['duration_ms']<=580 for e in rows))
    def test_user_ornament_choice_on_grace_keeps_grace_parent(self):
        p=grace_project();p['notes'][1]['performance_override']=dict(kind='mordent_lower')
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual([e['pitch'] for e in r['audio_events'] if e['source_note_ids']==['g']],[62,60,62])
        self.assertTrue(any(f['kind']=='grace_unspecified' and f['realized'] for f in r['features']))
    def test_gate_override_cannot_extend_child_outside_grace_budget(self):
        p=grace_project();p['notes'][1]['performance_override']=dict(gate_ratio=1.2)
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertTrue(all(e['t_ms']+e['duration_ms']<=580 for e in r['audio_events'] if e['source_note_ids']==['g']))
    def test_repeat_keeps_each_child_and_parent_per_occurrence(self):
        p=grace_project();p['repeat_sections']=[dict(start_beat=0,end_beat=3,count=2,confirmed=True)];p['selection']['repeat_mode']='unfold'
        r=realize_project(p);self.assertFalse(r['errors'])
        rows=[e for e in r['audio_events'] if e['source_note_ids']==['g']]
        self.assertEqual(len(rows),4);self.assertEqual({e['occurrence'] for e in rows},{0,1})
    def test_competing_unrelated_ornaments_stay_unresolved(self):
        p=grace_project();p['notes'][1]['performance_marks'].append(mark('mordent_upper','other'))
        self.assertTrue(realize_project(p)['errors'])
    def test_grace_glissando_cannot_claim_an_unverified_truncated_run(self):
        p=grace_project('glissando');p['notes'][1]['performance_marks'][1]['options']['target_id']='a'
        r=realize_project(p);self.assertTrue(r['errors']);self.assertFalse(any(f['kind']=='glissando' and f['realized'] for f in r['features']))
    def test_tight_vertical_trill_lower_stack_recognizes_other_font_and_scale(self):
        for scale in (.5,1,2):
            for shift in (-300,0,500):
                a=[shift+x*scale for x in [10,10,30,22]];b=[shift+x*scale for x in [8,23,32,36]]
                n=note('x','C5',0,marks=[mark('trill','tr',a),mark('mordent_lower','lo',b)])
                self.assertEqual(annotate_combinations([n],{'r':10*scale}),1);self.assertIsNotNone(combination_pair(n['performance_marks']))
    def test_side_by_side_far_vertical_offset_or_wrong_order_do_not_pair(self):
        for box in ([32,10,54,22],[10,30,30,42],[31,23,51,35],[10,-5,30,8]):
            n=note('x','C5',0,marks=[mark('trill','tr'),mark('mordent_lower','lo',box)])
            self.assertEqual(annotate_combinations([n],{'r':10}),0)
    def test_simultaneous_voice_keeps_stack_unresolved(self):
        n=note('x','C5',0,marks=[mark('trill','tr'),mark('mordent_lower','lo',[8,23,32,36])]);peer=note('v','E5',0)
        self.assertEqual(annotate_combinations([n,peer],{'r':10}),0)

    def long_project(self):
        n=note('long','C5',0,marks=[mark('mordent_upper','wave',[10,12,30,20]),mark('mordent_lower','stroke',[18,10,38,23])])
        p=dict(name='Synthetic long lower sign',source_kind='manual',recognition_performed=False,notes=[n,note('next','D5',1)],
            selection=dict(bpm=120,start_beat=0,repeat_mode='written'),performance_policy=dict(mode='practice'))
        return p
    def test_long_lower_ink_relation_preserves_all_raw_fields(self):
        p=self.long_project();before=deepcopy(p)
        self.assertEqual(annotate_combinations(p['notes'],{'r':10}),1);self.assertIsNotNone(long_mordent_pair(p['notes'][0]['performance_marks']))
        for old,new in zip(before['notes'][0]['performance_marks'],p['notes'][0]['performance_marks']):
            self.assertEqual({k:old[k] for k in ('kind','group_id','source')},{k:new[k] for k in ('kind','group_id','source')})
    def test_long_lower_is_exact_five_downward_attacks_with_no_separate_upper_sound(self):
        p=self.long_project();annotate_combinations(p['notes'],{'r':10});before=deepcopy(p);r=realize_project(p)
        self.assertFalse(r['errors']);self.assertEqual(p,before)
        rows=[e for e in r['audio_events'] if e['source_note_ids']==['long']]
        self.assertEqual([e['pitch'] for e in rows],[72,71,72,71,72]);self.assertEqual({e['group_id'] for e in rows},{'stroke'})
        self.assertTrue(all(0<=e['t_ms']<500 and e['t_ms']+e['duration_ms']<=500 for e in rows))
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if e['source_note_ids']==['next']),500)
        wave=next(f for f in r['features'] if f['group_id']=='wave');self.assertFalse(wave['realized']);self.assertEqual(wave['rendering'],'notation-ink-component')
        lower=next(f for f in r['features'] if f['group_id']=='stroke');self.assertTrue(lower['realized']);self.assertTrue(lower['estimated'])
    def test_long_lower_accepts_explicit_full_sign_choice(self):
        p=self.long_project();annotate_combinations(p['notes'],{'r':10});p['notes'][0]['performance_override']=dict(kind=LONG_MORDENT)
        self.assertFalse(realize_project(p)['errors'])
    def test_long_lower_scale_translation_and_reversed_extension_are_generic(self):
        for scale in (.4,1,3):
            for reverse in (False,True):
                p=self.long_project();a,b=p['notes'][0]['performance_marks']
                if reverse:a['source']['bbox']=[18,12,38,20];b['source']['bbox']=[10,10,30,23]
                for m in (a,b):m['source']['bbox']=[100+v*scale for v in m['source']['bbox']]
                self.assertEqual(annotate_combinations(p['notes'],{'r':10*scale}),1)
    def test_long_lower_requires_vertical_stroke_and_collinear_overlapping_extension(self):
        for box in ([18,12,38,20],[18,30,38,43],[35,10,55,23],[10,10,30,23]):
            p=self.long_project();p['notes'][0]['performance_marks'][1]['source']['bbox']=box
            self.assertEqual(annotate_combinations(p['notes'],{'r':10}),0)
    def test_long_lower_other_font_shared_owner_or_chord_remain_unresolved(self):
        for mutation in ('font','shared','chord'):
            p=self.long_project();n=p['notes'][0]
            if mutation=='font':n['performance_marks'][1]['source']['font']='DifferentMusic'
            elif mutation=='shared':p['notes'][1]['performance_marks']=deepcopy(n['performance_marks'])
            else:p['notes'][1]['origin']=list(n['origin'])
            self.assertEqual(annotate_combinations(p['notes'],{'r':10}),0)

if __name__=='__main__':unittest.main()
