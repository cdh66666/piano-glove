"""The import route uses explicit score tempo and supports only printed fingers."""
import base64
from copy import deepcopy
from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge import SoftwareConsole

class PDFDirectFlowTests(unittest.TestCase):
    def convert(self,source_tempo,**payload):
        project=dict(name='测试',source_tempo_bpm=source_tempo,selection=dict(bpm=120,start_beat=0),
            notes=[dict(id='n',hand='right',pitch='C4',finger=1,finger_source='printed',beat=0,duration_beats=1)])
        data=dict(filename='新谱.pdf',base64=base64.b64encode(b'%PDF-1.4\n').decode(),bpm=120,**payload)
        with patch('score_sources.ScoreSources'),patch('score_converter.recognize_pdf',return_value=deepcopy(project)),patch('pdf_preview.render_pdf_pages',return_value=[]):
            return SoftwareConsole(None).convert(data)['project']

    def test_original_quarter_note_62_is_not_replaced_by_default_120(self):
        result=self.convert(62.0)
        self.assertEqual(result['selection']['bpm'],62.0)
        self.assertTrue(result['automatic']['ready'])
        self.assertNotEqual(result['notes'][0].get('confirmed'),True)

    def test_missing_original_tempo_preserves_requested_default(self):
        self.assertEqual(self.convert(None)['selection']['bpm'],120)

    def test_explicit_manual_tempo_mode_preserves_requested_value(self):
        self.assertEqual(self.convert(62,use_source_tempo=False)['selection']['bpm'],120)

if __name__=='__main__':unittest.main()
