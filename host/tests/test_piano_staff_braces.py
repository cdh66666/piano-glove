"""Printed grand-staff braces disambiguate vocal-plus-piano scores."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _braced_piano_layout, recognize

class PianoBraceTests(unittest.TestCase):
    def test_three_staves_per_system_preserve_only_the_bracketed_piano_hands(self):
        staves=[dict(top=y,bottom=y+20,gap=5,left=50) for y in (20,80,130,220,280,330)]
        braces=[dict(char='ğ',bbox=[42,79,50,151]),dict(char='ğ',bbox=[42,279,50,351])]
        layout=_braced_piano_layout(staves,braces)
        self.assertEqual([s['hand'] for s in layout],[None,'right','left',None,'right','left'])
        self.assertEqual([s['system'] for s in layout],[1,1,1,2,2,2])
        self.assertEqual([s['upper_partner'] for s in layout],[None,None,1,None,None,4])
        self.assertTrue(layout[0]['outside_piano'])

    def test_plain_two_staff_system_keeps_right_left_pair(self):
        staves=[dict(top=y,bottom=y+20,gap=5,left=50) for y in (80,130)]
        layout=_braced_piano_layout(staves,[dict(char='ğ',bbox=[42,79,50,151])])
        self.assertEqual([s['hand'] for s in layout],['right','left'])
        self.assertIsNone(_braced_piano_layout(staves,[]))

    def test_complete_original_vocal_score_selects_all_586_piano_right_notes(self):
        source=Path(__file__).resolve().parents[1]/'assets/score-library/1137915.pdf'
        project=recognize(source)
        expected={f'p{page}-s{staff}' for page in range(1,8) for staff in ([2,5,8] if page<7 else [2,5])}
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual(len(right),586)
        self.assertEqual({n['staff'] for n in right},expected)
        outside=[n for n in project['notes'] if n.get('staff_role')=='outside_piano']
        self.assertTrue(outside)
        self.assertTrue(all(n['excluded'] and n['hand'] is None for n in outside))
        self.assertTrue(all(not n['confirmed'] for n in project['notes']))
        self.assertEqual(project['written_duration_beats'],244)

if __name__=='__main__':unittest.main()
