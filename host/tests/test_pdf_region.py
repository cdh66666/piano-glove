"""The review lens renders a sharp crop at the requested PDF position."""
from pathlib import Path
import base64,io,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pypdfium2 as pdfium
from PIL import Image
from pdf_preview import render_pdf_region

class PDFRegionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'blank.pdf'
        document=pdfium.PdfDocument.new();document.new_page(200,300).close();document.save(str(self.path));document.close()
    def test_crop_uses_top_left_points_and_scale(self):
        crop=render_pdf_region(self.path,1,10,20,50,30,scale=8)
        self.assertEqual((crop['x'],crop['y'],crop['width'],crop['height']),(10,20,50,30))
        image=Image.open(io.BytesIO(base64.b64decode(crop['data'].split(',',1)[1])))
        self.assertEqual(image.size,(400,240))
    def test_crop_is_clamped_to_page(self):
        crop=render_pdf_region(self.path,1,180,290,50,30,scale=2)
        self.assertEqual((crop['width'],crop['height']),(20,10))
    def test_bad_page_or_outside_region_is_rejected(self):
        with self.assertRaises(ValueError):render_pdf_region(self.path,2,0,0,10,10)
        with self.assertRaises(ValueError):render_pdf_region(self.path,1,500,500,10,10)

if __name__=='__main__':unittest.main()
