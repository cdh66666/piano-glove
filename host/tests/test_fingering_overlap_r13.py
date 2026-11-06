"""Independent synthetic overlap controls; no user score geometry is used."""
from pathlib import Path
import sys,unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
sys.path.insert(0,str(HERE))
from test_fingering_evidence_r13 import note,digit
import fingering_evidence as candidate

class IndependentOverlappingGlyphTests(unittest.TestCase):
    def make(self,scale=1,dx=0,dy=0,marker_mode='separate'):
        gap=4*scale;x=80*scale+dx;y=90*scale+dy
        n=note('synthetic',x,y,gap)
        label=digit(4,x+gap,y-5*gap,gap)
        n.update(finger=4,finger_source='printed',finger_bbox=label['bbox'][:],source_fingering_state='printed')
        if marker_mode=='same':marker=label['bbox'][:]
        elif marker_mode=='near_duplicate':marker=[p+(.01*gap) for p in label['bbox']]
        else:
            b=label['bbox'];marker=[b[0]-.6*gap,b[1]-.6*gap,b[2]+.6*gap,b[3]+.6*gap]
        n['rhythm_evidence']['tuplet']={'marker_bbox':marker,'actual':4}
        staff={'gap':gap,'heads':[]};jobs=[(staff,[n],[[n]])]
        result=candidate.refine_fingering_evidence(jobs,[staff],[label],{},[],[])
        return n,result,label,marker

    def test_separate_overlaid_glyph_keeps_original_fingering(self):
        for scale,dx,dy in [(1,0,0),(.43,110,-22),(3.1,-56,620)]:
            with self.subTest(scale=scale):
                n,stats,label,marker=self.make(scale,dx,dy)
                self.assertTrue(candidate._same_ink(label['bbox'],marker))
                self.assertFalse(candidate._claimed_rhythmic(label['bbox'],4,[(marker,4)]))
                self.assertEqual((n['finger'],n['source_fingering_state']),(4,'printed'))

    def test_same_physical_marker_is_removed(self):
        for kind in ('same','near_duplicate'):
            with self.subTest(kind=kind):
                n,stats,_,_=self.make(marker_mode=kind)
                self.assertIsNone(n['finger'])
                self.assertEqual(stats['incorrect_tuplet_assignments_removed'],1)

    def test_distinct_value_is_never_claimed_as_marker(self):
        n,stats,label,marker=self.make()
        self.assertFalse(candidate._claimed_rhythmic(label['bbox'],5,[(marker,4)]))

    def test_same_sized_sources_with_different_fonts_stay_ambiguous(self):
        gap=4;n=note('synthetic',80,90,gap);label=digit(4,84,70,gap)
        n.update(finger=4,finger_source='printed',finger_bbox=label['bbox'][:],source_fingering_state='printed')
        n['rhythm_evidence']['tuplet']={'marker_bbox':label['bbox'][:],'actual':4}
        overlay=dict(label,char='4',font='Other')
        staff={'gap':gap,'heads':[]};jobs=[(staff,[n],[[n]])]
        result=candidate.refine_fingering_evidence(jobs,[staff],[label],{},[overlay],[])
        self.assertEqual((n['finger'],n['source_fingering_state']),(None,'unresolved'))
        self.assertEqual(result['overlapping_glyphs_unresolved'],1)

if __name__=='__main__':unittest.main()
