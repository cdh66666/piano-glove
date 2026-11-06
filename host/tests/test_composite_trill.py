from pathlib import Path
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_marks import _glyph_symbols,_source
def trill(x=100):return dict(char='Ơ',font='Aloisen',x=x,y=80.,size=20.,bbox=[x,60.,x+20,80.])
def wave(x=98):return dict(char='ƣ',font='Aloisen',x=x,y=80.,size=20.,bbox=[x,66.,x+24,80.])
class CompositeTrillTests(unittest.TestCase):
    def test_one_overlapping_pair_has_one_trill_and_both_original_components(self):
        symbols=_glyph_symbols([trill(),wave()]);self.assertEqual(len(symbols),1);self.assertEqual(symbols[0]['kind'],'trill')
        source=_source(symbols[0]);self.assertEqual(source['component_count'],2);self.assertEqual([c['char'] for c in source['components']],['Ơ','ƣ']);self.assertEqual(source['bbox'],[98.,60.,122.,80.])
    def test_adjacent_wave_is_not_same_symbol(self):
        self.assertEqual(len(_glyph_symbols([trill(),wave(125)])),2)
    def test_small_ink_overlap_is_not_enough(self):
        self.assertEqual(len(_glyph_symbols([trill(),wave(118)])),2)
    def test_different_font_not_coalesced(self):
        w=wave();w.update(font='Bravura',char='\ue56c');self.assertEqual(len(_glyph_symbols([trill(),w])),2)
    def test_lower_mordent_is_not_a_trill_base(self):
        w=wave();w['char']='Ƥ';self.assertEqual(len(_glyph_symbols([trill(),w])),2)
    def test_two_competing_trills_stay_ambiguous(self):
        self.assertEqual(len(_glyph_symbols([trill(),trill(101),wave()])),3)
    def test_input_objects_not_modified(self):
        import copy
        objects=[trill(),wave()];before=copy.deepcopy(objects);_glyph_symbols(objects);self.assertEqual(objects,before)
if __name__=='__main__':unittest.main()
