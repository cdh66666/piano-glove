import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_codec import encode, decode

class ScoreCodecTests(unittest.TestCase):
    def score(self):
        return dict(version=1,hand='right',title='右手和弦与长音',duration_ms=12000,
                    notes=[dict(t_ms=0,duration_ms=10000,pitch=60,finger=1,velocity=80,amplitude_pct=100),
                           dict(t_ms=0,duration_ms=500,pitch=64,finger=3,velocity=96,amplitude_pct=80),
                           dict(t_ms=10000,duration_ms=2000,pitch=62,finger=1,velocity=80,amplitude_pct=100)])
    def test_roundtrip_long_notes_chord_and_rest(self):
        score=self.score()
        self.assertEqual(decode(encode(score)),score)
        self.assertEqual(len(encode(score)),128+3*16)
    def test_integrity_includes_title_and_events(self):
        blob=encode(self.score())
        for offset in (24,128,140):
            bad=bytearray(blob);bad[offset]^=1
            with self.assertRaisesRegex(ValueError,'CRC'): decode(bad)
    def test_truncated_and_extra_data_rejected(self):
        blob=encode(self.score())
        for bad in (blob[:20],blob[:-1],blob+b'x'):
            with self.assertRaises(ValueError): decode(bad)
    def test_left_hand_and_unknown_finger_rejected(self):
        for field,value in [('hand','left'),('version',2)]:
            score=self.score();score[field]=value
            with self.assertRaises(ValueError): encode(score)
        for value in (0,6,True):
            score=self.score();score['notes'][0]['finger']=value
            with self.assertRaises(ValueError): encode(score)
    def test_overlapping_same_finger_rejected(self):
        score=self.score();score['notes'][1]['finger']=1
        with self.assertRaisesRegex(ValueError,'Overlapping'): encode(score)
    def test_invalid_timing_and_values(self):
        for field,value in [('t_ms',-1),('duration_ms',0),('pitch',128),('velocity',0),('amplitude_pct',101)]:
            score=self.score();score['notes'][0][field]=value
            with self.assertRaises(ValueError): encode(score)
    def test_capacity_calculation(self):
        score=self.score();score['duration_ms']=100000
        score['notes']=[dict(t_ms=i*100,duration_ms=90,pitch=60,finger=1) for i in range(1000)]
        self.assertEqual(len(encode(score)),16128)
        self.assertEqual(len(decode(encode(score))['notes']),1000)
