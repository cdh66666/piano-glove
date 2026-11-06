"""Customer excerpt and tie semantics; synthetic scores, no PDF/device access."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_automatic import check_project, export_automatic
from score_converter import export_reviewed


def note(identity, **changes):
    result = dict(id=identity, page=1, system=1, measure=1, hand='right',
                  pitch='C4', finger=1, beat=0, duration_beats=1, confirmed=True)
    result.update(changes)
    return result


def project(notes, **selection):
    selected = dict(bpm=120, start_beat=0, end_beat=None, range_reviewed=True,
                    repeat_mode='written')
    selected.update(selection)
    return dict(name='节选', automatic_mode=True, notes=notes, selection=selected)


class ExportScopeTests(unittest.TestCase):
    def test_other_page_missing_fields_and_overlaps_do_not_block_excerpt(self):
        source = project([note('selected'), note('missing', page=2, beat=None, finger=None),
                          note('overlap-a', page=2, beat=4),
                          note('overlap-b', page=2, beat=4, pitch='E4')], start_page=1, end_page=1)
        before = deepcopy(source)
        checked = check_project(source)
        self.assertTrue(checked['automatic']['ready'])
        self.assertEqual(checked['automatic']['attention_note_ids'], [])
        self.assertEqual(checked['scope']['selected_note_ids'], ['selected'])
        self.assertEqual([n['in_export_scope'] for n in checked['notes']], [True, False, False, False])
        self.assertEqual(len(export_automatic(source)['notes']), 1)
        self.assertEqual(source, before)

    def test_other_beat_missing_fields_do_not_block_excerpt(self):
        source = project([note('selected'), note('later', beat=4, finger=None)], end_beat=1)
        self.assertTrue(check_project(source)['automatic']['ready'])
        self.assertEqual(len(export_automatic(source)['notes']), 1)

    def test_selected_unknown_note_remains_attention(self):
        source = project([note('good'), note('unknown', beat=None, finger=None)], end_beat=1)
        checked = check_project(source)
        self.assertEqual(checked['automatic']['attention_note_ids'], ['unknown'])
        self.assertTrue(checked['notes'][1]['in_export_scope'])
        with self.assertRaisesRegex(ValueError, '还有 1 处'):
            export_automatic(source)

    def test_source_position_missing_cannot_be_silently_dropped(self):
        source = project([note('unlocated', page=None)], start_page=1, end_page=1)
        checked = check_project(source)
        self.assertFalse(checked['automatic']['ready'])
        self.assertIn('核对原谱', checked['automatic']['messages'][0])

    def test_known_other_page_can_exclude_missing_later_coordinates(self):
        source = project([note('selected'), note('other', page=2, system=None, finger=None)],
                         start_page=1, end_page=1, start_system=1, end_system=1)
        self.assertEqual(len(export_automatic(source)['notes']), 1)

    def page_two(self):
        source = project([note('p1', beat=0),
                          note('p2', page=2, beat=65, measure_beat=1,
                               measure_start_beat=64, staff='p2-s1')], start_page=2, end_page=2)
        source['rests'] = [dict(page=2, system=1, measure=1, staff='p2-s1',
                                beat=64, measure_beat=0, measure_start_beat=64, duration_beats=1),
                           dict(page=2, system=1, measure=1, staff='p2-s1',
                                beat=66, measure_beat=2, measure_start_beat=64, duration_beats=2)]
        source['staves'] = [dict(id='p2-s1', page=2, system=1,
                                measures=[dict(measure=1, length_beats=4, timing_resolved=True)])]
        return source

    def test_page_excerpt_starts_at_measure_and_keeps_initial_and_final_rests(self):
        source = self.page_two()
        checked = check_project(source)
        self.assertEqual((checked['scope']['start_beat'], checked['scope']['end_beat']), (64, 68))
        for export in (export_reviewed, export_automatic):
            result = export(source)
            self.assertEqual(result['notes'][0]['t_ms'], 500)
            self.assertEqual(result['duration_ms'], 2000)

    def test_explicit_beat_crop_and_page_range_intersect(self):
        source = self.page_two()
        source['selection'].update(start_beat=65, end_beat=66)
        result = export_automatic(source)
        self.assertEqual(result['notes'][0]['t_ms'], 0)
        self.assertEqual(result['duration_ms'], 500)

    def test_source_range_can_use_measure_relative_position_without_boundary_field(self):
        source = self.page_two()
        for event in source['notes'] + source['rests']:
            event.pop('measure_start_beat', None)
        self.assertEqual(export_automatic(source)['notes'][0]['t_ms'], 500)

    def test_empty_intersection_has_actionable_message(self):
        source = self.page_two()
        source['selection']['end_beat'] = 4
        checked = check_project(source)
        self.assertFalse(checked['automatic']['ready'])
        self.assertIn('没有交集', checked['automatic']['messages'][0])

    def test_outside_incomplete_tremolo_and_repeat_are_irrelevant(self):
        source = project([note('selected'), note('other', page=2, beat=10,
                         tremolo_group='unresolved')], start_page=1, end_page=1, repeat_mode='unfold')
        source['repeat_sections'] = [dict(start_beat=10, end_beat=12, count=None,
                                          second_ending_end_beat=None)]
        self.assertEqual(len(export_automatic(source)['notes']), 1)

    def test_tremolo_excerpt_keeps_pulses_after_its_initial_source_onset(self):
        common = dict(tremolo_group='t', tremolo_step_beats=.25,
                      tremolo_span_beats=4, duration_beats=4)
        source = project([note('a', tremolo_side=0, **common),
                          note('b', pitch='G4', finger=5, tremolo_side=1, **common)],
                         start_beat=1, end_beat=2)
        result = export_automatic(source)
        self.assertEqual([n['t_ms'] for n in result['notes']], [0, 125, 250, 375])
        self.assertEqual(result['duration_ms'], 500)


class AutomaticTieTests(unittest.TestCase):
    def test_explicit_false_and_absent_candidate_option_preserve_two_attacks(self):
        source = project([note('a', tie_to_candidate='b'), note('b', beat=1)])
        for setting in ({}, {'apply_tie_candidates': False}):
            source['selection'].update(setting)
            result = export_automatic(source)
            self.assertEqual([n['t_ms'] for n in result['notes']], [0, 500])

    def test_explicit_tie_continuation_needs_no_invented_digit(self):
        source = project([note('a', tie_to='b', tie_reviewed=True),
                          note('b', beat=1, finger=None, tie_to='c', tie_reviewed=True),
                          note('c', beat=2, finger=None)], apply_tie_candidates=False)
        before = deepcopy(source)
        self.assertTrue(check_project(source)['automatic']['ready'])
        result = export_automatic(source)
        self.assertEqual(len(result['notes']), 1)
        self.assertEqual(result['notes'][0]['duration_ms'], 1500)
        self.assertEqual(result['source_notes'][0]['source_note_ids'], ['a', 'b', 'c'])
        self.assertEqual(source, before)

    def test_opted_in_candidate_tie_can_continue_without_a_new_digit(self):
        source = project([note('a', tie_to_candidate='b'), note('b', beat=1, finger=None)],
                         apply_tie_candidates=True)
        self.assertEqual(export_automatic(source)['notes'][0]['duration_ms'], 1000)

    def test_global_reviewed_explicit_tie_contract_is_preserved(self):
        source = project([note('a', tie_to='b'), note('b', beat=1, finger=None)], ties_reviewed=True)
        self.assertEqual(len(export_automatic(source)['notes']), 1)

    def test_tie_chain_root_still_requires_finger(self):
        source = project([note('a', finger=None, tie_to='b', tie_reviewed=True),
                          note('b', beat=1, finger=None), note('printed', beat=4, finger=2)])
        checked = check_project(source)
        self.assertIn('a', checked['automatic']['attention_note_ids'])
        with self.assertRaises(ValueError):export_automatic(source)

    def test_invalid_explicit_tie_is_not_made_playable(self):
        for changes in ({'pitch': 'D4'}, {'beat': 1.5}, {'finger': 2}):
            source = project([note('a', tie_to='b', tie_reviewed=True),
                              note('b', **dict({'beat': 1}, **changes))])
            with self.assertRaises(ValueError):export_automatic(source)

    def test_overlapping_attack_during_digitless_continuation_is_reported(self):
        source = project([note('a', tie_to='b', tie_reviewed=True),
                          note('b', beat=1, finger=None, duration_beats=2),
                          note('conflict', beat=2, pitch='E4')])
        checked = check_project(source)
        self.assertEqual(set(checked['automatic']['attention_note_ids']), {'a', 'b', 'conflict'})
        with self.assertRaisesRegex(ValueError, '重叠'):export_automatic(source)


if __name__ == '__main__':unittest.main()
