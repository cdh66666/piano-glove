import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from calibration_recordings import validate_recording,save_recording,read_recording

class RecordingTests(unittest.TestCase):
    def recording(self):
        return {'version':1,'slot':2,'id':'3','profile':'SCS','range':1023,
                'complete':True,'standby':1,'frames':[
                    {'t_ms':0,'raw':1022,'unwrapped':1022},
                    {'t_ms':10,'raw':1023,'unwrapped':1023},
                    {'t_ms':20,'raw':0,'unwrapped':1024},
                    {'t_ms':30,'raw':1,'unwrapped':1025}]}
    def test_entire_crossing_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            data=self.recording()
            result=save_recording(data,root)
            saved=read_recording(result['id'],root)
            self.assertEqual(saved['frames'],data['frames'])
            self.assertEqual(saved['standby'],1)
            self.assertEqual(result['frames'],4)
    def test_partial_is_preserved_without_completed_claim(self):
        with tempfile.TemporaryDirectory() as root:
            data=self.recording();data['complete']=False
            self.assertFalse(save_recording(data,root)['complete'])
    def test_invalid_raw_or_wrap_or_time_is_rejected(self):
        for key,value in [('raw',1024),('unwrapped',0),('t_ms',-1)]:
            data=self.recording();data['frames'][2][key]=value
            with self.assertRaises(ValueError):validate_recording(data)
    def test_arbitrary_path_is_rejected(self):
        with self.assertRaises(ValueError):read_recording('../bridge.py')

if __name__=='__main__':unittest.main()
