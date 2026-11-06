"""Independent musical examples. No customer PDF, gold, model or device input."""
from pathlib import Path
from copy import deepcopy
import json,sys,unittest
ROOT=Path(__file__).resolve().parent;HOST=ROOT.parent
sys.path.insert(0,str(HOST))
from score_realization import realize_project,compile_practice_score
from score_codec import encode,decode

def mark(kind,group=None,**options):return dict(kind=kind,group_id=group,options=options)
def note(ident='a',pitch='C4',beat=0,duration=1,finger=1,marks=(),**extra):
    return dict(id=ident,hand='right',pitch=pitch,finger=finger,beat=beat,duration_beats=duration,
        source_fingering_state='printed' if finger is not None else 'unmarked',performance_marks=list(marks),
        page=1,system=1,measure=1,**extra)
def project(notes,**extra):return dict(name='独立记谱例',notes=notes,selection=dict(bpm=120,start_beat=0,repeat_mode='written'),
    performance_policy=dict(mode='practice'),**extra)
def audio(p):
    result=realize_project(p)
    if result['errors']:raise AssertionError(result['errors'])
    return result['audio_events']

class RealizationTests(unittest.TestCase):
    def test_gliss_uses_one_held_finger_not_invented_auxiliary_digits(self):
        p=project([note('g','C4',0,1,3,marks=[mark('glissando',target_id='b')]),
                   note('b','C5',1,1,5)])
        r=realize_project(p);self.assertFalse(r['errors'])
        sliding=[e for e in r['audio_events'] if 'g' in e['source_note_ids']]
        self.assertEqual([e['pitch'] for e in sliding],[60,62,64,65,67,69,71])
        self.assertEqual({e['finger'] for e in sliding},{3})
        self.assertEqual(len([e for e in r['motion_events'] if 'g' in e['source_note_ids']]),1)
        self.assertNotIn('aux_finger',r['note_states']['g']['editable_fields'])
        self.assertNotIn('rate_hz',r['note_states']['g']['editable_fields'])

    def after_grace_geometry_project(self):
        notes=[]
        for measure,base in ((1,0),(2,4.5)):
            for i in range(4):
                n=note(('a' if measure==1 else 'b')+str(i),'C4',base+i,1,1,
                    staff='right',voice='one',origin=[50+i*45,20],measure_beat=i,measure_start_beat=base)
                n['measure']=measure;notes.append(n)
        small=note('after','D4',4,.5,2,marks=[mark('grace_after','after-group',anchor_id='a3')],
            staff='right',voice='one',origin=[210,15],measure_beat=4,measure_start_beat=0)
        notes.insert(4,small)
        return project(notes,staves=[dict(id='right',hand='right',page=1,system=1,lines=[0,10,20,30,40],
            measures=[dict(measure=1,meter_beats=4,timing_resolved=False),dict(measure=2,meter_beats=4,timing_resolved=False)])],written_duration_beats=8.5)

    def test_derived_meter_removes_aftergrace_nominal_half_beat_from_followers(self):
        p=self.after_grace_geometry_project();before=deepcopy(p);r=realize_project(p)
        self.assertFalse(r['errors'])
        first=next(e for e in r['audio_events'] if 'a0' in e['source_note_ids'])
        following=next(e for e in r['audio_events'] if 'b0' in e['source_note_ids'])
        self.assertEqual(following['t_ms']-first['t_ms'],2000)
        self.assertEqual(r['duration_ms'],4000);self.assertEqual(p,before)
        self.assertEqual(r['source_map']['after']['source_duration_beats'],.5)
        self.assertEqual(r['source_map']['b0']['source_beat'],4.5)
        self.assertEqual(r['source_map']['b0']['derived_performance_beat'],4)

    def test_derived_grace_clock_preserves_explicit_manual_global_anchor(self):
        p=self.after_grace_geometry_project();n=next(n for n in p['notes'] if n['id']=='b0')
        n.update(beat=10,manual_fields=['beat']);r=realize_project(p)
        self.assertFalse(r['errors']);self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'b0' in e['source_note_ids']),5000)
        self.assertEqual(n['beat'],10)

    def test_measured_manual_grace_duration_is_not_removed_from_meter(self):
        p=self.after_grace_geometry_project();n=next(n for n in p['notes'] if n['id']=='after');n['manual_fields']=['duration_beats']
        r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'b0' in e['source_note_ids']),2250)

    def test_repeat_boundaries_follow_derived_grace_clock_without_editing_source(self):
        p=self.after_grace_geometry_project();p['selection']['repeat_mode']='unfold'
        p['repeat_sections']=[dict(start_beat=0,end_beat=4.5,count=2,confirmed=True)]
        before=deepcopy(p);r=realize_project(p);self.assertFalse(r['errors'])
        self.assertEqual([e['t_ms'] for e in r['audio_events'] if 'a0' in e['source_note_ids']],[0,2000])
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'b0' in e['source_note_ids']),4000)
        self.assertEqual(r['duration_ms'],6000);self.assertEqual(p,before)

    def test_source_unchanged_and_basic_timing(self):
        p=project([note()]);before=deepcopy(p);score=compile_practice_score(p)
        self.assertEqual(p,before);self.assertEqual(score['performance']['audio_events'][0]['duration_ms'],500)
        self.assertEqual(decode(encode(score))['notes'],score['notes'])
        self.assertIn('练习',score['title']);self.assertEqual(len(score['performance']['arrangement_id']),64)

    def test_unmarked_is_audio_not_fake_finger(self):
        p=project([note('a'),note('b','E4',1,finger=None)])
        r=realize_project(p);self.assertEqual(len(r['audio_events']),2);self.assertEqual(len(r['motion_events']),1)
        self.assertIsNone(p['notes'][1]['finger']);self.assertEqual(r['coverage']['unmarked_audio_only'],1)

    def test_unresolved_practice_finger_has_separate_provenance(self):
        n=note('u',finger=None);n['source_fingering_state']='unresolved';p=project([n]);r=realize_project(p)
        self.assertEqual(r['motion_events'][0]['finger'],3);self.assertIsNone(n['finger'])
        self.assertEqual(r['source_map']['u']['finger_origin'],'estimated');self.assertTrue(r['note_states']['u']['warning_root'])

    def test_real_overlap_unions_motor_but_all_chord_audio_survives(self):
        r=realize_project(project([note('a'),note('b','E4')]))
        self.assertEqual([x['pitch'] for x in r['audio_events']],[60,64]);self.assertEqual(len(r['motion_events']),1)
        self.assertEqual(set(r['motion_events'][0]['source_note_ids']),{'a','b'})

    def test_touching_repetitions_keep_independent_motor_attacks(self):
        r=realize_project(project([note('a'),note('b',beat=1),note('c',beat=2)]))
        self.assertEqual([x['t_ms'] for x in r['motion_events']],[0,500,1000])

    def test_staggered_same_finger_overlap_preserves_later_attack_and_long_audio(self):
        r=realize_project(project([note('a',duration=2),note('b','E4',1,1,1)]))
        self.assertEqual([x['t_ms'] for x in r['motion_events']],[0,500])
        self.assertLess(r['motion_events'][0]['duration_ms'],500)
        self.assertEqual(r['audio_events'][0]['duration_ms'],1000)
        self.assertEqual(r['coverage']['motion_expected_attacks'],2)
        self.assertEqual(r['coverage']['motion_actual_attacks'],2)
        self.assertEqual(r['coverage']['missing_motion_onsets'],[])

    def test_audio_changes_must_change_compatible_pgl_identity(self):
        a=project([note('a'),note('b','E4')]);b=deepcopy(a);b['notes'][1]['pitch']='G4'
        x,y=compile_practice_score(a),compile_practice_score(b)
        self.assertEqual(x['notes'],y['notes']);self.assertNotEqual(encode(x),encode(y))
        self.assertEqual(encode(x),encode(compile_practice_score(a)))

    def grace(self,kind,count=1,**over):
        ns=[note('g'+str(i),'D4',0,None,2,marks=[mark(kind,'g',anchor_id='m',order=i)]) for i in range(count)]
        ns[0]['performance_override']=over;return project(ns+[note('m')])

    def test_01_long_grace_divides_principal_without_adding_beat(self):
        p=self.grace('grace_long');before=deepcopy(p);r=realize_project(p)
        self.assertEqual([(e['t_ms'],e['duration_ms']) for e in r['audio_events']],[(0,250),(250,250)])
        self.assertEqual(r['duration_ms'],500);self.assertEqual(p,before)

    def test_02_short_grace_at_piece_start_borrows_on_beat(self):
        r=realize_project(self.grace('grace_short'))
        self.assertEqual([(e['t_ms'],e['duration_ms']) for e in r['audio_events']],[(0,80),(80,420)])
        self.assertTrue(r['estimates']);self.assertEqual(r['duration_ms'],500)

    def test_03_cluster_keeps_every_head_in_one_borrowed_window(self):
        r=realize_project(self.grace('grace_cluster',2))
        self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,40,80]);self.assertEqual(r['coverage']['sounded_sources'],3)
        self.assertEqual(r['duration_ms'],500)

    def test_04_after_grace_uses_principal_tail(self):
        r=realize_project(self.grace('grace_after'))
        self.assertEqual([(e['pitch'],e['t_ms'],e['duration_ms']) for e in r['audio_events']],[(60,0,420),(62,420,80)])

    def test_unslashed_never_automatically_becomes_traditional_long(self):
        r=realize_project(self.grace('grace_unspecified'))
        self.assertEqual(r['audio_events'][0]['duration_ms'],80);self.assertIn('grace_unspecified',[x['kind'] for x in r['estimates']])

    def test_prebeat_grace_shortens_preceding_voice_not_main_attack(self):
        p=project([note('prev'),note('g','D4',1,None,2,marks=[mark('grace_short',anchor_id='m')]),note('m','E4',1,1,3)])
        self.assertEqual([(e['t_ms'],e['duration_ms']) for e in audio(p)],[(0,420),(420,80),(500,500)])

    def test_manual_grace_time_is_not_reinterpreted(self):
        p=project([note('g','D4',.75,.25,2,marks=[mark('grace_short',anchor_id='m')],manual_fields=['duration_beats']),note('m','E4',1,1,3)])
        self.assertEqual(audio(p)[0]['t_ms'],375)

    def test_05_upper_mordent_actual_auxiliary_attack(self):
        a=audio(project([note(marks=[mark('mordent_upper')])]))
        self.assertEqual([e['pitch'] for e in a],[60,62,60]);self.assertEqual([e['finger'] for e in a],[1,2,1]);self.assertEqual(a[-1]['t_ms']+a[-1]['duration_ms'],500)

    def test_06_lower_mordent_actual_lower_neighbor(self):
        self.assertEqual([e['pitch'] for e in audio(project([note(pitch='G4',finger=3,marks=[mark('mordent_lower')])]))],[67,65,67])

    def test_07_turn_uses_upper_main_lower_main(self):
        self.assertEqual([e['pitch'] for e in audio(project([note(pitch='G4',finger=3,marks=[mark('turn')])]))],[69,67,65,67])

    def test_08_inverted_turn_is_not_regular_turn(self):
        self.assertEqual([e['pitch'] for e in audio(project([note(pitch='G4',finger=3,marks=[mark('inverted_turn')])]))],[65,67,69,67])

    def test_turn_accidentals_are_independent_above_and_below(self):
        p=project([note(pitch='C5',marks=[mark('turn',auxiliary_accidental='sharp')])]);self.assertEqual([e['pitch'] for e in audio(p)],[75,72,71,72])
        p=project([note(pitch='C5',marks=[mark('turn',upper_auxiliary_accidental='flat',lower_auxiliary_accidental='flat')])]);self.assertEqual([e['pitch'] for e in audio(p)],[73,72,70,72])

    def test_delayed_turn_holds_main_before_turn_and_rate_really_changes_attacks(self):
        p=project([note(pitch='G4',marks=[mark('turn',delayed=True)])]);a=audio(p)
        self.assertEqual(a[0]['pitch'],67);self.assertEqual(a[0]['duration_ms'],250);self.assertEqual(a[1]['t_ms'],250)
        p['notes'][0]['performance_override']={'rate_hz':20};b=audio(p)
        self.assertNotEqual([e['t_ms'] for e in a],[e['t_ms'] for e in b])

    def test_09_trill_spans_its_written_duration(self):
        p=project([note(duration=2,marks=[mark('trill')])]);a=audio(p)
        self.assertEqual(len(a),8);self.assertEqual([x['pitch'] for x in a],[60,62]*4);self.assertEqual(a[-1]['t_ms']+a[-1]['duration_ms'],1000)

    def test_auxiliary_respects_key_signature_and_explicit_alteration(self):
        p=project([note(pitch='E4',marks=[mark('trill')],pitch_context={'key_signature':1})]);self.assertIn(66,[x['pitch'] for x in audio(p)])
        p=project([note(marks=[mark('trill',auxiliary_accidental='sharp')])]);self.assertIn(63,[x['pitch'] for x in audio(p)])
        p=project([note(pitch='E4',marks=[mark('trill')],pitch_context={'key_signature':{'F':1}})]);self.assertIn(66,[x['pitch'] for x in audio(p)])

    def test_grace_chord_heads_in_one_column_sound_simultaneously(self):
        p=project([note('g1','D4',0,None,2,marks=[mark('grace_cluster','g',anchor_id='m',order=0)]),
            note('g2','F4',0,None,4,marks=[mark('grace_cluster','g',anchor_id='m',order=0)]),note('m')])
        a=audio(p);self.assertEqual([e['t_ms'] for e in a],[0,0,80]);self.assertEqual([e['duration_ms'] for e in a],[80,80,420])

    def test_legacy_single_grace_groups_with_one_anchor_share_one_budget(self):
        p=project([note('g1','D4',0,None,2,marks=[mark('grace_short','old1',anchor_id='m',order=0)]),
            note('g2','F4',0,None,4,marks=[mark('grace_short','old2',anchor_id='m',order=1)]),note('m')])
        a=audio(p);self.assertEqual([e['t_ms'] for e in a],[0,40,80]);self.assertEqual(a[-1]['duration_ms'],420)

    def test_10_arpeggio_attacks_roll_and_hold_to_same_end(self):
        ns=[note(str(i),p,0,1,i+1,marks=[mark('arpeggio','chord')]) for i,p in enumerate(('C4','E4','G4'))]
        a=audio(project(ns));self.assertEqual([e['t_ms'] for e in a],[0,30,60]);self.assertEqual([e['t_ms']+e['duration_ms'] for e in a],[500]*3)

    def test_unknown_ordinary_arpeggio_group_reports_source_gap_not_empty_min(self):
        p=project([note('a',duration=None,marks=[mark('arpeggio','a')]),note('b','E4',duration=None,finger=2,marks=[mark('arpeggio','a')]),note('next','G4',1,1,3)])
        before=deepcopy(p);r=realize_project(p)
        self.assertEqual({e['id'] for e in r['errors']},{'a','b'})
        self.assertTrue(all('音值' in e['message'] for e in r['errors']))
        self.assertFalse(r['performance_complete']);self.assertEqual(p,before)

    def test_grace_arpeggio_chord_rolls_inside_its_borrowed_window(self):
        marks=[mark('grace_cluster','g',anchor_id='main',order=0),mark('arpeggio','a')]
        p=project([note('low','C4',0,None,1,marks=marks),note('high','E4',0,None,3,marks=marks),note('main','G4',0,1,5)])
        before=deepcopy(p);r=realize_project(p)
        self.assertFalse(r['errors']);self.assertEqual([e['pitch'] for e in r['audio_events']],[60,64,67])
        self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,20,80])
        self.assertEqual(r['duration_ms'],500);self.assertEqual(r['coverage']['sounded_sources'],3)
        self.assertTrue(any(f['kind']=='arpeggio' and f['realized'] for f in r['features']));self.assertEqual(p,before)

    def test_11_written_broken_chord_is_not_rolled_twice(self):
        a=audio(project([note(str(i),p,i*.25,.25,i+1,marks=[mark('broken_chord')]) for i,p in enumerate(('C4','E4','G4','C5'))]))
        self.assertEqual([e['t_ms'] for e in a],[0,125,250,375])

    def test_12_gliss_all_white_keys_audio_one_source_finger_hold(self):
        p=project([note('a',marks=[mark('glissando',target_id='b')]),note('b','C5',1,1,5)])
        r=realize_project(p);self.assertEqual([e['pitch'] for e in r['audio_events']],[60,62,64,65,67,69,71,72])
        self.assertEqual([(e['finger'],e['t_ms'],e['duration_ms']) for e in r['motion_events']],[(1,0,500),(5,500,500)])

    def test_13_single_tremolo_four_sixteenths_in_quarter(self):
        r=realize_project(project([note(marks=[mark('tremolo_single',strokes=2)])]))
        self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,125,250,375]);self.assertEqual(len(r['motion_events']),4)

    def test_14_two_halves_tremolo_share_two_beats_not_four(self):
        ns=[note('a','C4',0,2,1,marks=[mark('tremolo_alternating','t',side=0,span_beats=2,step_beats=.125)]),note('b','E4',0,2,3,marks=[mark('tremolo_alternating','t',side=1,span_beats=2,step_beats=.125)])]
        r=realize_project(project(ns));self.assertEqual(len(r['audio_events']),16);self.assertEqual(r['duration_ms'],1000);self.assertEqual([e['pitch'] for e in r['audio_events']],[60,64]*8)

    def test_15_tuplet_written_durations_are_not_applied_twice(self):
        ns=[note(str(i),'C4',i/3,1/3,1,marks=[mark('tuplet','triplet',actual=3,normal=2,already_applied=True)]) for i in range(3)]
        r=realize_project(project(ns));self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,167,333]);self.assertEqual(r['duration_ms'],500)

    def test_explicit_unapplied_tuplet_retimes_group_and_following_onset(self):
        ns=[note(str(i),'C4',i*.5,.5,1,marks=[mark('tuplet','triplet',actual=3,normal=2,already_applied=False)]) for i in range(3)]+[note('next','D4',1.5,1,2)]
        self.assertEqual([e['t_ms'] for e in audio(project(ns))],[0,167,333,500])

    def test_16_dots_and_double_dots_are_actual_durations(self):
        self.assertEqual(audio(project([note(duration=1.5,marks=[mark('dots',count=1,already_applied=True)])]))[0]['duration_ms'],750)
        self.assertEqual(audio(project([note(marks=[mark('dots',count=2,already_applied=False)])]))[0]['duration_ms'],875)

    def test_17_syncopation_preserves_offbeat_attack(self):
        a=audio(project([note('a',duration=.5),note('b','D4',.5,1,2,marks=[mark('syncopation')]),note('c','E4',1.5,.5,3)]))
        self.assertEqual([(e['t_ms'],e['duration_ms']) for e in a],[(0,250),(250,500),(750,250)])

    def test_18_tie_is_one_sound_and_one_held_same_finger(self):
        r=realize_project(project([note('a',marks=[mark('tie',target_id='b')]),note('b',beat=1)]))
        self.assertEqual(len(r['audio_events']),1);self.assertEqual(r['audio_events'][0]['duration_ms'],1000)
        self.assertEqual(len(r['motion_events']),1);self.assertEqual(r['motion_events'][0]['duration_ms'],1000)
        self.assertEqual(r['coverage']['sounded_sources'],2)

    def test_tie_with_written_finger_substitution_does_not_restrike_audio(self):
        r=realize_project(project([note('a',marks=[mark('tie',target_id='b')]),note('b',beat=1,finger=2)]))
        self.assertEqual(len(r['audio_events']),1);self.assertEqual(len(r['motion_events']),2)

    def test_unmarked_tied_continuation_extends_existing_finger_without_inventing_source_digit(self):
        p=project([note('a',marks=[mark('tie',target_id='b')]),note('b',beat=1,finger=None)])
        r=realize_project(p);self.assertEqual(len(r['motion_events']),1);self.assertEqual(r['motion_events'][0]['duration_ms'],1000)
        self.assertIn('b',r['motion_events'][0]['source_note_ids']);self.assertIsNone(p['notes'][1]['finger'])
        self.assertEqual(r['source_map']['b']['finger_origin'],'tie-continuation')

    def test_19_slur_keeps_two_attacks_and_audio_connection_only(self):
        r=realize_project(project([note('a',marks=[mark('slur',target_id='b')]),note('b','D4',1,1,2)]))
        self.assertEqual(len(r['audio_events']),2);self.assertEqual(r['audio_events'][0]['duration_ms'],520);self.assertEqual(r['motion_events'][0]['duration_ms'],500)

    def test_20_fermata_moves_followers_but_never_source_beats(self):
        p=project([note('a',marks=[mark('fermata')]),note('b','D4',1,1,2)]);before=deepcopy(p);r=realize_project(p)
        self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,750]);self.assertEqual(r['duration_ms'],1250);self.assertEqual(p,before)

    def test_fermata_on_rest_extends_silence_not_a_note(self):
        p=project([note('a'),note('b','D4',2,1,2)],rests=[dict(id='rest',hand='right',beat=1,duration_beats=1,performance_marks=[mark('fermata')])])
        r=realize_project(p);self.assertEqual(len(r['audio_events']),2);self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,1250]);self.assertEqual(r['audio_events'][0]['duration_ms'],500)

    def test_lh_fermata_uses_known_rh_measure_anchor_not_unknown_lh_global(self):
        p=project([note('a',measure_beat=0,measure_start_beat=0),note('b','D4',2,1,2,measure_beat=2,measure_start_beat=0)],rests=[dict(id='lr',hand='left',page=1,system=1,measure=1,beat=None,measure_beat=1,duration=1,performance_marks=[mark('fermata')])])
        r=realize_project(p);self.assertFalse(r['errors']);self.assertEqual([e['t_ms'] for e in r['audio_events']],[0,1250])

    def test_same_pause_on_distinct_voice_marks_does_not_accumulate(self):
        p=project([note('a',duration=2,marks=[mark('fermata','voice1')]),note('b','E4',1,1,3,marks=[mark('fermata','voice2')]),note('c','D4',2,1,2)])
        a=audio(p);self.assertEqual(a[-1]['t_ms'],1250)

    def test_chord_fermata_group_is_not_counted_once_per_head(self):
        p=project([note('a',marks=[mark('fermata','f')]),note('b','E4',finger=3,marks=[mark('fermata','f')]),note('c','D4',1,1,2)])
        self.assertEqual(audio(p)[-1]['t_ms'],750)

    def test_21_staccato_and_staccatissimo_shorten_gate_not_next_onset(self):
        for kind,duration in [('staccato',250),('staccatissimo',125)]:
            a=audio(project([note('a',marks=[mark(kind)]),note('b','D4',1,1,2)]));self.assertEqual(a[0]['duration_ms'],duration);self.assertEqual(a[1]['t_ms'],500)

    def test_22_tenuto_and_accent_keep_meter_and_change_gate_velocity(self):
        a=audio(project([note(marks=[mark('tenuto'),mark('accent')])]))
        self.assertEqual(a[0]['duration_ms'],500);self.assertEqual(a[0]['velocity'],115)

    def test_23_octave_applied_once_and_unapplied_explicit_downward(self):
        self.assertEqual(audio(project([note(pitch='C5',marks=[mark('ottava',semitones=12,already_applied=True)])]))[0]['pitch'],72)
        self.assertEqual(audio(project([note(pitch='C5',marks=[mark('ottava',semitones=-12,already_applied=False)])]))[0]['pitch'],60)

    def test_24_pedal_sustains_audio_not_motor_or_next_onset(self):
        p=project([note('a'),note('b','D4',1,1,2)],performance_spans=[dict(id='ped',kind='pedal',start_note_id='a',end_note_id='b',options={'start_beat':0,'end_beat':2})])
        r=realize_project(p);self.assertEqual(r['audio_events'][0]['duration_ms'],1000);self.assertEqual(r['motion_events'][0]['duration_ms'],500);self.assertEqual(r['audio_events'][1]['t_ms'],500)

    def test_pedal_repeated_pitch_preserves_both_attacks_without_voice_accumulation(self):
        p=project([note('a'),note('b',beat=1)],performance_spans=[dict(id='ped',kind='pedal',start_note_id='a',options={'start_beat':0,'end_beat':2})])
        a=audio(p);self.assertEqual(len(a),2);self.assertEqual(a[0]['duration_ms'],500)

    def test_pedal_last_affected_head_is_not_the_release_anchor(self):
        p=project([note('a'),note('b','D4',1,1,2),note('c','E4',2,1,3)],performance_spans=[dict(id='p',kind='pedal',start_note_id='a',end_note_id='b',source_note_ids=['a','b'],options=dict(release_note_id='c',release_position='before_anchor'))])
        a=audio(p);self.assertEqual(a[0]['duration_ms'],1000)

    def test_group_written_override_suppresses_span_effect_and_auto_restores_it(self):
        p=project([note('a'),note('b','D4',1,1,2)],performance_spans=[dict(id='p',kind='pedal',start_note_id='a',end_note_id='b',source_note_ids=['a','b'],options=dict(start_beat=0,end_beat=2))])
        p['notes'][0]['performance_override']={'mode':'written'}
        a=audio(p);self.assertEqual(a[0]['duration_ms'],500)
        p['notes'][0]['performance_override']={'mode':'auto'}
        self.assertEqual(audio(p)[0]['duration_ms'],1000)

    def test_written_fermata_span_does_not_still_warp_global_time(self):
        p=project([note('a',measure_beat=0,measure_start_beat=0),note('b','D4',1,1,2,measure_beat=1,measure_start_beat=0)],performance_spans=[dict(id='f',kind='fermata',source_note_ids=['a'],options={'anchor_note_id':'a'})])
        p['notes'][0]['performance_override']={'mode':'written'}
        self.assertEqual(audio(p)[1]['t_ms'],500)

    def test_trailing_rest_is_retained_but_range_does_not_include_rest_of_piece(self):
        p=project([note()],rests=[dict(id='r',hand='right',beat=1,duration=2)])
        self.assertEqual(realize_project(p)['duration_ms'],1500)
        p=project([note('a'),note('b','D4',1,1,2),note('c','E4',2,1,3)],written_duration_beats=20)
        p['selection'].update(start_beat=1,end_beat=2)
        self.assertEqual(realize_project(p)['duration_ms'],500)

    def test_overrides_are_real_controls_not_source_edits(self):
        n=note(marks=[mark('staccato'),mark('accent')]);n['performance_override']=dict(gate_ratio=.75,velocity=70,reviewed=True)
        p=project([n]);before=deepcopy(p);r=realize_project(p);self.assertEqual(r['audio_events'][0]['duration_ms'],375);self.assertEqual(r['audio_events'][0]['velocity'],70);self.assertEqual(p,before)

    def test_written_unknown_grace_remains_a_real_blocker(self):
        p=self.grace('grace_short',mode='written');self.assertTrue(realize_project(p)['errors'])
        p['notes'][0]['rhythm_evidence']={'nominal_duration':.5}
        self.assertTrue(realize_project(p)['errors'])

    def test_reviewed_estimate_keeps_provenance_without_repeated_yellow_root(self):
        p=self.grace('grace_short',reviewed=True);r=realize_project(p);self.assertTrue(r['note_states']['g0']['estimated']);self.assertFalse(r['note_states']['g0']['warning_root'])

    def test_kind_override_changes_only_practice_interpretation(self):
        p=self.grace('grace_unspecified');p['notes'][0]['performance_override']={'kind':'grace_long'};before=deepcopy(p);r=realize_project(p)
        self.assertEqual(r['audio_events'][0]['duration_ms'],250);self.assertEqual(p,before)
        self.assertEqual(p['notes'][0]['performance_marks'][0]['kind'],'grace_unspecified')
        self.assertIn('kind',r['note_states']['g0']['editable_fields'])

    def test_invalid_pitches_and_durations_are_not_hidden(self):
        p=project([note(pitch='bad')]);self.assertTrue(realize_project(p)['errors'])
        p=project([note(duration=None)]);self.assertTrue(realize_project(p)['errors'])

    def test_unknown_mark_does_not_manufacture_audio(self):
        a=audio(project([note(marks=[mark('ordinary-text-digit-3')])]))
        self.assertEqual(len(a),1);self.assertEqual(a[0]['pitch'],60)

if __name__=='__main__':unittest.main()
