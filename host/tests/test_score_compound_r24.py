"""Independent same-anchor combination and actual two-phase controls."""
from pathlib import Path
from copy import deepcopy
import sys,unittest,json
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
from score_compound import annotate_combinations,combination_pair,COMBINATION
from score_realization import realize_project,compile_practice_score
from score_codec import encode,decode

def mark(kind,group,box=None,font='Aloisen'):
    return dict(kind=kind,group_id=group,position='on',source=dict(method='printed_music_glyph',font=font,
        char='tr' if kind=='trill' else 'lower',bbox=box or [97,12,115,24]),options={})
def note(ident='a',beat=0,pitch='C5',finger=3,marks=None,**extra):
    return dict(id=ident,hand='right',page=1,system=1,measure=1,staff='rh',origin=[100+beat*50,55],
        pitch=pitch,finger=finger,source_fingering_state='printed' if finger else 'unmarked',duration_beats=1,beat=beat,
        performance_marks=marks if marks is not None else [mark('trill','tr'),mark('mordent_lower','low')],**extra)
def project(notes=None):
    return dict(name='Independent combination',source_kind='manual',recognition_performed=False,
        notes=notes or [note(),note('next',1,'D5',4,[])],performance_policy=dict(mode='practice'),
        selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
def bound():
    p=project();annotate_combinations(p['notes'],{'rh':10});return p

class CompoundTests(unittest.TestCase):
    def test_relation_retains_both_original_kinds_sources_and_groups(self):
        p=project();before=deepcopy(p);self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),1)
        for a,b in zip(before['notes'][0]['performance_marks'],p['notes'][0]['performance_marks']):
            self.assertEqual({k:a[k] for k in ('kind','source','group_id','position')},{k:b[k] for k in ('kind','source','group_id','position')})
        self.assertEqual(combination_pair(p['notes'][0]['performance_marks'])[2],'a:'+COMBINATION)

    def test_independent_trill_and_lower_remain_independent(self):
        for k in ('trill','mordent_lower'):
            p=project([note(marks=[mark(k,'one')])]);self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),0)
            r=realize_project(p);self.assertFalse(r['errors']);self.assertTrue(any(f['kind']==k for f in r['features']))

    def test_different_fonts_do_not_form_combination(self):
        p=project();p['notes'][0]['performance_marks'][1]['source']['font']='OtherMusic'
        self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),0);self.assertTrue(realize_project(p)['errors'])

    def test_close_but_nonoverlapping_symbols_do_not_form_combination(self):
        p=project();p['notes'][0]['performance_marks'][1]['source']['bbox']=[117,12,135,24]
        self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),0);self.assertTrue(realize_project(p)['errors'])

    def test_two_neighboring_anchors_are_not_combined(self):
        p=project([note(marks=[mark('trill','one')]),note('b',1,'D5',4,[mark('mordent_lower','two')])])
        self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),0);self.assertFalse(realize_project(p)['errors'])

    def test_multiple_simultaneous_voices_are_not_automatically_interpreted(self):
        p=project([note(voice=1),note('other',0,'E5',2,[],voice=2)])
        self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),0);self.assertTrue(realize_project(p)['errors'])

    def test_chord_shared_components_are_not_mistaken_for_unique_single_anchor(self):
        a=note();b=note('other',0,'E5',2,deepcopy(a['performance_marks']))
        self.assertEqual(annotate_combinations([a,b],{'rh':10}),0)

    def test_two_lower_candidates_remain_ambiguous(self):
        p=project();p['notes'][0]['performance_marks'].append(mark('mordent_lower','third'))
        self.assertEqual(annotate_combinations(p['notes'],{'rh':10}),0)

    def test_actual_trill_and_lower_sequences_share_total_budget_keep_next_beat(self):
        p=bound();before=deepcopy(p);r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual(p,before)
        body=[e for e in r['audio_events'] if e['group_id']=='tr'];tail=[e for e in r['audio_events'] if e['group_id']=='low']
        self.assertGreaterEqual(len(body),2);self.assertEqual([e['pitch'] for e in body[:2]],[72,74])
        self.assertEqual([e['pitch'] for e in tail],[72,71,72]);self.assertLess(body[-1]['t_ms'],tail[0]['t_ms'])
        self.assertEqual(tail[-1]['t_ms']+tail[-1]['duration_ms'],500)
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'next' in e['source_note_ids']),500)
        self.assertTrue(all(f['estimated'] for f in r['features'] if f['kind'] in ('trill','mordent_lower')))
        self.assertEqual(r['coverage']['selected_sources'],r['coverage']['sounded_sources'])

    def test_lower_and_upper_accidentals_are_separate(self):
        p=bound();a,b=p['notes'][0]['performance_marks'];a['options']['auxiliary_accidental']=-1;b['options']['auxiliary_accidental']=-1
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertIn(73,[e['pitch'] for e in r['audio_events'] if e['group_id']=='tr'])
        self.assertEqual([e['pitch'] for e in r['audio_events'] if e['group_id']=='low'],[72,70,72])

    def test_upper_and_lower_fingers_have_separate_user_sources(self):
        p=bound();p['notes'][0]['performance_override']=dict(aux_finger=5,lower_aux_finger=1)
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual({e['finger'] for e in r['audio_events'] if e['pitch']==74 and 'a' in e['source_note_ids']},{5})
        self.assertEqual({e['finger'] for e in r['audio_events'] if e['pitch']==71},{1})
        self.assertEqual(p['notes'][0]['finger'],3)

    def test_unmarked_stays_gray_and_audio_only_with_two_effects(self):
        p=bound();p['notes'][0].update(finger=None,source_fingering_state='unmarked');r=realize_project(p)
        self.assertFalse(r['errors']);self.assertTrue(all(e['finger'] is None for e in r['audio_events'] if 'a' in e['source_note_ids']))

    def test_changing_borrow_ratio_moves_real_tail_and_not_the_next_note(self):
        p=bound();r=realize_project(p);p['notes'][0]['performance_override']=dict(borrow_ratio=.5)
        s=realize_project(p);self.assertFalse(s['errors'])
        self.assertNotEqual(next(e['t_ms'] for e in r['audio_events'] if e['group_id']=='low'),next(e['t_ms'] for e in s['audio_events'] if e['group_id']=='low'))
        self.assertEqual(next(e['t_ms'] for e in s['audio_events'] if 'next' in e['source_note_ids']),500)

    def test_rate_changes_actual_trill_density_within_source_budget(self):
        p=bound();p['notes'][0]['performance_override']=dict(rate_hz=4);a=realize_project(p)
        p['notes'][0]['performance_override']=dict(rate_hz=20);b=realize_project(p)
        self.assertLess(sum(e['group_id']=='tr' for e in a['audio_events']),sum(e['group_id']=='tr' for e in b['audio_events']))
        self.assertEqual(a['duration_ms'],b['duration_ms'])

    def test_single_choices_combo_and_restore_change_real_events_not_source(self):
        for kind in ('trill','mordent_lower',COMBINATION,None):
            p=bound();before=deepcopy(p['notes'][0]['performance_marks']);p['notes'][0]['performance_override']=dict(kind=kind) if kind else {}
            r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual(p['notes'][0]['performance_marks'],before)
            values=[e['pitch'] for e in r['audio_events'] if 'a' in e['source_note_ids']]
            self.assertEqual(71 in values,kind!='trill');self.assertEqual(74 in values,kind!='mordent_lower')

    def test_forged_or_insufficient_pair_cannot_be_enabled_by_type_choice(self):
        p=project();p['notes'][0]['performance_override']=dict(kind=COMBINATION)
        self.assertTrue(realize_project(p)['errors'])

    def test_same_finger_cannot_pretend_to_play_main_and_neighbor(self):
        for field in ('aux_finger','lower_aux_finger'):
            p=bound();p['notes'][0]['performance_override']={field:3};self.assertTrue(realize_project(p)['errors'])

    def test_codec_and_source_identity_use_actual_audio(self):
        p=bound();score=compile_practice_score(p);self.assertEqual(decode(encode(score))['notes'],score['notes'])
        self.assertTrue(score['performance']['performance_complete'])

if __name__=='__main__':unittest.main()
