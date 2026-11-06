"""Source-independent chord, cross-voice and ambiguous-label examples."""
from pathlib import Path
from copy import deepcopy
import sys,unittest

HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
from test_fingering_evidence_r13 import note,digit
import fingering_evidence as c

def example(direction='up',count=2,scale=1,dx=0,dy=0):
    gap=5*scale;x=100*scale+dx;y=100*scale+dy
    stem=[x+1.2*gap,y-4*gap,y+(count-1)*gap] if direction=='up' else [x+1.2*gap,y,y+(count+3)*gap]
    group=[note('n'+str(i),x+(1.2*gap if i==0 else 0),y+i*gap,gap,
        rhythm_evidence={'stem':stem,'stem_direction':direction,'beams':1},
        source_fingering_state='unmarked',source_fingering_evidence={'candidate_bboxes':[]}) for i in range(count)]
    values=[5,3,2,1][:count]
    if direction=='up':ys=[y+(count-1)*gap+(1.6+i*1.2)*gap for i in range(count)]
    else:ys=[y-(1.6+(count-1-i)*1.2)*gap for i in range(count)]
    labels=[digit(v,x,z,gap) for v,z in zip(values,ys)]
    group[-1].update(finger=values[0],finger_source='printed',finger_bbox=labels[0]['bbox'],source_fingering_state='printed')
    staff={'gap':gap,'heads':[]};jobs=[(staff,group,[group])]
    return group,labels,jobs,gap,values

def call(group,labels,jobs):
    return c.refine_fingering_evidence(jobs,[j[0] for j in jobs],labels,{},[],[])

class IndependentHeadSideTests(unittest.TestCase):
    def test_reconciles_complete_column_at_displaced_head_on_both_stem_sides(self):
        for direction in ('up','down'):
            for scale,dx,dy in [(1,0,0),(.6,47,-31),(2.3,-80,180)]:
                with self.subTest(direction=direction,scale=scale):
                    group,labels,jobs,gap,values=example(direction=direction,scale=scale,dx=dx,dy=dy)
                    result=call(group,labels,jobs)
                    self.assertEqual([e['finger'] for e in group],values)
                    self.assertEqual(result['head_side_chord_columns'],1)
                    before=deepcopy(group);call(group,labels,jobs);self.assertEqual(group,before)

    def test_three_note_column(self):
        group,labels,jobs,gap,values=example(count=3)
        result=call(group,labels,jobs)
        self.assertEqual([e['finger'] for e in group],values)
        self.assertEqual(result['head_side_chord_columns'],1)

    def test_incomplete_column_is_not_guessed(self):
        group,labels,jobs,gap,values=example(count=3);labels.pop(1)
        before=[e['finger'] for e in group];result=call(group,labels,jobs)
        self.assertEqual([e['finger'] for e in group],before)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_extra_digit_is_not_arbitrarily_dropped(self):
        group,labels,jobs,gap,values=example();labels.append(digit(4,100,125,gap))
        before=[e['finger'] for e in group];result=call(group,labels,jobs)
        self.assertEqual([e['finger'] for e in group],before)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_competing_unlabelled_other_staff_head_blocks_assignment(self):
        group,labels,jobs,gap,values=example();anchor=labels[0]
        other=note('other',anchor['x'],anchor['y']+gap,gap,hand='left',rhythm_evidence={})
        other.update(source_fingering_state='unmarked',source_fingering_evidence={'candidate_bboxes':[]})
        staff={'gap':gap,'heads':[]};jobs.append((staff,[other],[[other]]))
        before=[e['finger'] for e in group];result=call(group,labels,jobs)
        self.assertEqual([e['finger'] for e in group],before)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_manual_edits_are_untouched(self):
        group,labels,jobs,gap,values=example();group[-1]['manual_fields']=['finger']
        before=deepcopy(group);result=call(group,labels,jobs)
        self.assertEqual(group,before);self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_second_digit_close_to_other_hand_is_not_stolen(self):
        group,labels,jobs,gap,values=example();far=labels[-1]
        other=note('other',far['x'],far['y'],gap,hand='left',rhythm_evidence={})
        other.update(source_fingering_state='unmarked',source_fingering_evidence={'candidate_bboxes':[]})
        staff={'gap':gap,'heads':[]};jobs.append((staff,[other],[[other]]))
        result=call(group,labels,jobs)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_left_hand_is_outside_right_hand_scope(self):
        group,labels,jobs,gap,values=example()
        for e in group:e['hand']='left'
        before=[e['finger'] for e in group];result=call(group,labels,jobs)
        self.assertEqual([e['finger'] for e in group],before)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_rhythm_label_cannot_complete_a_column(self):
        group,labels,jobs,gap,values=example();group[0]['rhythm_evidence']['tuplet']={'actual':3,'marker_bbox':labels[-1]['bbox']}
        result=call(group,labels,jobs)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

    def test_existing_foreign_label_cannot_be_reused(self):
        group,labels,jobs,gap,values=example();other=note('other',120,125,gap,hand='left')
        other.update(finger=values[-1],finger_source='printed',finger_bbox=labels[-1]['bbox'],source_fingering_state='printed')
        staff={'gap':gap,'heads':[]};jobs.append((staff,[other],[[other]]))
        result=call(group,labels,jobs)
        self.assertEqual(result.get('head_side_chord_columns',0),0)

if __name__=='__main__':unittest.main()
