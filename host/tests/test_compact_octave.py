"""Independent engraving geometry, without customer score coordinates."""
import unittest

from score_converter_engine import _octave_regions, _octave_at


def example(reverse=False, lower=False, scale=1, dx=0, dy=0):
    x = lambda v: v*scale+dx
    y = lambda v: v*scale+dy
    staff = dict(left=x(10), right=x(210), top=y(100), bottom=y(128), gap=7*scale,
                 heads=[dict(x=x(60)), dict(x=x(105))])
    marker = dict(char='text:8vb' if lower else 'ƴ', x=x(60), y=y(140 if lower else 80),
                  bbox=[x(60),y(130 if lower else 60),x(78),y(150 if lower else 80)])
    if lower:
        marker['octave_semitones'] = -12
    endpoint = 70 if reverse else 80
    level = 136 if lower else 65
    lines = [(x(79),y(level),x(endpoint),y(level),.5*scale),
             (x(endpoint),y(level),x(endpoint),y(level+(-4 if lower else 4)),.5*scale)]
    return staff, marker, lines


class CompactOctaveTests(unittest.TestCase):
    def test_forward_tiny_and_reverse_brackets_are_bounded(self):
        for reverse in (False, True):
            for lower in (False, True):
                for scale, dx, dy in ((.7,0,0),(1,21,50),(2.5,100,25)):
                    with self.subTest(reverse=reverse,lower=lower,scale=scale):
                        s,m,lines = example(reverse,lower,scale,dx,dy)
                        regions = _octave_regions(s,[m],lines)
                        self.assertEqual(regions[0]['shift'],-12 if lower else 12)
                        self.assertEqual(regions[0]['endpoint'],'cap')
                        self.assertEqual(_octave_at(s['heads'][0]['x'],regions,s['gap'])[0],-12 if lower else 12)
                        self.assertEqual(_octave_at(s['heads'][1]['x'],regions,s['gap'])[0],0)

    def test_missing_hook_does_not_infer_an_isolated_octave(self):
        s,m,lines = example()
        self.assertIsNone(_octave_regions(s,[m],lines[:1])[0]['shift'])

    def test_wrong_way_hook_does_not_bound_a_region(self):
        s,m,lines = example()
        lines[1] = (80,65,80,61,.5)
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_detached_l_shape_is_not_an_octave_line(self):
        s,m,lines = example()
        lines[0] = (96,65,80,65,.5)
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_conflicting_compact_hooks_remain_unresolved(self):
        s,m,lines = example()
        lines += [(79,65,81,65,.5),(81,65,81,69,.5)]
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])

    def test_unknown_label_has_no_octave_semantics(self):
        s,m,lines = example()
        m['char'] = 'unknown'
        self.assertIsNone(_octave_regions(s,[m],lines)[0]['shift'])


if __name__ == '__main__':
    unittest.main()
