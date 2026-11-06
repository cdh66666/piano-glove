"""Original-PDF catalog, holdout separation and raw recognition cache checks."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HOST = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOST))
from score_catalog import HOLDOUT_IDS, ScoreCatalog, build_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='piano-catalog-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'cache'
        self.catalog = ScoreCatalog(cache_root=self.cache)

    def fixture(self, score_id='1002604', revision=None):
        folder = self.root / 'fixture'
        folder.mkdir(exist_ok=True)
        entry = self.catalog.get(score_id)
        (folder / entry['file']).write_bytes(self.catalog.read(score_id))
        manifest = dict(self.catalog.manifest, scores=[entry])
        if revision is not None:
            manifest['cache_revision'] = revision
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return ScoreCatalog(folder, self.cache)

    @staticmethod
    def raw(entry, pitch='C4'):
        return dict(source_sha256=entry['sha256'], name=entry['title'],
            selection={'bpm': 120, 'range_reviewed': True}, report={'ready': True},
            notes=[dict(id='n1', pitch=pitch, confirmed=True)])

    def test_all_originals_are_unique_and_exactly_three_are_not_bundled(self):
        # 11-04 内置扩到约 100 首：新加的 lib- 另外检查；原来那批原件数字不变
        library = [entry for entry in self.catalog.list(include_holdouts=True) if str(entry['id']).startswith('lib-')]
        self.assertTrue(70 <= len(library) <= 80)
        self.assertTrue(all(entry['bundled'] and entry.get('category') and entry.get('stats', {}).get('notes') for entry in library))
        self.assertEqual(len({entry['sha256'] for entry in self.catalog.list(include_holdouts=True)}), len(self.catalog.list(include_holdouts=True)))
        all_scores = [entry for entry in self.catalog.list(include_holdouts=True) if entry.get('source_kind') != 'manual' and not str(entry['id']).startswith('lib-')]
        bundled = [entry for entry in self.catalog.list() if entry.get('source_kind') != 'manual' and not str(entry['id']).startswith('lib-')]
        self.assertEqual((len(all_scores), len(bundled)), (29, 26))  # 11-05 用户：扫描版《这世界那么多人》认不出，从内置删掉
        self.assertEqual(sum(entry['pages'] for entry in all_scores), 110)  # 删掉 6 页的扫描版
        self.assertEqual(sum(entry['pages'] for entry in bundled), 104)  # 删掉 6 页的扫描版
        self.assertEqual(sum(entry['bytes'] for entry in all_scores), 5059174)  # 删掉 2457790 字节的扫描版
        self.assertEqual(sum(entry['bytes'] for entry in bundled), 4735453)
        self.assertEqual(len({entry['sha256'] for entry in all_scores}), 29)
        self.assertEqual({entry['id'] for entry in all_scores if not entry['bundled']}, HOLDOUT_IDS)
        self.assertEqual(len([p for p in self.catalog.root.glob('*.pdf') if not p.name.startswith('lib-')]), 27)
        for entry in bundled:
            data = self.catalog.read(entry['id'])
            self.assertTrue(data.startswith(b'%PDF-'))
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])

    def test_holdouts_cannot_be_read_from_bundle_and_reviews_are_only_excerpts(self):
        for score_id in HOLDOUT_IDS:
            entry = self.catalog.get(score_id)
            self.assertIsNone(entry['file'])
            self.assertFalse((self.catalog.root / (score_id + '.pdf')).exists())
            with self.assertRaisesRegex(FileNotFoundError, '手动导入'):
                self.catalog.read(score_id)
            review = entry['reviewed_conversion']
            self.assertEqual(review['status'], 'reviewed_excerpt')
            self.assertFalse(review['whole_score_reviewed'])
        self.assertTrue(all(entry['reviewed_conversion'] is None for entry in self.catalog.list() if entry.get('source_kind') != 'manual'))

    def test_metadata_returns_independent_values_and_unknown_id_is_explicit(self):
        entry = self.catalog.list()[0]
        identity = entry['id']
        entry['title'] = '临时改名'
        self.assertNotEqual(self.catalog.get(identity)['title'], '临时改名')
        with self.assertRaises(KeyError):
            self.catalog.get('../not-in-catalog')

    def test_only_full_curated_scores_supply_valid_playable_packages(self):
        from io import BytesIO
        import zipfile
        from score_codec import decode
        for row in self.catalog.list():
            if not row['playable']:
                with self.assertRaisesRegex(ValueError,'整首核对'):
                    self.catalog.package(row['id'])
                continue
            result=self.catalog.package(row['id'])
            with zipfile.ZipFile(BytesIO(base64.b64decode(result['base64']))) as archive:
                score=archive.read('score.pgl')
                self.assertEqual(hashlib.sha256(score).hexdigest(),result['score_sha256'])
                self.assertEqual(len(decode(score)['notes']),result['notes'])
                self.assertIn('source.json',archive.namelist())
        for score_id in HOLDOUT_IDS:
            with self.assertRaises(ValueError):self.catalog.package(score_id)

    def test_raw_candidate_cache_cannot_become_directly_playable(self):
        catalog=self.fixture()
        self.assertFalse(catalog.list()[0]['playable'])
        with self.assertRaisesRegex(ValueError,'整首核对'):catalog.package('1002604')

    def test_unresolved_curation_blocks_direct_playback(self):
        self.catalog._curated['1002604']['unresolved_items']=['unverified measure']
        self.assertFalse(next(row for row in self.catalog.list() if row['id']=='1002604')['playable'])
        with self.assertRaises(ValueError):self.catalog.package('1002604')

    def test_modified_bundled_bytes_are_rejected_even_with_valid_cached_project(self):
        catalog = self.fixture()
        entry = catalog.list()[0]
        convert = Mock(return_value=self.raw(entry))
        catalog.project(entry['id'], converter=convert)
        path = catalog.root / entry['file']
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            catalog.project(entry['id'], converter=convert)
        convert.assert_called_once()

    def test_lazy_cache_reuses_raw_result_without_approving_or_leaking_user_edits(self):
        catalog = self.fixture()
        entry = catalog.get('1002604')
        convert = Mock(return_value=self.raw(entry))
        first = catalog.project(entry['id'], converter=convert)
        payload = convert.call_args.args[0]
        self.assertEqual(hashlib.sha256(base64.b64decode(payload['base64'])).hexdigest(), entry['sha256'])
        self.assertEqual(payload['filename'], entry['filename'])
        self.assertFalse(first['notes'][0]['confirmed'])
        self.assertFalse(first['selection']['range_reviewed'])
        self.assertFalse(first['report']['ready'])
        first['notes'][0].update(pitch='D4', confirmed=True)
        first['selection']['range_reviewed'] = True
        second = catalog.project(entry['id'], converter=convert)
        self.assertEqual(second['notes'][0]['pitch'], 'C4')
        self.assertFalse(second['notes'][0]['confirmed'])
        self.assertFalse(second['selection']['range_reviewed'])
        convert.assert_called_once()

    def test_tempo_reuses_recognition_but_parser_revision_invalidates_it(self):
        catalog = self.fixture(revision='parser-one')
        entry = catalog.list()[0]
        convert = Mock(return_value=self.raw(entry))
        for bpm in (120, 120.0, 100):
            self.assertEqual(catalog.project(entry['id'], bpm, convert)['selection']['bpm'], bpm)
        self.assertEqual(convert.call_count, 1)
        manifest = catalog.manifest
        manifest['cache_revision'] = 'parser-two'
        (catalog.root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        ScoreCatalog(catalog.root, self.cache).project(entry['id'], 120, convert)
        self.assertEqual(convert.call_count, 2)

    def test_broken_cache_is_rebuilt_and_wrong_source_result_is_not_cached(self):
        catalog = self.fixture()
        entry = catalog.get('1002604')
        convert = Mock(return_value=self.raw(entry))
        catalog.project(entry['id'], converter=convert)
        cached = next(self.cache.glob('*.json'))
        cached.write_text('not json', encoding='utf-8')
        catalog.project(entry['id'], converter=convert)
        self.assertEqual(convert.call_count, 2)
        with self.assertRaisesRegex(ValueError, '不一致'):
            catalog.project(entry['id'], 121, lambda _: {'source_sha256': 'wrong-source'}, force=True)
        self.assertEqual(len(list(self.cache.glob('*.json'))), 1)
        for invalid in (True, 0, 241, '120', 120.5):
            with self.assertRaises(ValueError):
                catalog.project(entry['id'], invalid, convert)

    def test_precomputed_projects_open_without_conversion_and_keep_unconfirmed_state(self):
        converter = Mock(side_effect=AssertionError('bundled project should avoid reconversion'))
        project = self.catalog.project('1002604', converter=converter)
        self.assertEqual(project['source_sha256'], self.catalog.get('1002604')['sha256'])
        self.assertTrue(project['page_previews'])
        self.assertTrue(all(not note['confirmed'] for note in project['notes']))
        self.assertFalse(project['selection']['range_reviewed'])
        converter.assert_not_called()

    def test_imported_original_reopens_without_recognition_and_force_rebuilds_it(self):
        data=b'%PDF-1.7 development cache fixture'
        digest=hashlib.sha256(data).hexdigest()
        entry=dict(sha256=digest,title='开发原谱')
        converter=Mock(return_value=self.raw(entry))
        first=self.catalog.imported_project('开发原谱.pdf',data,120,converter)
        cached=next(self.cache.glob('*.json'));original_bytes=cached.read_bytes()
        first['notes'][0].update(finger=5,manual_fields=['finger'])
        again=self.catalog.imported_project('原谱另存.pdf',data,96,converter)
        self.assertEqual(again['selection']['bpm'],96)
        self.assertEqual(again['source_name'],'原谱另存.pdf')
        self.assertNotIn('manual_fields',again['notes'][0])
        self.assertEqual(cached.read_bytes(),original_bytes)
        converter.assert_called_once()
        self.catalog.imported_project('开发原谱.pdf',data,96,converter,force=True)
        self.assertEqual(converter.call_count,2)

    def test_force_recognition_bypasses_bundled_precomputed_output(self):
        entry=self.catalog.get('1002604')
        converter=Mock(return_value=self.raw(entry,pitch='F4'))
        fresh=self.catalog.project('1002604',converter=converter,force=True)
        self.assertEqual(fresh['notes'][0]['pitch'],'F4')
        converter.assert_called_once()

    def test_real_bundled_pdf_is_recognized_locally_and_returns_actual_png(self):
        with patch.dict('os.environ', LOCALAPPDATA=str(self.root)), \
             patch('socket.socket', side_effect=AssertionError('socket created')), \
             patch('serial.Serial', side_effect=AssertionError('COM opened')), \
             patch('serial.serial_for_url', side_effect=AssertionError('COM opened')):
            project = self.catalog.project('1002604')
        entry = self.catalog.get('1002604')
        self.assertEqual(project['source_sha256'], entry['sha256'])
        self.assertEqual(len(project['page_previews']), 2)
        self.assertTrue(project['notes'])
        self.assertTrue(all(not note['confirmed'] for note in project['notes']))
        self.assertFalse(project['selection']['range_reviewed'])
        for page in project['page_previews']:
            self.assertTrue(base64.b64decode(page['data'].split(',', 1)[1]).startswith(b'\x89PNG\r\n\x1a\n'))
        reused = self.catalog.project('1002604', converter=Mock(side_effect=AssertionError('cache missed')))
        self.assertEqual(reused['source_sha256'], entry['sha256'])


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='piano-catalog-build-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        samples = self.source / 'samples'
        samples.mkdir(parents=True)
        from pypdf import PdfWriter
        entries = []
        for identity in sorted(HOLDOUT_IDS | {'1002604'}):
            path = samples / (identity + '_9_原始谱_五线谱.pdf')
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            writer.add_metadata({'/Title': identity})
            with path.open('wb') as handle:
                writer.write(handle)
            data = path.read_bytes()
            entries.append(dict(name=path.name, pages=1, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        # A true byte duplicate is counted once. Generated report PDFs outside
        # this original manifest are deliberately not included.
        duplicate = dict(next(entry for entry in entries if entry['name'].startswith('1002604_')))
        duplicate['name'] = 'alias.pdf'
        shutil.copyfile(samples / next(entry['name'] for entry in entries if entry['name'].startswith('1002604_')),
                        samples / duplicate['name'])
        entries.append(duplicate)
        (samples / 'agreement.pdf').write_bytes(b'%PDF-report-not-an-original')
        (self.source / 'downloads-manifest.json').write_text(json.dumps(entries), encoding='utf-8')

    def test_rebuild_is_reproducible_deduplicates_sha_and_keeps_exactly_three_external(self):
        first = build_catalog(self.source, self.root / 'bundle-a', self.root / 'manual-a', cache_revision='same-parser')
        second = build_catalog(self.source, self.root / 'bundle-b', self.root / 'manual-b', cache_revision='same-parser')
        self.assertEqual(first, second)
        self.assertEqual((first['total'], first['bundled_count']), (4, 1))
        self.assertEqual((self.root / 'bundle-a' / 'manifest.json').read_bytes(),
                         (self.root / 'bundle-b' / 'manifest.json').read_bytes())
        self.assertEqual(len(list((self.root / 'manual-a').glob('*.pdf'))), 3)
        self.assertEqual([path.name for path in (self.root / 'bundle-a').glob('*.pdf')], ['1002604.pdf'])
        self.assertNotIn('agreement.pdf', json.dumps(first))

    def test_source_or_existing_destination_mismatch_is_not_silently_overwritten(self):
        bundle = self.root / 'bundle'
        bundle.mkdir()
        destination = bundle / '1002604.pdf'
        destination.write_bytes(b'user-owned-existing-file')
        with self.assertRaisesRegex(ValueError, '未覆盖'):
            build_catalog(self.source, bundle, self.root / 'manual')
        self.assertEqual(destination.read_bytes(), b'user-owned-existing-file')
        original = next((self.source / 'samples').glob('1002604_*.pdf'))
        original.write_bytes(original.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, '不匹配'):
            build_catalog(self.source, self.root / 'other-bundle', self.root / 'other-manual')


if __name__ == '__main__':
    unittest.main()
