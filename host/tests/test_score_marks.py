"""Synthetic notation and ownership cases; no customer PDF is accessed."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'candidate' if (HERE/'candidate/score_marks.py').is_file() else HERE.parent))
from score_marks import annotate_performance_page,finalize_performance_spans

def fixture():
    staff=dict(id='p1-s1',page=1,system=1,hand='right',left=20,right=400,top=100,bottom=140,gap=10,
        bbox=[20,100,400,140],key_signature={'F':1})
    project=dict(notes=[],rests=[],staves=[dict(staff)],performance_spans=[])
    return project,[staff],[],[],[]

def note(project,x=100,y=130,pitch='E4',midi=64,duration=1,beat=0,staff='p1-s1',hand='right',**other):
    ident=other.pop('id','n'+str(len(project['notes'])+1))
    value=dict(id=ident,page=1,system=1,staff=staff,hand=hand,measure=1,origin=[x,y],glyph_bbox=[x,y-4,x+12,y+4],bbox=[x-2,y-5,x+14,y+5],
        pitch=pitch,written_pitch=pitch,midi=midi,duration=duration,beats=duration,measure_beat=beat,
        rhythm_evidence={'head':'filled','stem':[x+10,y-35,y],'stem_direction':'up','beams':0,'dots':0},issues=[])
    value.update(other);project['notes'].append(value);return value

def glyph(char,x=100,y=85,font='Aloisen',width=10,height=10):
    return dict(char=char,x=x,y=y,bbox=[x,y-height,x+width,y],size=20,font=font)

def text(word,x=100,y=85,size=10):
    return [dict(char=c,x=x+i*size*.5,y=y,bbox=[x+i*size*.5,y-size,x+(i+1)*size*.5,y],size=size,font='TimesNewRoman') for i,c in enumerate(word)]

def apply(f):
    p,s,c,l,curves=f;annotate_performance_page(p,1,s,c,c,l,curves);finalize_performance_spans(p);return p

def kinds(n):return {m['kind'] for m in n.get('performance_marks',[])}

class PrintedMarksTests(unittest.TestCase):
    def test_verified_aloisen_symbols(self):
        pairs=[('\u01a0','trill'),('\u01a3','mordent_upper'),('\u01a4','mordent_lower'),('\u01a6','turn'),
               ('\u01b2','fermata'),('\u01b3','fermata'),('\u01c0','accent'),('\u01c7','staccato'),('\u01c8','tenuto')]
        for char,kind in pairs:
            with self.subTest(kind=kind):
                f=fixture();n=note(f[0]);f[2].append(glyph(char));source=deepcopy(n);apply(f)
                self.assertIn(kind,kinds(n));self.assertEqual({k:n[k] for k in source},source)
                mark=next(m for m in n['performance_marks'] if m['kind']==kind)
                self.assertEqual(mark['source']['page'],1);self.assertEqual(mark['source']['bbox'],[100.,75.,110.,85.])

    def test_inverse_turn_and_staccatissimo_standard_smufl(self):
        for char,kind in [('\ue568','inverted_turn'),('\ue4a6','staccatissimo'),('\ue4a9','staccatissimo')]:
            f=fixture();n=note(f[0]);f[2].append(glyph(char,font='Bravura'));apply(f);self.assertIn(kind,kinds(n))

    def test_unicode_trill_independent_of_font_family(self):
        f=fixture();n=note(f[0]);f[2].append(glyph('\U0001d196',font='MusicUnicode'));apply(f);self.assertIn('trill',kinds(n))

    def test_pdfium_utf16_surrogate_pair_decodes_one_printed_music_scalar(self):
        f=fixture();n=note(f[0]);f[2].extend([glyph('\ud834',font='NotoMusic'),glyph('\udd98',font='NotoMusic')]);apply(f)
        self.assertIn('inverted_turn',kinds(n));mark=next(m for m in n['performance_marks'] if m['kind']=='inverted_turn');self.assertEqual(mark['source']['char'],'\U0001d198')

    def test_surrogates_at_different_origins_are_not_joined(self):
        f=fixture();n=note(f[0]);f[2].extend([glyph('\ud834',font='NotoMusic'),glyph('\udd98',x=130,font='NotoMusic')]);apply(f)
        self.assertNotIn('inverted_turn',kinds(n))

    def test_private_codes_in_non_music_fonts_are_not_smufl(self):
        f=fixture();n=note(f[0]);f[2].append(glyph('\ue566',font='BodyPrivate'));apply(f);self.assertNotIn('trill',kinds(n))

    def test_wrong_font_does_not_decode_aloisen_letters(self):
        f=fixture();n=note(f[0]);f[2].append(glyph('\u01a0',font='OrdinaryBody'));apply(f);self.assertNotIn('trill',kinds(n))

    def test_augmentation_dot_is_not_staccato(self):
        f=fixture();n=note(f[0]);n['rhythm_evidence']['dots']=1
        f[2].append(glyph('\u01c7',x=117,y=132,width=2,height=3));apply(f)
        self.assertIn('dots',kinds(n));self.assertNotIn('staccato',kinds(n))

    def test_combined_accent_dot_emits_two_real_articulations(self):
        f=fixture();n=note(f[0]);f[2].append(glyph('\u01c1'));apply(f);self.assertTrue({'accent','staccato'}<=kinds(n))

    def test_trill_text_boundary_and_title_exclusion(self):
        for word,y,expected in [('tr',85,True),('tr.',85,True),('intro',85,False),('tr',0,False),('string',85,False)]:
            f=fixture();n=note(f[0]);f[2].extend(text(word,y=y));apply(f);self.assertEqual('trill' in kinds(n),expected,(word,y))

    def test_trill_auxiliary_accidental_is_not_principal_accidental(self):
        f=fixture();n=note(f[0]);f[2].extend([glyph('\u01a0'),glyph('\u0121',x=101,y=63,width=8,height=12)])
        apply(f);mark=next(m for m in n['performance_marks'] if m['kind']=='trill');self.assertEqual(mark['options']['auxiliary_accidental'],1)
        self.assertEqual(n['pitch_context']['key_signature'],{'F':1})

    def test_delayed_turn_between_two_written_attacks_belongs_to_preceding(self):
        f=fixture();a=note(f[0],x=70);b=note(f[0],x=210,pitch='F4',midi=65,beat=1)
        f[2].append(glyph('\u01a6',x=135));apply(f)
        mark=next(m for m in a['performance_marks'] if m['kind']=='turn');self.assertTrue(mark['options']['delayed']);self.assertEqual(mark['options']['next_anchor_id'],b['id'])
        self.assertNotIn('turn',kinds(b))

    def test_between_bar_turn_not_assigned_to_previous_measure(self):
        f=fixture();a=note(f[0],x=70);note(f[0],x=210,measure=2);f[2].append(glyph('\u01a6',x=135));apply(f)
        self.assertNotIn('turn',kinds(a))

    def test_ambiguous_multiple_auxiliary_accidentals_are_not_guessed(self):
        f=fixture();n=note(f[0]);f[2].extend([glyph('\u01a0'),glyph('\u0121',x=101,y=63,width=8,height=12),glyph('\u0122',x=106,y=62,width=8,height=12)])
        apply(f);mark=next(m for m in n['performance_marks'] if m['kind']=='trill');self.assertNotIn('auxiliary_accidental',mark['options'])

    def test_turn_upper_and_lower_accidentals_are_separate_neighbors(self):
        for kind,char in [('turn','\u01a6'),('inverted_turn','\ue568')]:
            f=fixture();n=note(f[0]);f[2].extend([glyph(char,font='Aloisen' if kind=='turn' else 'Bravura'),glyph('\u0121',x=101,y=63,width=8,height=12),glyph('\u0122',x=101,y=105,width=8,height=12)])
            apply(f);mark=next(m for m in n['performance_marks'] if m['kind']==kind)
            self.assertEqual(mark['options']['upper_auxiliary_accidental'],1);self.assertEqual(mark['options']['lower_auxiliary_accidental'],-1);self.assertNotIn('auxiliary_accidental',mark['options'])

    def test_principal_accidental_not_used_as_lower_turn_auxiliary(self):
        f=fixture();n=note(f[0]);f[2].extend([glyph('\u01a6'),glyph('\u0121',x=85,y=132,width=8,height=12)])
        apply(f);mark=next(m for m in n['performance_marks'] if m['kind']=='turn');self.assertNotIn('lower_auxiliary_accidental',mark['options'])

    def test_arpeggio_all_chord_members_and_direction(self):
        f=fixture();a=note(f[0],y=115,issues=['arpeggio_requires_review']);b=note(f[0],y=135,pitch='C4',midi=60,issues=['arpeggio_requires_review'])
        f[2].extend([glyph('\u01ac',x=78,y=144,width=10,height=40),glyph('↓',x=78,y=145,font='TimesNewRoman')]);apply(f)
        ma=[m for m in a['performance_marks'] if m['kind']=='arpeggio'];mb=[m for m in b['performance_marks'] if m['kind']=='arpeggio']
        self.assertEqual(len(ma),1);self.assertEqual(len(mb),1);self.assertEqual(ma[0]['group_id'],mb[0]['group_id']);self.assertEqual(ma[0]['options']['direction'],'down')

    def test_displaced_second_shared_stem_keeps_one_arpeggio_attack(self):
        f=fixture();a=note(f[0],x=100,y=130);b=note(f[0],x=110,y=125,pitch='F4',midi=65)
        b['rhythm_evidence']['stem']=list(a['rhythm_evidence']['stem'])
        f[2].append(glyph('\u01ac',x=78,y=144,width=10,height=40));apply(f)
        ma=next(m for m in a['performance_marks'] if m['kind']=='arpeggio');mb=next(m for m in b['performance_marks'] if m['kind']=='arpeggio');self.assertEqual(ma['group_id'],mb['group_id'])

    def test_mark_owned_by_nearest_staff_not_row_parity(self):
        f=fixture();s=dict(f[1][0],id='p1-s2',hand='left',top=210,bottom=250,bbox=[20,210,400,250]);f[1].append(s);f[0]['staves'].append(dict(s))
        a=note(f[0]);b=note(f[0],y=235,staff='p1-s2',hand='left');f[2].append(glyph('\u01a0',y=205));apply(f)
        self.assertNotIn('trill',kinds(a));self.assertIn('trill',kinds(b))

    def test_written_values_unchanged_by_all_expression_marks(self):
        f=fixture();n=note(f[0],duration=1.5,beat=.5);before={k:n[k] for k in ('pitch','midi','duration','beats','measure_beat')}
        f[2].extend(glyph(c,x=100+i*2) for i,c in enumerate(['\u01a0','\u01b2','\u01c0','\u01c7']))
        apply(f);self.assertEqual({k:n[k] for k in before},before)


class StructuredMarksTests(unittest.TestCase):
    def test_short_grace_with_anchor(self):
        f=fixture();g=note(f[0],x=80,grace_kind='slashed',grace_group='g',main_anchor_id='main',duration=None,grace_order=0);note(f[0],id='main',x=120)
        apply(f);m=next(m for m in g['performance_marks'] if m['kind']=='grace_short');self.assertEqual(m['options']['anchor_id'],'main')

    def test_multiple_graces_are_one_ordered_group(self):
        f=fixture();a=note(f[0],x=70,grace_kind='slashed',grace_group='g',main_anchor_id='main',duration=None,grace_order=0)
        b=note(f[0],x=85,grace_kind='slashed',grace_group='g',main_anchor_id='main',duration=None,grace_order=1);note(f[0],id='main',x=120)
        apply(f);self.assertIn('grace_cluster',kinds(a));self.assertEqual(a['performance_marks'][0]['options']['member_ids'],['n1','n2']);self.assertIn('grace_cluster',kinds(b))

    def test_unslashed_grace_not_claimed_certain_long(self):
        f=fixture();g=note(f[0],x=100,grace_kind='unmeasured',grace_group='g',main_anchor_id='main',duration=None);note(f[0],id='main',x=140)
        apply(f);self.assertIn('grace_unspecified',kinds(g));self.assertNotIn('grace_long',kinds(g));self.assertTrue(g['performance_marks'][0]['options']['semantic_estimated'])

    def test_explicit_appoggiatura_text_selects_long_without_changing_duration(self):
        f=fixture();g=note(f[0],x=100,grace_kind='unmeasured',grace_group='g',main_anchor_id='main',duration=None);note(f[0],id='main',x=160)
        f[2].extend(text('appoggiatura'));apply(f);self.assertIn('grace_long',kinds(g));self.assertIsNone(g['duration'])

    def test_post_grace_suffix_only_not_intervening_regular_note(self):
        f=fixture();a=note(f[0],x=100);g=note(f[0],x=135,duration=.5,issues=['grace_or_cue_note_requires_review']);apply(f)
        m=next(m for m in g['performance_marks'] if m['kind']=='grace_after');self.assertEqual(m['options']['anchor_id'],a['id']);self.assertEqual(g['duration'],.5)
        f=fixture();note(f[0],x=100);g=note(f[0],x=135,duration=.5,issues=['grace_or_cue_note_requires_review']);note(f[0],x=170);apply(f)
        self.assertNotIn('grace_after',kinds(g))

    def test_existing_tuplet_double_dot_syncopation_and_tie(self):
        f=fixture();a=note(f[0],x=100,beat=.5,duration=1.5,tie_to_candidate='b');note(f[0],x=150,id='b',pitch='E4',midi=64,beat=2)
        a['rhythm_evidence'].update(dots=2,tuplet={'actual':3,'normal':2,'nominal_duration_beats':.5,'method':'printed_number'})
        apply(f);self.assertTrue({'tuplet','dots','syncopation','tie'}<=kinds(a))

    def test_existing_two_chord_tremolo_kept_without_rewriting_notes(self):
        f=fixture();a=note(f[0],tremolo_group='t',tremolo_side=0,tremolo_step_beats=.125,tremolo_span_beats=4)
        apply(f);m=next(m for m in a['performance_marks'] if m['kind']=='tremolo_alternating');self.assertEqual(m['options']['step_beats'],.125)

    def test_broken_chord_written_sequence(self):
        f=fixture();a=note(f[0],x=60,pitch='C4',midi=60,duration=.5);b=note(f[0],x=100,pitch='E4',midi=64,duration=.5);c=note(f[0],x=140,pitch='G4',midi=67,duration=.5)
        apply(f);self.assertIn('broken_chord',kinds(a));self.assertIn('broken_chord',kinds(b));self.assertIn('broken_chord',kinds(c))

    def test_stepwise_scale_not_relabelled_broken_chord(self):
        f=fixture();a=note(f[0],x=60,pitch='C4',midi=60,duration=.5);note(f[0],x=100,pitch='D4',midi=62,duration=.5);note(f[0],x=140,pitch='E4',midi=64,duration=.5)
        apply(f);self.assertNotIn('broken_chord',kinds(a))

    def test_single_tremolo_parallel_internal_strokes(self):
        for count in (1,2,3):
            f=fixture();n=note(f[0],y=140);n['rhythm_evidence']['stem']=[110,90,140]
            f[3].extend((103,109+i*8,117,103+i*8,4) for i in range(count));apply(f)
            m=next(m for m in n['performance_marks'] if m['kind']=='tremolo_single');self.assertEqual(m['options']['strokes'],count)

    def test_shared_tip_beam_is_not_single_tremolo(self):
        f=fixture();a=note(f[0],x=100);b=note(f[0],x=140);f[3].append((110,95,150,95,4));apply(f)
        self.assertNotIn('tremolo_single',kinds(a));self.assertNotIn('tremolo_single',kinds(b))

    def test_octave_is_already_applied(self):
        f=fixture();n=note(f[0],octave_shift=-12,octave_evidence={'marker_bbox':[80,150,110,165]});apply(f)
        m=next(m for m in n['performance_marks'] if m['kind']=='ottava');self.assertTrue(m['options']['applied_to_pitch']);self.assertEqual(m['options']['semitones'],-12)

    def test_glissando_text_requires_a_connection_not_just_a_word(self):
        f=fixture();a=note(f[0],x=60);b=note(f[0],x=200,pitch='C6',midi=84);f[2].extend(text('gliss.',x=100));f[3].append((70,125,195,80,1));apply(f)
        self.assertIn('glissando',kinds(a));self.assertIn('glissando',kinds(b))
        f=fixture();a=note(f[0],x=60);note(f[0],x=200);f[2].extend(text('gliss.',x=100));apply(f);self.assertNotIn('glissando',kinds(a))

    def test_slur_distinct_pitches(self):
        f=fixture();a=note(f[0],x=100);b=note(f[0],x=160,pitch='F4',midi=65);f[4].append([106,102,166,113]);apply(f)
        self.assertIn('slur',kinds(a));self.assertIn('slur',kinds(b))

    def test_tie_arc_is_not_also_slur(self):
        f=fixture();a=note(f[0],x=100,tie_to_candidate='b');b=note(f[0],x=160,id='b');f[4].append([106,102,166,113]);apply(f)
        self.assertIn('tie',kinds(a));self.assertNotIn('slur',kinds(a));self.assertNotIn('slur',kinds(b))

    def test_fermata_on_rest_and_shared_ending(self):
        f=fixture();a=note(f[0],x=100,duration=4,beat=0)
        rest=dict(id='r1',page=1,system=1,staff='p1-s1',hand='right',measure=1,origin=[170,120],duration=4,measure_beat=0,issues=[])
        f[0]['rests'].append(rest);f[2].extend([glyph('\u01b2',x=100),glyph('\u01b2',x=170)])
        apply(f);ma=next(m for m in a['performance_marks'] if m['kind']=='fermata');mr=next(m for m in rest['performance_marks'] if m['kind']=='fermata');self.assertEqual(ma['group_id'],mr['group_id'])
        pause=[s for s in f[0]['performance_spans'] if s['kind']=='fermata'];self.assertEqual(len(pause),1)
        self.assertEqual(pause[0]['options']['anchor_note_id'],a['id']);self.assertEqual(pause[0]['options']['anchor_rest_id'],'r1');self.assertEqual(pause[0]['options']['local_end_beat'],4)

    def test_left_rest_fermata_can_anchor_global_right_hand_pause(self):
        f=fixture();a=note(f[0],duration=4,beat=0)
        s=dict(f[1][0],id='p1-s2',hand='left',top=210,bottom=250,bbox=[20,210,400,250]);f[1].append(s);f[0]['staves'].append(dict(s))
        rest=dict(id='r1',page=1,system=1,staff='p1-s2',hand='left',measure=1,origin=[100,230],duration=4,measure_beat=0,issues=[])
        f[0]['rests'].append(rest);f[2].append(glyph('\u01b2',x=100,y=200));apply(f)
        pause=next(s for s in f[0]['performance_spans'] if s['kind']=='fermata')
        self.assertEqual(pause['options']['anchor_rest_id'],'r1');self.assertEqual(pause['source_note_ids'],[a['id']])
        self.assertNotIn('fermata',kinds(a))


class PedalAndProvenanceTests(unittest.TestCase):
    def two_staff(self):
        f=fixture();s=dict(f[1][0],id='p1-s2',hand='left',top=210,bottom=250,bbox=[20,210,400,250]);f[1].append(s);f[0]['staves'].append(dict(s))
        note(f[0],x=60,y=235,staff='p1-s2',hand='left')
        for x,b in [(60,0),(100,1),(200,2),(300,3)]:note(f[0],x=x,beat=b)
        return f

    def test_pedal_down_and_release_star(self):
        f=self.two_staff();f[2].extend([glyph('\u01d0',x=30,y=310,width=30,height=14),glyph('*',x=199,y=310,font='TimesNewRoman',width=4,height=12)]);apply(f)
        spans=[s for s in f[0]['performance_spans'] if s['kind']=='pedal'];self.assertEqual(len(spans),1)
        self.assertEqual(len(spans[0]['source_note_ids']),2);self.assertEqual(spans[0]['options']['release_note_id'],'n4');self.assertFalse(spans[0]['options']['end_estimated'])
        self.assertEqual(spans[0]['source']['staff'],'p1-s2')

    def test_pedal_open_end_is_marked_estimated(self):
        f=self.two_staff();f[2].append(glyph('\u01d0',x=30,y=310,width=30,height=14));apply(f)
        span=next(s for s in f[0]['performance_spans'] if s['kind']=='pedal');self.assertTrue(span['options']['end_estimated'])

    def test_star_without_pedal_has_no_effect(self):
        f=self.two_staff();f[2].append(glyph('*',x=199,y=310,font='TimesNewRoman'));apply(f);self.assertFalse(any(s['kind']=='pedal' for s in f[0]['performance_spans']))

    def test_pedal_line_end_hook(self):
        f=self.two_staff();f[2].append(glyph('\u01d0',x=30,y=310,width=30,height=14));f[3].extend([(65,306,200,306,1),(200,306,200,296,1)]);apply(f)
        span=next(s for s in f[0]['performance_spans'] if s['kind']=='pedal');self.assertEqual(span['options']['release_note_id'],'n4')

    def test_pedal_below_left_measure_rest_still_affects_right_notes(self):
        f=self.two_staff();f[0]['notes']=[n for n in f[0]['notes'] if n['hand']=='right']
        f[0]['rests'].append(dict(id='r1',page=1,system=1,staff='p1-s2',hand='left',measure=1,origin=[60,230],duration=4,measure_beat=0,issues=[]))
        f[2].append(glyph('\u01d0',x=30,y=310,width=30,height=14));apply(f)
        self.assertTrue(any(s['kind']=='pedal' for s in f[0]['performance_spans']))

    def test_wrong_way_pedal_hook_does_not_establish_precise_end(self):
        f=self.two_staff();f[2].append(glyph('\u01d0',x=30,y=310,width=30,height=14));f[3].extend([(65,306,200,306,1),(200,306,200,316,1)]);apply(f)
        span=next(s for s in f[0]['performance_spans'] if s['kind']=='pedal');self.assertTrue(span['options']['end_estimated'])

    def test_cross_page_pedal_source_box_keeps_original_page(self):
        f=self.two_staff();f[2].append(glyph('\u01d0',x=30,y=310,width=30,height=14));p,s,c,l,curves=f
        annotate_performance_page(p,1,s,c,c,l,curves)
        s2=[dict(st,page=2,id=st['id'].replace('p1','p2')) for st in s];p['staves'].extend(deepcopy(s2))
        future=note(p,x=100,staff='p2-s1',page=2,beat=4);last=note(p,x=200,staff='p2-s1',page=2,beat=5)
        other=note(p,x=60,y=235,staff='p2-s2',hand='left',page=2,beat=4)
        up=glyph('\ue655',x=200,y=310,font='Bravura')
        annotate_performance_page(p,2,s2,[up],[up],[],[]);finalize_performance_spans(p)
        mark=next(m for m in future['performance_marks'] if m['kind']=='pedal');self.assertEqual(mark['source']['page'],1);self.assertEqual(mark['source']['system'],1)
        self.assertNotIn('pedal',kinds(last))

    def test_scaled_and_translated_marks_have_same_semantics(self):
        for scale,dx,dy in [(1,0,0),(2.5,42,19),(.7,13,43)]:
            f=fixture();n=note(f[0]);f[2].append(glyph('\u01a3'))
            for staff in f[1]:
                for key in ('left','right'):staff[key]=staff[key]*scale+dx
                for key in ('top','bottom'):staff[key]=staff[key]*scale+dy
                staff['gap']*=scale;staff['bbox']=[staff['left'],staff['top'],staff['right'],staff['bottom']]
            f[0]['staves']=deepcopy(f[1])
            for event in f[0]['notes']:
                event['origin']=[event['origin'][0]*scale+dx,event['origin'][1]*scale+dy]
                for key in ('bbox','glyph_bbox'):event[key]=[v*scale+(dx if i%2==0 else dy) for i,v in enumerate(event[key])]
                x,lo,hi=event['rhythm_evidence']['stem'];event['rhythm_evidence']['stem']=[x*scale+dx,lo*scale+dy,hi*scale+dy]
            for c in f[2]:
                c['x']=c['x']*scale+dx;c['y']=c['y']*scale+dy;c['size']*=scale;c['bbox']=[v*scale+(dx if i%2==0 else dy) for i,v in enumerate(c['bbox'])]
            apply(f);self.assertIn('mordent_upper',kinds(n))

if __name__=='__main__':unittest.main()
