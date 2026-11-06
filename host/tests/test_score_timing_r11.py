"""Independent synthetic music cases for editable RH timing (no PDFs)."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_timing import reflow_right_hand_timing


def event(identity, x, local=None, duration=1, **extra):
    note = dict(id=identity, page=1, system=1, measure=1, staff='r', hand='right',
                pitch='C4', finger=1, origin=[x, 20], measure_beat=local,
                beat=None, duration=duration, duration_beats=duration)
    note.update(extra)
    return note


def score(notes, *, length=None, meter=4, rests=()):
    records = {}
    for n in list(notes)+list(rests):
        if n.get('hand') == 'right':
            records.setdefault(n['measure'], dict(measure=n['measure'], timing_resolved=length is not None,
                length_beats=length, meter_beats=meter))
    return dict(notes=notes, rests=list(rests), staves=[dict(id='r', hand='right', page=1, system=1,
        meter_beats=meter, lines=[0,10,20,30,40], measures=list(records.values()))])


class RightHandTimingTests(unittest.TestCase):
    def test_left_hand_never_supplies_meter_duration_or_positions(self):
        p = score([event('a', 20), event('b', 40)], meter=4)
        left = event('left', 20, 0, 19, hand='left', staff='l', beat=812)
        p['notes'].append(left)
        p['staves'].append(dict(id='l', hand='left', page=1, system=1, meter_beats=19,
            measures=[dict(measure=1, timing_resolved=True, length_beats=19, meter_beats=19)]))
        before = deepcopy(left)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes'][:2]], [0, 1])
        self.assertEqual(p['written_duration_beats'], 2)
        self.assertEqual(p['notes'][-1], before)

    def test_only_root_warns_and_manual_anchor_moves_later_measure(self):
        p = score([event('a', 20), event('b', 40),
                   event('c', 20, 0, 1, measure=2)], length=None,
                  rests=[event('tail',60,1,3,measure=2)])
        p['staves'][0]['measures'][1].update(timing_resolved=True, length_beats=4)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']], [0, 1, 2])
        self.assertEqual([bool(n['timing_warning']) for n in p['notes']], [True, False, False])
        p['notes'][0].update(beat=1.5, manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']], [1.5, 2.5, 3.5])
        self.assertTrue(all(n['timing_warning'] is None for n in p['notes']))
        self.assertTrue(all(not n['timing_estimated'] for n in p['notes']))
        before = deepcopy(p)
        reflow_right_hand_timing(p)
        self.assertEqual(p, before)

    def test_duration_edit_preserves_chord_and_rest_and_moves_next_measure(self):
        rest = event('rest', 60, 2, 1)
        p = score([event('a', 20, 0), event('b', 40, 1), event('chord', 40, 1),
                   event('c', 80, 3), event('d', 20, 0, measure=2)], length=4, rests=[rest])
        reflow_right_hand_timing(p)
        p['notes'][0].update(duration_beats=2, manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']], [0, 2, 2, 4, 5])
        self.assertEqual(p['rests'][0]['beat'], 3)
        self.assertEqual(p['written_duration_beats'], 9)

    def test_known_parallel_voices_keep_overlap(self):
        p = score([event('held', 20, 0, 4, voice='down'),
                   event('up0', 20, 0, 1, voice='up'),
                   event('up1', 40, 1, 1, voice='up'),
                   event('up2', 60, 2, 1, voice='up'),
                   event('up3', 80, 3, 1, voice='up')], length=4)
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']], [0, 0, 1, 2, 3])
        self.assertTrue(all(n['timing_warning'] is None for n in p['notes']))

    def test_voice_duration_edit_moves_its_lane_without_serializing_sustain(self):
        p = score([event('held', 20, 0, 4, voice='down'),
                   event('up0', 20, 0, 1, voice='up'),
                   event('up1', 40, 1, 1, voice='up'),
                   event('up2', 60, 2, 1, voice='up'),
                   event('up3', 80, 3, 1, voice='up'),
                   event('later',20,0,measure=2)], length=4)
        reflow_right_hand_timing(p)
        p['notes'][1].update(duration_beats=2,manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']], [0,0,2,3,4,5])
        before=deepcopy(p)
        reflow_right_hand_timing(p)
        self.assertEqual(p,before)

    def test_left_derived_onset_and_transitive_beam_anchor_are_not_trusted(self):
        p = score([event('a',20,3,onset_evidence=dict(method='aligned_to_paired_complete_voice',anchor_ids=['lh'])),
                   event('b',40,4,onset_evidence=dict(method='adjacent_attacks_on_same_printed_beam',anchor_ids=['a']))])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1])
        self.assertEqual([bool(n['timing_warning']) for n in p['notes']],[True,False])

    def test_unknown_rest_warns_visible_next_note_and_can_be_reanchored(self):
        p = score([event('a',20,0),event('b',60,None),event('c',80,None)],
                  rests=[event('rest',40,None,None)])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,2,3])
        self.assertEqual(p['right_hand_timing']['warning_note_ids'],['b'])
        self.assertIsNone(p['rests'][0]['duration_beats'])
        p['notes'][1].update(beat=1.5,manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1.5,2.5])
        self.assertEqual(p['right_hand_timing']['warning_notes'],0)

    def test_right_hand_cross_staff_note_uses_geometry_without_left_bar_length(self):
        p = score([event('a',20),event('b',40,staff='lower')])
        p['staves'].append(dict(id='lower',hand='left',page=1,system=1,
            lines=[60,70,80,90,100],meter_beats=16,
            measures=[dict(measure=1,timing_resolved=True,length_beats=16,meter_beats=16)]))
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,1])
        self.assertEqual(p['written_duration_beats'],2)

    def test_unknown_trailing_rest_has_visible_last_note_warning(self):
        p=score([event('a',20,0)],rests=[event('rest',40,None,None)])
        reflow_right_hand_timing(p)
        self.assertEqual(p['right_hand_timing']['warning_note_ids'],['a'])
        self.assertIn('休止',p['notes'][0]['timing_warning'])

    def test_middle_unknown_rest_does_not_mark_earlier_notes_as_dependent(self):
        p=score([event('a',20,0),event('b',60,None),event('c',80,None)],
                rests=[event('rest',40,None,None)])
        reflow_right_hand_timing(p)
        first,root,later=p['notes']
        self.assertFalse(first['timing_estimated'])
        self.assertIsNone(first['timing_source_id'])
        self.assertIsNone(first['timing_warning'])
        self.assertTrue(root['timing_estimated'])
        self.assertEqual(root['timing_source_id'],'b')
        self.assertTrue(root['timing_warning'])
        self.assertTrue(later['timing_estimated'])
        self.assertEqual(later['timing_source_id'],'b')
        self.assertIsNone(later['timing_warning'])

    def test_hand_change_adds_source_note_without_treating_generated_beats_as_original(self):
        p=score([event('a',20),event('b',60,hand='left')])
        reflow_right_hand_timing(p)
        p['notes'][0].update(beat=2,manual_fields=['beat'])
        p['notes'][1]['hand']='right'
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[2,3])

    def test_unknown_actual_duration_remains_unknown(self):
        p = score([event('a', 20, duration=None), event('b', 40), event('c', 60)])
        reflow_right_hand_timing(p)
        self.assertIsNone(p['notes'][0]['duration_beats'])
        self.assertEqual(p['notes'][1]['beat'], 1)
        self.assertTrue(p['notes'][0]['timing_warning'])
        self.assertIsNone(p['notes'][1]['timing_warning'])
        p['notes'][0].update(duration_beats=.5, manual_fields=['duration_beats'])
        reflow_right_hand_timing(p)
        self.assertEqual(p['notes'][1]['beat'], .5)

    def test_explicit_later_manual_anchor_is_retained(self):
        p = score([event('a', 20, 0), event('b', 40, 1), event('c', 60, 2)], length=4)
        reflow_right_hand_timing(p)
        p['notes'][0].update(beat=1, manual_fields=['beat'])
        p['notes'][2].update(beat=8, manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']], [1, 2, 8])

    def test_manual_unstructured_project_is_untouched(self):
        p = dict(notes=[dict(id='a', hand='right', beat=5, duration_beats=1)],
                 selection=dict(bpm=120), written_duration_beats=8)
        before = deepcopy(p)
        reflow_right_hand_timing(p)
        self.assertEqual(p, before)

    def test_repeat_sections_follow_source_marker_boundaries(self):
        p = score([event('a', 20, 0), event('b', 40, 1),
                   event('c', 20, 0, measure=2)], length=4)
        p['repeat_markers'] = [dict(page=1,system=1,boundary=0,kind='start',written_beat=0),
                               dict(page=1,system=1,boundary=2,kind='end',written_beat=8)]
        p['repeat_sections'] = [dict(start_beat=0,end_beat=8,count=2,marker_indices=[0,1])]
        reflow_right_hand_timing(p)
        p['notes'][0].update(beat=2, manual_fields=['beat'])
        reflow_right_hand_timing(p)
        self.assertEqual(p['repeat_sections'][0]['start_beat'], 2)
        self.assertEqual(p['repeat_sections'][0]['end_beat'], 10)


if __name__ == '__main__':
    unittest.main()
