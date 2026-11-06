"""Human-authored catalog resources, independent temporary source/project fixtures."""
import base64
from copy import deepcopy
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from PIL import Image

HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
from score_catalog import ScoreCatalog
from score_codec import encode,decode

spec=importlib.util.spec_from_file_location('manual_catalog_runtime',HOST/'customer_runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)

class ManualCatalogTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='manual-score-catalog-')
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.cache=self.root/'cache'
        stream=BytesIO();Image.new('RGB',(20,12),'white').save(stream,format='JPEG')
        self.source=stream.getvalue();self.source_sha=hashlib.sha256(self.source).hexdigest()
        self.project={'source_kind':'manual','recognizer':'manual-transcription-v1','source_sha256':self.source_sha,
                      'name':'人工测试曲谱','source_name':'authored-source.jpg','selection':{'bpm':80,'hand':'right','start_beat':0,'end_beat':4},
                      'source_tempo_bpm':80,'manual_review_import':True,'report':{'ready':True},
                      'notes':[{'id':'human-note','hand':'right','pitch':'C4','finger':2,'finger_source':'manual',
                                'beat':1,'duration_beats':1,'manual_fields':['pitch','finger','beat','duration_beats'],'confirmed':True}]}
        (self.root/'source.jpg').write_bytes(self.source)
        self.write_project(self.project)
        self.entry={'id':'authored-example','title':'独立人工测试（人工编配）','filename':'authored-source.jpg','file':'source.jpg',
                    'sha256':self.source_sha,'bytes':len(self.source),'pages':1,'bundled':True,'source_kind':'manual',
                    'manual_project':'manual-project.json','manual_project_sha256':hashlib.sha256(self.project_bytes).hexdigest(),
                    'reviewed_conversion':None}
        self.write_manifest()
        self.catalog=ScoreCatalog(self.root,self.cache)
        self.converter=Mock(side_effect=AssertionError('Manual source may never enter PDF conversion'))

    def write_project(self,project):
        self.project_bytes=json.dumps(project,ensure_ascii=False).encode('utf-8')
        (self.root/'manual-project.json').write_bytes(self.project_bytes)

    def write_manifest(self):
        (self.root/'manifest.json').write_text(json.dumps({'scores':[self.entry],'cache_revision':'independent-parser','holdout_ids':[]}),encoding='utf-8')

    def replace_project(self,project):
        self.write_project(project)
        self.entry['manual_project_sha256']=hashlib.sha256(self.project_bytes).hexdigest()
        self.write_manifest();self.catalog=ScoreCatalog(self.root,self.cache)

    def test_opens_jpeg_authored_project_without_pdf_converter_even_on_force(self):
        for force in (False,True):
            p=self.catalog.project(self.entry['id'],96,self.converter,force=force)
            self.assertEqual(p['source_kind'],'manual');self.assertFalse(p['recognition_performed'])
            self.assertEqual(p['selection']['bpm'],96);self.assertEqual(p['source_tempo_bpm'],80)
            self.assertEqual(p['notes'],self.project['notes']);self.assertTrue(p['manual_review_import'])
        self.converter.assert_not_called();self.assertFalse(self.cache.exists())

    def test_returned_manual_edits_do_not_modify_resource_or_future_open(self):
        before=(self.root/'manual-project.json').read_bytes()
        p=self.catalog.project(self.entry['id'],converter=self.converter)
        p['notes'][0]['finger']=5;p['selection']['end_beat']=99
        again=self.catalog.project(self.entry['id'],converter=self.converter)
        self.assertEqual(again['notes'][0]['finger'],2);self.assertEqual(again['selection']['end_beat'],4)
        self.assertEqual((self.root/'manual-project.json').read_bytes(),before)

    def test_verified_source_image_is_checked_before_manual_project_on_each_open(self):
        self.catalog.project(self.entry['id'],converter=self.converter)
        (self.root/'source.jpg').write_bytes(self.source+b'corrupt')
        for force in (False,True):
            with self.assertRaisesRegex(ValueError,'内置原谱校验失败'):
                self.catalog.project(self.entry['id'],converter=self.converter,force=force)
        self.converter.assert_not_called()

    def test_modified_manual_json_is_rejected_without_fallback(self):
        (self.root/'manual-project.json').write_bytes(self.project_bytes+b' ')
        for force in (False,True):
            with self.assertRaisesRegex(ValueError,'人工曲谱项目校验失败'):
                self.catalog.project(self.entry['id'],converter=self.converter,force=force)
        self.converter.assert_not_called()

    def test_manual_project_must_refer_to_the_verified_original(self):
        wrong=deepcopy(self.project);wrong['source_sha256']='0'*64;self.replace_project(wrong)
        with self.assertRaisesRegex(ValueError,'与原件不一致'):
            self.catalog.project(self.entry['id'],converter=self.converter)
        self.converter.assert_not_called()

    def test_invalid_manual_structure_or_false_provenance_is_not_relabelled_as_recognition(self):
        for wrong in [[],{'source_sha256':self.source_sha,'notes':{}},dict(self.project,source_kind='automatic')]:
            with self.subTest(project=wrong):
                self.replace_project(wrong)
                with self.assertRaisesRegex(ValueError,'格式不正确|来源类型不一致'):
                    self.catalog.project(self.entry['id'],converter=self.converter)
        self.converter.assert_not_called()

    def test_missing_manual_resource_configuration_does_not_attempt_pdf(self):
        del self.entry['manual_project'];self.write_manifest();self.catalog=ScoreCatalog(self.root,self.cache)
        with self.assertRaisesRegex(ValueError,'人工曲谱项目文件未配置'):
            self.catalog.project(self.entry['id'],converter=self.converter)
        self.converter.assert_not_called()

    def test_manual_tempo_uses_same_bounds_as_pdf_and_never_calls_converter(self):
        for invalid in (True,0,241,'120',120.5):
            with self.subTest(bpm=invalid),self.assertRaisesRegex(ValueError,'BPM须为'):
                self.catalog.project(self.entry['id'],invalid,self.converter)
        self.converter.assert_not_called()

    def test_manual_source_ignores_any_stale_raw_parser_cache(self):
        self.cache.mkdir()
        key=hashlib.sha256('|'.join((self.source_sha,'independent-parser','120.0')).encode('ascii')).hexdigest()
        (self.cache/(key+'.json')).write_text(json.dumps(dict(self.project,source_kind='automatic',recognizer='fake-parser')),encoding='utf-8')
        p=self.catalog.project(self.entry['id'],converter=self.converter)
        self.assertEqual(p['source_kind'],'manual');self.assertEqual(p['recognizer'],'manual-transcription-v1')
        self.converter.assert_not_called()

    def test_generic_manual_route_does_not_depend_on_score_id_or_file_name(self):
        self.entry['id']='unrelated-id-7921';self.entry['title']='另一人工项目';self.entry['filename']='different-photo.jpeg'
        self.write_manifest();catalog=ScoreCatalog(self.root,self.cache)
        self.assertEqual(catalog.project(self.entry['id'],converter=self.converter)['notes'][0]['finger'],2)
        self.converter.assert_not_called()

    def test_curated_manual_package_retains_existing_sha_and_source_checks(self):
        score={'version':1,'hand':'right','title':'独立人工测试','duration_ms':1000,
               'notes':[{'t_ms':0,'duration_ms':1000,'finger':2,'pitch':60,'velocity':96,'amplitude_pct':100}]}
        pgl=encode(score);buf=BytesIO()
        with zipfile.ZipFile(buf,'w') as bundle:
            bundle.writestr('score.pgl',pgl);bundle.writestr('source.json','{}')
        blob=buf.getvalue();(self.root/'authored.pglpack').write_bytes(blob)
        curated={'entries':[{'id':self.entry['id'],'status':'reviewed-complete','full_source_coverage':True,
                  'unresolved_items':[],'source_sha256':self.source_sha,'pglpack':'authored.pglpack',
                  'package_sha256':hashlib.sha256(blob).hexdigest(),'score_sha256':hashlib.sha256(pgl).hexdigest(),'played_right_events':1}]}
        (self.root/'curation-manifest.json').write_text(json.dumps(curated),encoding='utf-8')
        catalog=ScoreCatalog(self.root,self.cache);self.assertTrue(catalog.list()[0]['playable'])
        result=catalog.package(self.entry['id']);self.assertEqual(base64.b64decode(result['base64']),blob)
        self.assertEqual(decode(pgl)['notes'][0]['finger'],2)
        (self.root/'authored.pglpack').write_bytes(blob+b'bad')
        with self.assertRaisesRegex(ValueError,'曲谱包校验失败'):catalog.package(self.entry['id'])

    def test_runtime_counts_documents_and_file_formats_separately(self):
        entries=[{'file':'score-a.pdf'},{'file':'folder/score-b.PDF'},{'file':'source.jpg','source_kind':'manual'}]
        self.assertEqual(runtime.catalog_source_counts(entries),dict(bundled_original_documents=3,bundled_original_pdfs=2,bundled_manual_scores=1))
        self.assertEqual(runtime.catalog_source_counts([]),dict(bundled_original_documents=0,bundled_original_pdfs=0,bundled_manual_scores=0))


if __name__=='__main__':unittest.main()
