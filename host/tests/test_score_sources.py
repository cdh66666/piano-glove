"""Real image and checksum tests; no serial or hardware access."""
import base64
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_sources import ScoreSources
from score_codec import encode


def score(title='原曲'):
    return dict(version=1,hand='right',title=title,duration_ms=200,
                notes=[dict(t_ms=0,duration_ms=200,pitch=60,finger=1)],
                source_notes=[dict(id='n1',page=1,origin=[25.5,40])])


def preview(page=1):
    output = io.BytesIO()
    with Image.new('RGB',(12,16),'white') as image:
        image.save(output,format='PNG')
    return dict(page=page,data='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode())


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ScoreSources(self.temp.name)
        self.source = 'a'*64
        self.project = dict(source_sha256=self.source)
    def tearDown(self):
        self.temp.cleanup()
    def test_original_image_roundtrip_and_note_order(self):
        self.store.record_document(self.source,[preview()])
        blob=encode(score())
        self.assertTrue(self.store.associate(blob,self.project,score()))
        value=self.store.lookup(blob)
        self.assertTrue(value['available'])
        self.assertEqual(value['note_pages'],[dict(index=0,page=1,id='n1',origin=[25.5,40])])
        self.assertEqual(self.store.image(value['score_sha256'],1),base64.b64decode(preview()['data'].split(',')[1]))
    def test_different_file_does_not_inherit_slot_source(self):
        self.store.record_document(self.source,[preview()])
        self.store.associate(encode(score()),self.project,score())
        self.assertFalse(self.store.lookup(encode(score('另一首')))['available'])
    def test_restart_keeps_association(self):
        self.store.record_document(self.source,[preview()])
        blob=encode(score());self.store.associate(blob,self.project,score())
        self.assertTrue(ScoreSources(self.temp.name).lookup(blob)['available'])
    def test_missing_source_does_not_claim_real_original(self):
        self.assertFalse(self.store.associate(encode(score()),self.project,score()))
        self.assertFalse(self.store.lookup(encode(score()))['available'])
    def test_unknown_page_and_path_tokens_rejected(self):
        self.store.record_document(self.source,[preview()])
        blob=encode(score());self.store.associate(blob,self.project,score())
        with self.assertRaises(FileNotFoundError):self.store.image(self.store.lookup(blob)['score_sha256'],2)
        with self.assertRaises(ValueError):self.store.lookup_key('../manifest')
    def test_invalid_image_does_not_replace_verified_document(self):
        self.store.record_document(self.source,[preview()])
        with self.assertRaises(ValueError):self.store.record_document(self.source,[dict(page=1,data='data:image/png;base64,AAAA')])
        self.assertEqual(json.loads((Path(self.temp.name)/'documents'/self.source/'manifest.json').read_text())[0]['width'],12)
    def test_pdf_point_boxes_are_scaled_to_actual_preview_pixels(self):
        self.store.record_document(self.source,[preview()],[dict(page=1,width=120,height=160)])
        value=score();value['source_notes'][0]['bbox']=[20,50,30,60]
        blob=encode(value);self.store.associate(blob,self.project,value)
        box=self.store.lookup(blob)['note_pages'][0]
        self.assertAlmostEqual(box['x'],1.4);self.assertAlmostEqual(box['y'],2)
        self.assertAlmostEqual(box['width'],2.2);self.assertAlmostEqual(box['height'],5.6)
    def test_portable_package_keeps_exact_device_bytes_and_real_png(self):
        self.store.record_document(self.source,[preview(),preview(2)])
        blob=encode(score());self.store.associate(blob,self.project,score())
        package=self.store.package(blob)
        self.assertEqual(package,self.store.package(blob))
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertEqual(archive.namelist(),['score.pgl','source.json','pages/1.png'])
            self.assertIsNone(archive.testzip())
            self.assertTrue(all(entry.compress_type==zipfile.ZIP_STORED for entry in archive.infolist()))
            self.assertEqual(archive.read('score.pgl'),blob)
            manifest=json.loads(archive.read('source.json'))
            self.assertEqual(manifest['version'],1)
            self.assertEqual(manifest['score_sha256'],hashlib.sha256(blob).hexdigest())
            self.assertEqual(manifest['source_sha256'],self.source)
            self.assertEqual(manifest['pages'],[dict(page=1,width=12,height=16,image_file='pages/1.png')])
            self.assertEqual(archive.read('pages/1.png'),base64.b64decode(preview()['data'].split(',')[1]))
            self.assertNotIn('image_url',manifest['pages'][0])
    def test_no_source_has_no_portable_bundle(self):
        self.assertIsNone(self.store.package(encode(score())))
    def test_missing_registered_image_cannot_create_incomplete_bundle(self):
        self.store.record_document(self.source,[preview()])
        blob=encode(score());self.store.associate(blob,self.project,score())
        (Path(self.temp.name)/'documents'/self.source/'1.png').unlink()
        with self.assertRaises(FileNotFoundError):self.store.package(blob)


if __name__=='__main__':unittest.main()
