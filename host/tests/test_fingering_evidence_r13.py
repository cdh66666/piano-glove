"""Independent geometric fingering examples; no held-out music PDFs."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _assign_page_fingerings
from fingering_evidence import refine_fingering_evidence

def note(identity,x=100,y=100,gap=5,**extra):
    result=dict(id=identity,measure=1,origin=[x,y],hand='right',finger=None,finger_source=None,
                finger_candidates=[],issues=[],confidence=.85,pitch='C4',duration=.5,beat=1,
                rhythm_evidence=dict(stem=[x+1.2*gap,y-4*gap,y],stem_direction='up',beams=1))
    result.update(extra);return result

def digit(value,x,y=73,gap=5,music=True):
    return dict(char=chr(0x130+value) if music else str(value),font='Aloisen' if music else 'Text',
                x=x,y=y,size=1.2*gap,bbox=[x,y-.6*gap,x+.8*gap,y+.4*gap])

def run(groups,labels,*,gap=5,extra_staves=(),extra_jobs=(),text=(),lines=()):
    staff=dict(id='staff',gap=gap,heads=[]);staves=[staff,*extra_staves]
    jobs=[(staff,g,groups) for g in groups]+list(extra_jobs)
    _assign_page_fingerings(jobs,staves,labels,{},text)
    before=deepcopy([e for g in groups for e in g])
    summary=refine_fingering_evidence(jobs,staves,labels,{},text,lines)
    return before,summary,staff,jobs

class FreeStemEvidenceTests(unittest.TestCase):
    def test_reconciles_two_nearby_columns_with_two_unique_stem_labels(self):
        for factor,dx,dy in [(1,0,0),(.7,31,-15),(2.3,-70,240)]:
            with self.subTest(factor=factor):
                gap=5*factor;x=100*factor+dx;y=100*factor+dy
                a=note('a',x,y,gap);b=note('b',x+1.2*gap,y,gap,pitch='E4')
                labels=[digit(2,x+1.2*gap,y-5.4*gap,gap),digit(4,x+2.4*gap,y-5.4*gap,gap)]
                before,stats,_,_=run([[a],[b]],labels,gap=gap)
                self.assertEqual([(n['finger'],n['source_fingering_state']) for n in before],[(None,'unmarked'),(2,'printed')])
                self.assertEqual([(n['finger'],n['source_fingering_state']) for n in (a,b)],[(2,'printed'),(4,'printed')])
                self.assertEqual(stats['reconciled_pairs'],1)
                self.assertEqual((a['pitch'],a['duration'],a['beat'],b['pitch'],b['duration'],b['beat']),('C4',.5,1,'E4',.5,1))

    def test_single_displaced_free_stem_music_digit_recovers_printed_value(self):
        a=note('a');a['rhythm_evidence']['stem']=[109,80,100]
        before,stats,_,_=run([[a]],[digit(4,109)])
        self.assertEqual((before[0]['finger'],before[0]['source_fingering_state']),(None,'unmarked'))
        self.assertEqual((a['finger'],a['source_fingering_state']),(4,'printed'))
        self.assertEqual(stats['recovered'],1)

    def test_one_digit_competing_between_stem_and_neighbor_is_not_silently_gray(self):
        a=note('a');b=note('b',x=106,pitch='E4')
        before,stats,_,_=run([[a],[b]],[digit(2,106)])
        self.assertEqual([(n['finger'],n['source_fingering_state']) for n in before],[(None,'unmarked'),(2,'printed')])
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unresolved')
        self.assertEqual(b['finger'],2);self.assertEqual(stats['ownership_conflicts'],1)

    def test_ownership_ambiguity_does_not_borrow_across_hands(self):
        a=note('a');b=note('b',x=106,hand='left',pitch='E4')
        label=digit(2,106);b.update(finger=2,finger_source='printed',finger_bbox=label['bbox'],source_fingering_state='printed')
        a['source_fingering_state']='unmarked';groups=[[a],[b]];staff=dict(gap=5,heads=[])
        stats=refine_fingering_evidence([(staff,g,groups) for g in groups],[staff],[label],{},[],[])
        self.assertEqual(stats['ownership_conflicts'],0)
        self.assertIsNone(a['finger'])

    def test_visible_ordinary_text_at_free_stem_is_uncertain_not_guessed(self):
        a=note('a');label=digit(4,106,music=False)
        before,stats,_,_=run([[a]],[],text=[label])
        self.assertEqual(before[0]['source_fingering_state'],'unmarked')
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unresolved')
        self.assertEqual(stats['ambiguous'],1)

    def test_same_staff_nearer_other_note_wins_over_free_stem_candidate(self):
        a=note('a');label=digit(4,106,music=False)
        other=note('neighbor',x=106,y=73,rhythm_evidence={},glyph_bbox=label['bbox'])
        before,stats,_,_=run([[a],[other]],[],text=[label])
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unmarked')
        self.assertEqual(other['source_fingering_state'],'unresolved')

    def test_other_staff_nearer_music_ink_wins_over_free_stem_candidate(self):
        a=note('a');label=digit(4,106,music=False)
        other=note('neighbor',x=106,y=73,hand='left',rhythm_evidence={},glyph_bbox=label['bbox'])
        a['source_fingering_state']='unmarked';other['source_fingering_state']='unmarked'
        upper=dict(gap=5,heads=[]);lower=dict(gap=5,heads=[]);jobs=[(upper,[a],[[a]]),(lower,[other],[[other]])]
        refine_fingering_evidence(jobs,[upper,lower],[],{},[label],[])
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unmarked')

    def test_three_centered_beamed_notes_do_not_guess_triplet_number_as_finger(self):
        a=note('a',x=90);b=note('b',x=100);c=note('c',x=110)
        groups=[[a],[b],[c]];label=digit(3,106,music=False)
        before,stats,_,_=run(groups,[],text=[label])
        self.assertEqual(before[1]['source_fingering_state'],'unmarked')
        self.assertIsNone(b['finger']);self.assertEqual(b['source_fingering_state'],'unresolved')

    def test_explicit_tuplet_bracket_is_not_finger_evidence(self):
        a=note('a',x=90);b=note('b',x=100);c=note('c',x=110)
        groups=[[a],[b],[c]];label=digit(3,106,music=False)
        # Two capped bracket halves around a centered numeral, without needing
        # any guessed note duration or previously-recognized tuplet metadata.
        lines=[(96,70,105,70,.5),(110,70,126,70,.5),
               (96,70,96,73,.5),(126,70,126,73,.5)]
        before,stats,_,_=run(groups,[],text=[label],lines=lines)
        self.assertIsNone(b['finger']);self.assertEqual(b['source_fingering_state'],'unmarked')
        self.assertEqual(stats['bracketed_tuplets'],1)

    def test_head_aligned_existing_tuplet_warning_clears_when_bracket_proves_it(self):
        a=note('a',x=84);b=note('b',x=94);c=note('c',x=104)
        groups=[[a],[b],[c]];label=digit(3,94,music=False)
        lines=[(90,70,93,70,.5),(98,70,120,70,.5),
               (90,70,90,73,.5),(120,70,120,73,.5)]
        # Lengthen the left bracket arm enough to supply independent ink.
        lines[0]=(85,70,93,70,.5);lines[2]=(85,70,85,73,.5)
        before,stats,_,_=run(groups,[],text=[label],lines=lines)
        self.assertEqual(before[1]['source_fingering_state'],'unresolved')
        self.assertIsNone(b['finger']);self.assertEqual(b['source_fingering_state'],'unmarked')

    def test_assigned_music_glyph_with_proven_tuplet_bracket_reverts_to_no_finger(self):
        a=note('a',x=90);b=note('b',x=100);c=note('c',x=110)
        groups=[[a],[b],[c]];label=digit(3,106,music=True)
        lines=[(96,70,105,70,.5),(110,70,126,70,.5),
               (96,70,96,73,.5),(126,70,126,73,.5)]
        before,stats,_,_=run(groups,[label],lines=lines)
        self.assertEqual([n['finger'] for n in before],[None,None,3])
        self.assertEqual([n['finger'] for n in (a,b,c)],[None,None,None])
        self.assertEqual(c['source_fingering_state'],'unmarked')
        self.assertEqual(stats['incorrect_tuplet_assignments_removed'],1)

    def test_competing_other_hand_ink_is_removed_from_partial_chord_candidates(self):
        a,b,c=(note('a',y=100),note('b',y=105),note('c',y=110))
        for n in (a,b,c):n['rhythm_evidence']['stem']=[106,80,110]
        label=digit(2,106,73,music=False)
        for n in (a,b,c):
            n['source_fingering_state']='unresolved'
            n['source_fingering_evidence']=dict(method='unassigned_visible_digit',candidate_bboxes=[label['bbox']])
        other=note('other',x=106,y=73,hand='left',rhythm_evidence={},glyph_bbox=label['bbox'])
        upper=dict(gap=5,heads=[]);lower=dict(gap=5,heads=[])
        g=[a,b,c];jobs=[(upper,g,[g]),(lower,[other],[[other]])]
        refine_fingering_evidence(jobs,[upper,lower],[],{},[label],[])
        self.assertTrue(all(n['source_fingering_state']=='unmarked' and n['finger'] is None for n in g))

    def test_manual_fingering_is_never_reassigned(self):
        a=note('a');b=note('b',x=106)
        b.update(finger=2,finger_source='manual',finger_bbox=digit(2,106)['bbox'],manual_fields=['finger'])
        a['source_fingering_state']='unmarked';b['source_fingering_state']='printed'
        g=[[a],[b]];staff=dict(gap=5,heads=[]);jobs=[(staff,x,g) for x in g]
        refine_fingering_evidence(jobs,[staff],[digit(2,106),digit(4,112)],{},[],[])
        self.assertEqual((a['finger'],b['finger']),(None,2))

    def test_excluded_source_event_is_not_modified(self):
        a=note('excluded',excluded=True);a['source_fingering_state']='unmarked'
        label=digit(4,106);staff=dict(gap=5,heads=[]);group=[a];before=deepcopy(a)
        refine_fingering_evidence([(staff,group,[group])],[staff],[label],{},[],[])
        self.assertEqual(a,before)

    def test_other_staff_head_near_long_stem_digit_prevents_wrong_assignment(self):
        for factor,dx,dy in [(1,0,0),(.6,31,-15),(2.4,-70,210)]:
            with self.subTest(factor=factor):
                gap=5*factor;x=100*factor+dx;y=100*factor+dy
                top=note('right',x,y,gap,glyph_bbox=[x,y-.5*gap,x+gap,y+.5*gap])
                top['rhythm_evidence']=dict(stem=[x+1.2*gap,y,y+4*gap],stem_direction='down',beams=0)
                lab=digit(1,x+1.2*gap,y+5*gap,gap)
                bottom=note('left',x+1.2*gap,y+6.2*gap,gap,hand='left',
                    glyph_bbox=[x+1.2*gap,y+6*gap,x+2.2*gap,y+7*gap],
                    rhythm_evidence=dict(stem=[x+1.2*gap,y+6.2*gap,y+10*gap],stem_direction='down',beams=0))
                for e in (top,bottom):e['source_fingering_state']='unmarked';e['source_fingering_evidence']={'candidate_bboxes':[]}
                upper=dict(gap=gap,heads=[]);lower=dict(gap=gap,heads=[])
                jobs=[(upper,[top],[[top]]),(lower,[bottom],[[bottom]])]
                refine_fingering_evidence(jobs,[upper,lower],[lab],{},[],[])
                self.assertIsNone(top['finger']);self.assertEqual(top['source_fingering_state'],'unmarked')

    def test_distinct_other_hand_finger_does_not_hide_right_hand_stem_label(self):
        gap=5;x=100;y=100
        top=note('right',x,y,gap,glyph_bbox=[x,97.5,x+5,102.5])
        top['rhythm_evidence']=dict(stem=[106,100,120],stem_direction='down',beams=0)
        upper_label=digit(1,106,124,gap)
        bottom=note('left',x+6,136,gap,hand='left',glyph_bbox=[106,135,111,140],
            rhythm_evidence=dict(stem=[106,136,155],stem_direction='down',beams=0))
        lower_label=digit(3,106,132,gap)
        bottom.update(finger=3,finger_source='printed',finger_bbox=lower_label['bbox'],source_fingering_state='printed')
        top['source_fingering_state']='unmarked';top['source_fingering_evidence']={'candidate_bboxes':[]}
        upper=dict(gap=gap,heads=[]);lower=dict(gap=gap,heads=[])
        jobs=[(upper,[top],[[top]]),(lower,[bottom],[[bottom]])]
        refine_fingering_evidence(jobs,[upper,lower],[upper_label,lower_label],{},[],[])
        self.assertEqual((top['finger'],bottom['finger']),(1,3))

    def test_duplicate_owned_ink_with_small_offset_is_not_unclaimed(self):
        for factor,dx,dy in [(1,0,0),(.6,31,-15),(2.4,-70,210)]:
            with self.subTest(factor=factor):
                gap=5*factor;x=100*factor+dx;y=100*factor+dy
                top=note('right',x,y,gap);label=digit(1,x+1.2*gap,y-5.4*gap,gap)
                duplicate=deepcopy(label);duplicate['y']+=.02*gap
                duplicate['bbox']=[v+(.02*gap if i in (1,3) else 0) for i,v in enumerate(label['bbox'])]
                bottom=note('left',x+1.2*gap,y+8*gap,gap,hand='left')
                bottom.update(finger=1,finger_source='printed',finger_bbox=duplicate['bbox'],source_fingering_state='printed')
                top['source_fingering_state']='unresolved'
                top['source_fingering_evidence']={'method':'unassigned_free_stem_digit_requires_review','candidate_bboxes':[label['bbox']]}
                upper=dict(gap=gap,heads=[]);lower=dict(gap=gap,heads=[])
                refine_fingering_evidence([(upper,[top],[[top]]),(lower,[bottom],[[bottom]])],
                                          [upper,lower],[label,duplicate],{},[],[])
                self.assertIsNone(top['finger']);self.assertEqual(top['source_fingering_state'],'unmarked')
                self.assertEqual(bottom['finger'],1)

    def test_nearly_overlapping_different_numbers_are_not_merged_or_guessed(self):
        gap=5;a=note('right');a['source_fingering_state']='unmarked';a['source_fingering_evidence']={'candidate_bboxes':[]}
        first=digit(1,106,73,gap);second=digit(4,106+.03*gap,73+.03*gap,gap)
        owner=note('other',x=150,y=110,gap=gap)
        owner.update(finger=1,finger_source='printed',finger_bbox=first['bbox'],source_fingering_state='printed')
        staff=dict(gap=gap,heads=[]);groups=[[a],[owner]]
        refine_fingering_evidence([(staff,g,groups) for g in groups],[staff],[first,second],{},[],[])
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unresolved')
        self.assertEqual(owner['finger'],1)

    def test_note_with_no_visible_digit_stays_gray(self):
        a=note('a');before,stats,_,_=run([[a]],[])
        self.assertEqual(a['source_fingering_state'],'unmarked');self.assertIsNone(a['finger'])

    def test_recognized_tuplet_marker_is_never_reused(self):
        a=note('a');label=digit(3,106,music=False)
        a['rhythm_evidence']['tuplet']=dict(marker_bbox=label['bbox'])
        before,stats,_,_=run([[a]],[],text=[label])
        self.assertEqual(a['source_fingering_state'],'unmarked');self.assertIsNone(a['finger'])

    def test_owned_digit_never_borrowed_across_hands(self):
        a=note('a');other=note('other',hand='left');label=digit(3,106,music=False)
        other.update(finger=3,finger_bbox=label['bbox'])
        staff=dict(gap=5,heads=[]);upper=[a];lower=[other]
        jobs=[(staff,upper,[upper]),(staff,lower,[lower])]
        a['source_fingering_state']='unmarked';other['source_fingering_state']='printed'
        refine_fingering_evidence(jobs,[staff],[],{},[label],[])
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unmarked');self.assertEqual(other['finger'],3)

    def test_partial_chord_never_assigned_from_two_ambiguous_digits(self):
        notes=[note('a',y=90),note('b',y=100),note('c',y=110)]
        for n in notes:n['rhythm_evidence']['stem']=[106,70,110]
        labels=[digit(2,106,63,music=False),digit(4,106,56,music=False)]
        before,stats,_,_=run([notes],[],text=labels)
        self.assertEqual([n['finger'] for n in notes],[None,None,None])
        self.assertTrue(all(n['source_fingering_state']=='unresolved' for n in notes))

    def test_text_in_word_or_multi_digit_number_is_not_a_finger(self):
        a=note('a');label=digit(2,106,music=False)
        neighbor=dict(char='1',font='Text',x=label['bbox'][0]-3,y=label['y'],size=6,
                      bbox=[label['bbox'][0]-3,label['bbox'][1],label['bbox'][0]-.5,label['bbox'][3]])
        before,stats,_,_=run([[a]],[],text=[label,neighbor])
        self.assertIsNone(a['finger']);self.assertEqual(a['source_fingering_state'],'unmarked')

if __name__=='__main__':unittest.main()
