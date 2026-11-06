"""Conservative shared-column warnings from independent synthetic notation."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST));sys.path.insert(0,str(HOST/'tests'))
from test_fingering_head_side_r15 import example,note,digit
import fingering_evidence as c

def scene(scale=1,dx=0,dy=0):
    right,labels,jobs,gap,values=example(scale=scale,dx=dx,dy=dy)
    x=100*scale+dx;y=140*scale+dy
    left=note('left',x,y,gap,hand='left',rhythm_evidence={'stem':[x,y,y+20*scale],'stem_direction':'down','beams':1},
              source_fingering_state='printed',source_fingering_evidence={'candidate_bboxes':[]})
    left.update(finger=values[-1],finger_source='printed',finger_bbox=labels[-1]['bbox'])
    alt=digit(1,x,169*scale+dy,gap);labels.append(alt)
    staff={'gap':gap,'heads':[]};jobs.append((staff,[left],[[left]]))
    return right,left,labels,jobs,gap,values,alt

def run(labels,jobs):return c.refine_fingering_evidence(jobs,[j[0] for j in jobs],labels,{},[],[])

class CompetingColumnWarning(unittest.TestCase):
    def test_rejected_cross_hand_claim_is_pending_not_gray_or_wrong_number(self):
        for scale,dx,dy in [(1,0,0),(.7,20,-50),(2,-60,90)]:
            with self.subTest(scale=scale):
                right,left,labels,jobs,gap,values,alt=scene(scale,dx,dy);labels.remove(alt);old_left=deepcopy(left)
                result=run(labels,jobs)
                self.assertEqual(result['cross_staff_column_uncertain'],1)
                self.assertEqual([e['finger'] for e in right],[None,values[0]])
                self.assertEqual(right[0]['source_fingering_state'],'unresolved')
                self.assertIn('fingering_missing_or_ambiguous',right[0]['issues'])
                self.assertEqual(left,old_left)
                before=deepcopy([*right,left]);run(labels,jobs);self.assertEqual([*right,left],before)

    def test_possible_two_sided_repair_remains_pending_and_does_not_modify_left(self):
        right,left,labels,jobs,gap,values,alt=scene();old_left=deepcopy(left);result=run(labels,jobs)
        self.assertEqual(right[0]['finger'],None);self.assertEqual(right[0]['source_fingering_state'],'unresolved')
        self.assertEqual(left,old_left);self.assertEqual(result['cross_staff_column_uncertain'],1)

    def test_incomplete_column_must_not_raise_shared_column_warning(self):
        right,left,labels,jobs,gap,values,alt=scene();labels.remove(alt);labels.pop(0)
        result=run(labels,jobs);self.assertEqual(result['cross_staff_column_uncertain'],0)

    def test_no_other_hand_ownership_is_not_shared_ambiguity(self):
        right,left,labels,jobs,gap,values,alt=scene();labels.remove(alt);left['finger']=None;left.pop('finger_bbox')
        result=run(labels,jobs);self.assertEqual(result['cross_staff_column_uncertain'],0)

    def test_no_right_owned_label_does_not_borrow_another_hand_column(self):
        right,left,labels,jobs,gap,values,alt=scene();labels.remove(alt)
        right[-1]['finger']=None;right[-1]['finger_source']=None;right[-1].pop('finger_bbox')
        result=run(labels,jobs);self.assertEqual(result['cross_staff_column_uncertain'],0)

    def test_confirmed_or_manual_right_note_is_not_reset(self):
        for attr in ('confirmed','manual_fields'):
            right,left,labels,jobs,gap,values,alt=scene();labels.remove(alt)
            right[-1][attr]=True if attr=='confirmed' else ['finger'];before=deepcopy(right[-1])
            result=run(labels,jobs);self.assertEqual(right[-1],before);self.assertEqual(result['cross_staff_column_uncertain'],0)

    def test_source_tuplet_markers_do_not_create_chord_ambiguity(self):
        right,left,labels,jobs,gap,values,alt=scene();labels.remove(alt);right[0]['rhythm_evidence']['tuplet']={'marker_bbox':labels[-1]['bbox'],'actual':3}
        result=run(labels,jobs);self.assertEqual(result['cross_staff_column_uncertain'],0)

if __name__=='__main__':unittest.main()
