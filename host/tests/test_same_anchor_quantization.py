"""Isolated synthetic checks; no user score, workbench, or device access."""
import unittest
from copy import deepcopy
from score_timing import reflow_right_hand_timing
from test_score_timing_r11 import event,score

def fixture(first_local=None):
    notes=[event('n'+str(i),20*i+20,(i+1)/3 if first_local else None,1/3) for i in range(6)]
    p=score(notes,length=4)
    p['repeat_markers']=[dict(page=1,system=1,boundary=0,kind='start',written_beat=0),
                         dict(page=1,system=1,boundary=1,kind='end',written_beat=4)]
    p['repeat_sections']=[dict(start_beat=0,end_beat=4,count=2,marker_indices=[0,1])]
    reflow_right_hand_timing(p)
    return p

def shape(p):
    return ([n['beat'] for n in p['notes']],p['written_duration_beats'],
            deepcopy(p['repeat_markers']),deepcopy(p['repeat_sections']))

class QuantizationTests(unittest.TestCase):
    def test_explicit_confirmation_of_published_middle_beat_has_no_drift(self):
        for index in (1,2,4,5):
            p=fixture();before=shape(p);anchor=p['notes'][index]
            anchor['manual_fields']=['beat']
            reflow_right_hand_timing(p)
            self.assertEqual(shape(p),before,index)
            first=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,first)

    def test_first_onset_at_fractional_local_keeps_bar_and_repeat_boundaries(self):
        p=fixture(True);before=shape(p);p['notes'][0]['manual_fields']=['beat']
        reflow_right_hand_timing(p);self.assertEqual(shape(p),before)
        first=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,first)

    def test_user_one_microbeat_edit_is_not_swallowed(self):
        p=fixture();before=shape(p);edited=round(p['notes'][1]['beat']+.000001,6)
        p['notes'][1].update(beat=edited,manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][1]['beat'],edited)
        self.assertNotEqual([n['beat'] for n in p['notes']],before[0])

    def test_chord_anchors_one_microbeat_apart_preserve_both_inputs(self):
        stem=[26,0,40]
        p=score([event('a',20,0,rhythm_evidence=dict(stem=stem)),
                 event('b',29,0,rhythm_evidence=dict(stem=stem)),event('c',50,1)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][0].update(beat=0,manual_fields=['beat'])
        p['notes'][1].update(beat=.000001,manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes'][:2]],[0,.000001])
        self.assertTrue(all('手动起拍不同' in n['timing_warning'] for n in p['notes'][:2]))
        saved=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,saved)

    def test_duration_one_microbeat_changes_both_successors(self):
        p=score([event('a',20,0,1),event('b',40,1,1),event('c',60,2,1)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][0].update(duration_beats=1.000001,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1.000001,2.000001])
        saved=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,saved)

    def test_non_manual_rounding_noise_does_not_move_successors(self):
        p=score([event('a',20,0,1),event('b',40,1,1),event('c',60,2,1)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][0]['duration_beats']=1.00000075
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1,2])

    def test_same_small_duration_change_propagates_only_when_manual(self):
        p=score([event('a',20,0,1),event('b',40,1,1),event('c',60,2,1)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][0].update(duration_beats=1.00000075,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1.000001,2.000001])

    def test_user_changed_first_anchor_moves_repeat_boundaries(self):
        p=fixture(True);before=shape(p);new=round(p['notes'][0]['beat']+.25,6)
        p['notes'][0].update(beat=new,manual_fields=['beat']);reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][0]['beat'],new)
        self.assertEqual(p['repeat_sections'][0]['start_beat'],.25)
        self.assertEqual(p['repeat_sections'][0]['end_beat'],4.25)
        self.assertNotEqual(shape(p),before)

    def test_later_manual_anchor_preserved(self):
        p=fixture();p['notes'][4].update(beat=3,manual_fields=['beat'])
        reflow_right_hand_timing(p);before=shape(p)
        p['notes'][1]['manual_fields']=['beat'];reflow_right_hand_timing(p)
        self.assertEqual(shape(p),before);self.assertEqual(p['notes'][4]['beat'],3)

    def test_unknown_duration_warning_does_not_disappear(self):
        p=score([event('unknown',20,None,None),event('after',40,None,1/3)])
        reflow_right_hand_timing(p);p['notes'][0]['manual_fields']=['beat']
        reflow_right_hand_timing(p)
        self.assertIsNone(p['notes'][0]['duration_beats'])
        self.assertTrue(p['notes'][0]['timing_warning'])

    def test_later_measure_stays_put_on_same_anchor(self):
        p=score([event('a',20,None,1/3),event('b',40,None,1/3),event('c',60,None,1/3),
                 event('next',20,0,1,measure=2)],length=4)
        reflow_right_hand_timing(p);before=[n['beat'] for n in p['notes']]
        p['notes'][1]['manual_fields']=['beat'];reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],before)

if __name__=='__main__':unittest.main()
