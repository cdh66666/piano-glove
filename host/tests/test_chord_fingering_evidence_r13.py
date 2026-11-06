"""Source-independent examples for complete printed chord-label columns."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST));sys.path.insert(0,str(HOST/'tests'))
from test_fingering_evidence_r13 import note,digit
import fingering_evidence as candidate

def example(values=(5,2),extra=False,manual=False,scale=1,dx=0,dy=0,head_shift=False):
    gap=5*scale;x=100*scale+dx;y=100*scale+dy
    stem=[x+1.2*gap,y,y+4*gap]
    group=[]
    for i,_ in enumerate(values):
        n=note('rh-'+str(i),x+(.8*gap if head_shift and i==1 else 0),y+i*gap,gap,
               rhythm_evidence=dict(stem=stem,stem_direction='down',beams=1),
               source_fingering_state='unmarked',source_fingering_evidence={'candidate_bboxes':[]})
        group.append(n)
    marks=[digit(value,stem[0],stem[2]+1.26*gap+i*1.2*gap,gap) for i,value in enumerate(values)]
    # Mirror the current partial-column defect: the first digit was allocated
    # to the bottom head, while the rest of this real chord stayed gray.
    group[-1].update(finger=values[0],finger_source='printed',finger_bbox=marks[0]['bbox'],source_fingering_state='printed')
    if manual:group[-1].update(finger_source='manual',manual_fields=['finger'])
    upper=dict(gap=gap,heads=[]);lower=dict(gap=gap,heads=[])
    left=note('left',stem[0],stem[2]+(len(values)*1.2+3)*gap,gap,hand='left',
              rhythm_evidence=dict(stem=[stem[0],stem[2]+(len(values)*1.2+3)*gap,stem[2]+(len(values)*1.2+7)*gap],stem_direction='down',beams=0))
    left_mark=digit(1,stem[0],stem[2]+(len(values)*1.2+2.46)*gap,gap)
    left.update(finger=1,finger_source='printed',finger_bbox=left_mark['bbox'],source_fingering_state='printed')
    labels=marks+[left_mark]
    if extra:labels.append(digit(3,stem[0],stem[2]+(len(values)*1.2+1.26)*gap,gap))
    jobs=[(upper,group,[group]),(lower,[left],[[left]])]
    return group,left,labels,jobs,gap

def run(g,left,labels,jobs):
    # Call the production-facing interface: already identified fingering and
    # source evidence have been prepared by the ordinary recognizer.
    return candidate.refine_fingering_evidence(jobs,[j[0] for j in jobs],labels,{},[],[])

class CompleteChordEvidenceTests(unittest.TestCase):
    def test_two_note_five_two_is_reordered_by_proven_full_column(self):
        for s,dx,dy in [(1,0,0),(.55,31,-14),(2.7,-80,240)]:
            with self.subTest(scale=s):
                group,left,marks,jobs,_=example(scale=s,dx=dx,dy=dy,head_shift=True)
                result=run(group,left,marks,jobs)
                self.assertEqual([n['finger'] for n in group],[5,2])
                self.assertEqual(left['finger'],1);self.assertEqual(result['chord_heads_recovered'],1)

    def test_three_note_five_two_one_and_other_hand_label(self):
        group,left,marks,jobs,_=example((5,2,1))
        # The neighboring hand uses its own separate 4 and does not consume RH 1.
        left_label=digit(4,marks[-1]['x'],marks[-1]['y'],5)
        left['finger']=4;left['finger_bbox']=left_label['bbox'];marks[-1]=left_label
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[5,2,1]);self.assertEqual(left['finger'],4)
        self.assertEqual(result['chord_heads_recovered'],2)

    def test_incomplete_column_does_not_guess_or_reorder(self):
        group,left,marks,jobs,_=example((5,2,1));marks.pop(1)
        before=[n.get('finger') for n in group]
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],before)
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_extra_unowned_digit_prevents_a_guessed_subset(self):
        group,left,marks,jobs,_=example((5,2),extra=True)
        before=[n.get('finger') for n in group]
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],before)
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_manual_digit_is_never_changed(self):
        group,left,marks,jobs,_=example((5,2),manual=True)
        before=deepcopy(group)
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[n['finger'] for n in before])
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_duplicate_drawing_does_not_create_extra_label(self):
        group,left,marks,jobs,gap=example((5,2))
        duplicate=deepcopy(marks[1]);duplicate['y']+=.02*gap
        duplicate['bbox']=[x+(.02*gap if i in (1,3) else 0) for i,x in enumerate(duplicate['bbox'])]
        marks.append(duplicate)
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[5,2])
        self.assertEqual(result['reconciled_chord_columns'],1)

    def test_column_ownership_is_recomputed_and_repeated_pass_is_idempotent(self):
        group,left,marks,jobs,_=example((5,2))
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[5,2])
        owned=[tuple(n['finger_bbox']) for n in [*group,left]]
        self.assertEqual(len(set(owned)),len(owned))
        before=deepcopy([*group,left]);run(group,left,marks,jobs)
        self.assertEqual([*group,left],before)

    def test_other_unresolved_voice_sharing_candidate_stem_blocks_reassignment(self):
        group,left,marks,jobs,gap=example((5,2));staff=jobs[0][0]
        rival=note('other-voice',100,101,gap,
            rhythm_evidence=dict(stem=group[0]['rhythm_evidence']['stem'],stem_direction='down',beams=1),
            source_fingering_state='unmarked',source_fingering_evidence={'candidate_bboxes':[]})
        jobs.insert(1,(staff,[rival],[group,[rival]]))
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[None,5])
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_two_close_but_different_glyphs_are_not_deduplicated(self):
        group,left,marks,jobs,gap=example((5,2))
        overlapping=digit(3,marks[1]['x']+.02*gap,marks[1]['y']+.02*gap,gap);marks.append(overlapping)
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[None,5])
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_label_explicitly_claimed_by_other_hand_is_not_taken(self):
        group,left,marks,jobs,_=example((5,2));left['finger']=2;left['finger_bbox']=marks[1]['bbox'];marks.pop()
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[None,5]);self.assertEqual(left['finger'],2)
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_rhythmic_bracket_number_cannot_complete_a_finger_column(self):
        group,left,marks,jobs,_=example((5,3));marker=marks[1]
        group[0]['rhythm_evidence']['tuplet']={'actual':3,'marker_bbox':marker['bbox']}
        result=run(group,left,marks,jobs)
        self.assertEqual([n['finger'] for n in group],[None,5]);self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_visible_unrecognized_tuplet_bracket_cannot_complete_finger_column(self):
        group,left,marks,jobs,gap=example((5,3));upper=jobs[0][0]
        neighboring_a=note('prior',x=84,y=100,gap=gap)
        neighboring_b=note('next',x=116,y=100,gap=gap)
        complete_groups=[[neighboring_a],group,[neighboring_b]]
        jobs=[(upper,g,complete_groups) for g in complete_groups]+[jobs[1]]
        marker=marks[1];y=marker['bbox'][1]+.5
        lines=[(90,y,marker['bbox'][0]-.4,y,.5),(marker['bbox'][2]+.4,y,122,y,.5),
               (90,y,90,y+3,.5),(122,y,122,y+3,.5)]
        result=candidate.refine_fingering_evidence(jobs,[j[0] for j in jobs],marks,{},[],lines)
        self.assertEqual([n['finger'] for n in group],[None,5])
        self.assertEqual(result.get('reconciled_chord_columns',0),0)

    def test_upward_stem_full_column_preserves_top_to_bottom_pitch_order(self):
        gap=5;stem=[106,80,105]
        a=note('top',100,100,gap,rhythm_evidence=dict(stem=stem,stem_direction='up',beams=1),
               source_fingering_state='unmarked',source_fingering_evidence={'candidate_bboxes':[]})
        b=note('bottom',100,105,gap,rhythm_evidence=dict(stem=stem,stem_direction='up',beams=1),
               source_fingering_state='printed',source_fingering_evidence={'candidate_bboxes':[]})
        five=digit(5,106,64.7,gap);two=digit(2,106,70.7,gap)
        b.update(finger=5,finger_source='printed',finger_bbox=five['bbox'])
        staff=dict(gap=gap,heads=[]);group=[a,b]
        result=candidate.refine_fingering_evidence([(staff,group,[group])],[staff],[five,two],{},[],[])
        self.assertEqual([a['finger'],b['finger']],[5,2]);self.assertEqual(result['reconciled_chord_columns'],1)

if __name__=='__main__':unittest.main()
