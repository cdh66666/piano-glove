"""Independent synthetic source-label evidence; user test PDFs are not fixtures."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _assign_page_fingerings,_source_fingering_states

def note(identity,x=100,y=30):
    return dict(id=identity,origin=[x,y],hand='right',finger=None,finger_source=None,
                finger_candidates=[],issues=[],confidence=.85,rhythm_evidence={})

def digit(value,x=100,y=20,font='Aloisen'):
    return dict(char=chr(0x130+value) if font=='Aloisen' else str(value),x=x,y=y,
                size=6,font=font,bbox=[x,y-3,x+4,y+2])

class SourceLabelStateTests(unittest.TestCase):
    def test_unmarked_source_preserves_note_without_inventing_a_finger(self):
        event=note('blank');staff=dict(gap=5,heads=[]);before=copy.deepcopy(event)
        _assign_page_fingerings([(staff,[event],[[event]])],[staff],[],{})
        self.assertEqual(event['source_fingering_state'],'unmarked')
        self.assertIsNone(event['finger'])
        self.assertEqual(event['origin'],before['origin'])

    def test_printed_label_keeps_its_value_and_source_bbox(self):
        event=note('printed');staff=dict(gap=5,heads=[]);label=digit(3)
        _assign_page_fingerings([(staff,[event],[[event]])],[staff],[label],{})
        self.assertEqual((event['finger'],event['source_fingering_state']),(3,'printed'))

    def test_ambiguous_partial_chord_is_not_declared_unmarked(self):
        events=[note('upper',y=30),note('lower',y=40)];staff=dict(gap=5,heads=[])
        label=digit(2,y=35)
        _assign_page_fingerings([(staff,events,[events])],[staff],[label],{})
        self.assertEqual([e['source_fingering_state'] for e in events],['unresolved','unresolved'])
        self.assertTrue(all(e['finger'] is None for e in events))

    def test_owned_partial_chord_digit_does_not_turn_other_head_into_an_error(self):
        events=[note('upper',y=30),note('lower',y=42.5)];staff=dict(gap=5,heads=[])
        label=digit(5,y=22.5)
        _assign_page_fingerings([(staff,events,[events])],[staff],[label],{})
        self.assertEqual(events[0]['source_fingering_state'],'printed')
        self.assertEqual(events[1]['source_fingering_state'],'unmarked')

    def test_neighboring_note_owns_its_digit(self):
        events=[note('first',x=100),note('second',x=120)];groups=[[e] for e in events]
        staff=dict(gap=5,heads=[])
        _assign_page_fingerings([(staff,g,groups) for g in groups],[staff],[digit(4,x=120)],{})
        self.assertEqual([e['source_fingering_state'] for e in events],['unmarked','printed'])

    def test_plain_text_or_invalid_visible_digit_stays_for_review(self):
        for label,plain in [(digit(2,font='Text'),True),(digit(6),False)]:
            event=note('visible');staff=dict(gap=5,heads=[])
            _source_fingering_states([(staff,[event],[[event]])],[staff],[] if plain else [label],{},[label] if plain else [])
            self.assertEqual(event['source_fingering_state'],'unresolved')
            self.assertIsNone(event['finger'])

    def test_distant_text_digit_is_not_a_fingering_candidate(self):
        event=note('blank');staff=dict(gap=5,heads=[])
        _source_fingering_states([(staff,[event],[[event]])],[staff],[],{},[digit(2,x=220,font='Text')])
        self.assertEqual(event['source_fingering_state'],'unmarked')

    def test_recognized_tuplet_number_is_not_a_missing_fingering_label(self):
        event=note('triplet');staff=dict(gap=5,heads=[]);marker=digit(3,font='Text')
        event['rhythm_evidence']={'tuplet':{'actual':3,'normal':2,'marker_bbox':marker['bbox']}}
        _source_fingering_states([(staff,[event],[[event]])],[staff],[],{},[marker])
        self.assertEqual(event['source_fingering_state'],'unmarked')

    def test_label_states_are_scale_and_translation_invariant(self):
        for scale,dx,dy in [(.6,-30,40),(1,0,0),(2.3,120,-12)]:
            event=note('variant',100*scale+dx,30*scale+dy);staff=dict(gap=5*scale,heads=[])
            label=digit(1,x=100*scale+dx,y=20*scale+dy)
            label['size']*=scale;label['bbox']=[label['x'],label['y']-3*scale,label['x']+4*scale,label['y']+2*scale]
            _assign_page_fingerings([(staff,[event],[[event]])],[staff],[label],{})
            self.assertEqual((event['finger'],event['source_fingering_state']),(1,'printed'))

if __name__=='__main__':unittest.main()
