"""Local genuine PDF preview associations, keyed by complete PGL checksum.

No preview bytes are added to the device's compact song format. A different
file in the same slot can never inherit a previous song's source image.
"""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import zipfile
from PIL import Image
from performance_schema import clean_performance
from score_codec import decode as decode_motion


class ScoreSources:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'PianoGloveSoftware' / 'score-sources'
        self.lock = threading.RLock()

    @staticmethod
    def key(value):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
            raise ValueError('原谱标识不正确')
        return value

    def _write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.pending')
        temporary.write_bytes(data)
        temporary.replace(path)

    def record_document(self, checksum, pages, geometry_pages=None):
        checksum = self.key(checksum)
        if not isinstance(pages, list) or not 1 <= len(pages) <= 256:
            raise ValueError('原谱页数不正确')
        validated = []
        total = 0
        seen = set()
        for entry in pages:
            number = entry.get('page')
            if type(number) is not int or not 1 <= number <= 256 or number in seen:
                raise ValueError('原谱页编号不正确')
            seen.add(number)
            data = entry.get('data', '')
            prefix = 'data:image/png;base64,'
            if not isinstance(data, str) or not data.startswith(prefix):
                raise ValueError('原谱预览须为PNG')
            blob = base64.b64decode(data[len(prefix):], validate=True)
            total += len(blob)
            if len(blob) > 8 * 1024 * 1024 or total > 128 * 1024 * 1024:
                raise ValueError('原谱预览过大')
            try:
                with Image.open(io.BytesIO(blob)) as image:
                    if image.format != 'PNG' or not 1 <= image.width <= 4000 or not 1 <= image.height <= 4000:
                        raise ValueError('原谱预览尺寸不正确')
                    width, height = image.size
                    image.verify()
            except OSError as error:
                raise ValueError('原谱预览图片损坏') from error
            metadata = dict(page=number, width=width, height=height)
            geometry = next((p for p in geometry_pages or [] if p.get('page') == number), {})
            for key in ('width','height'):
                value=geometry.get(key)
                if type(value) in (int,float) and math.isfinite(value) and value > 0:
                    metadata['pdf_'+key]=value
            validated.append((metadata, blob))
        with self.lock:
            folder = self.root / 'documents' / checksum
            for entry, blob in validated:
                self._write(folder / ('%d.png' % entry['page']), blob)
            self._write(folder / 'manifest.json', json.dumps([entry for entry, _ in validated], ensure_ascii=False).encode('utf-8'))

    def associate(self, blob, project, score):
        performance = clean_performance(score.get('performance'), score.get('duration_ms'))
        source = project.get('source_sha256')
        if performance is not None:
            wire = decode_motion(blob)
            suffix = '（练习·'+performance['arrangement_id'][:16]+'）'
            if wire['duration_ms'] != performance['duration_ms'] or (performance['mode'] == 'practice' and not wire['title'].endswith(suffix)):
                raise ValueError('手套动作文件与练习琴声的编排标识不一致')
            if isinstance(source, str) and re.fullmatch(r'[0-9a-f]{64}', source) and performance['source_identity'] != source:
                raise ValueError('练习编排与原谱标识不一致')
        if not isinstance(source, str) or not re.fullmatch(r'[0-9a-f]{64}', source):
            if performance is None:
                return False
            # A manual score can carry a full sounding timeline without
            # claiming that a PDF or an original image exists.
            source = performance['source_identity']
        with self.lock:
            document = self.root / 'documents' / source / 'manifest.json'
            if not document.is_file():
                if performance is None:
                    return False
                pages = []
            else:
                pages = json.loads(document.read_text('utf-8'))
            page_set = {entry['page'] for entry in pages}
            note_pages = []
            origins = score.get('source_notes', [])
            if len(origins) == len(score['notes']):
                for index, origin in enumerate(origins):
                    if not isinstance(origin, dict) or origin.get('page') not in page_set:
                        continue
                    entry = dict(index=index, page=origin['page'])
                    for key in ('id', 'system', 'measure', 'origin', 'bbox', 'source_note_ids'):
                        if key in origin:
                            entry[key] = origin[key]
                    page = next(p for p in pages if p['page'] == origin['page'])
                    box = origin.get('bbox')
                    if (isinstance(box, list) and len(box) == 4 and
                        all(type(v) in (int,float) and math.isfinite(v) for v in box) and
                        page.get('pdf_width') and page.get('pdf_height') and box[2] > box[0] and box[3] > box[1]):
                        x0=max(0,box[0]-6);y0=max(0,box[1]-30)
                        x1=min(page['pdf_width'],box[2]+6);y1=min(page['pdf_height'],box[3]+16)
                        if x1>x0 and y1>y0:
                            entry.update(x=x0/page['pdf_width']*page['width'],y=y0/page['pdf_height']*page['height'],
                                         width=(x1-x0)/page['pdf_width']*page['width'],height=(y1-y0)/page['pdf_height']*page['height'])
                    note_pages.append(entry)
            selected = {entry['page'] for entry in note_pages}
            if score.get('partial_export'):
                selected.update(entry['page'] for entry in score['partial_export'].get('skipped_pending',[])
                                if entry.get('page') in page_set)
            if not selected:
                selected = page_set
            digest = hashlib.sha256(blob).hexdigest()
            value = dict(source_sha256=source, score_sha256=digest, pages=[p for p in pages if p['page'] in selected], note_pages=note_pages)
            if score.get('partial_export'):
                value['partial_export']=score['partial_export']
            if score.get('performance_notice'):
                value['performance_notice']=score['performance_notice']
            if performance is not None:
                # Audio and motion no longer have a one-to-one index. Locate
                # every original head, including gray audio-only heads.
                by_id = {str(n.get('id')):n for n in project.get('notes', [])}
                for ident, origin in performance.get('source_map', {}).items():
                    note = by_id.get(str(ident), {})
                    page = next((p for p in pages if p['page'] == note.get('page')), None)
                    box = note.get('bbox')
                    if (page is None or not isinstance(origin, dict) or not isinstance(box, list)
                            or len(box) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in box)
                            or not page.get('pdf_width') or not page.get('pdf_height')):
                        continue
                    x0, y0 = max(0, box[0]-6), max(0, box[1]-30)
                    x1, y1 = min(page['pdf_width'], box[2]+6), min(page['pdf_height'], box[3]+16)
                    if x1 > x0 and y1 > y0:
                        origin['location'] = dict(page=page['page'], system=note.get('system'),
                            measure=note.get('measure'), x=x0/page['pdf_width']*page['width'],
                            y=y0/page['pdf_height']*page['height'],
                            width=(x1-x0)/page['pdf_width']*page['width'],
                            height=(y1-y0)/page['pdf_height']*page['height'])
                audio_pages = {origin.get('location', {}).get('page', origin.get('page'))
                               for origin in performance.get('source_map', {}).values() if isinstance(origin, dict)}
                if audio_pages:
                    selected.update(audio_pages.intersection(page_set))
                    value['pages'] = [p for p in pages if p['page'] in selected]
                value['performance'] = performance
                value['source_kind'] = 'pdf' if pages else 'score-model'
                value['display_title'] = performance.get('display_title', score.get('title'))
                value['motion_title'] = wire['title']
                value['motion_duration_ms'] = wire['duration_ms']
                existing = self.root / 'scores' / (digest + '.json')
                if existing.is_file():
                    old = json.loads(existing.read_text('utf8')).get('performance')
                    if old is None or old.get('arrangement_id') != performance.get('arrangement_id'):
                        raise ValueError('练习编排标识与已有琴声不一致，不能覆盖原谱关联')
            self._write(self.root / 'scores' / (digest + '.json'), json.dumps(value, ensure_ascii=False).encode('utf-8'))
            return True

    def lookup(self, blob):
        digest = hashlib.sha256(blob).hexdigest()
        return self.lookup_key(digest)

    def lookup_key(self, digest):
        digest = self.key(digest)
        with self.lock:
            path = self.root / 'scores' / (digest + '.json')
            if not path.is_file():
                return dict(available=False)
            value = json.loads(path.read_text('utf-8'))
            if value.get('performance') is not None:
                p = clean_performance(value['performance'], value.get('motion_duration_ms'), clone=False)
                if p['source_identity'] != value.get('source_sha256') or not str(value.get('motion_title', '')).endswith('（练习·'+p['arrangement_id'][:16]+'）'):
                    raise ValueError('保存的练习琴声与动作谱标识不一致')
            value['available'] = True
            for entry in value['pages']:
                entry['image_url'] = '/api/software/source/%s/%d' % (digest, entry['page'])
            return value

    def image(self, digest, page):
        value = self.lookup_key(digest)
        if not value['available'] or type(page) is not int or page not in {p['page'] for p in value['pages']}:
            raise FileNotFoundError('原谱预览不存在')
        source = self.key(value['source_sha256'])
        return (self.root / 'documents' / source / ('%d.png' % page)).read_bytes()

    def package(self, blob):
        """Carry genuine preview pages between browsers; device bytes stay PGL.

        ZIP_STORED permits the offline phone to validate and read the package
        without a network dependency or a decompression library.
        """
        with self.lock:
            value = self.lookup(blob)
            if not value['available']:
                return None
            if value.get('performance') is not None:
                wire = decode_motion(blob)
                if wire['title'] != value.get('motion_title') or wire['duration_ms'] != value.get('motion_duration_ms'):
                    raise ValueError('随谱包的动作文件与琴声不一致')
            manifest = dict(version=2 if value.get('performance') is not None else 1, source_sha256=self.key(value['source_sha256']),
                            score_sha256=self.key(value['score_sha256']),
                            pages=[], note_pages=value['note_pages'])
            if value.get('partial_export'):
                manifest['partial_export']=value['partial_export']
            if value.get('performance_notice'):
                manifest['performance_notice']=value['performance_notice']
            if value.get('performance') is not None:
                manifest['performance'] = value['performance']
                manifest['source_kind'] = value.get('source_kind', 'pdf')
                manifest['display_title'] = value.get('display_title')
            pictures = []
            for page in sorted(value['pages'], key=lambda entry: entry['page']):
                name = 'pages/%d.png' % page['page']
                picture = self.image(value['score_sha256'], page['page'])
                if len(picture) > 8 * 1024 * 1024:
                    raise ValueError('原谱单页超过8MB，无法生成随谱包')
                manifest['pages'].append(dict(page=page['page'], width=page['width'],
                                              height=page['height'], image_file=name))
                pictures.append((name, picture))
            encoded_manifest = json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            metadata_limit = (8 if manifest.get('performance') is not None else 2) * 1024 * 1024
            if len(encoded_manifest) > metadata_limit:
                raise ValueError('原谱与练习编排索引过大，请分段导出')
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                for name, data in [('score.pgl', blob), ('source.json', encoded_manifest)] + pictures:
                    # Stable metadata makes repeated exports byte-identical.
                    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_STORED
                    info.external_attr = 0o600 << 16
                    archive.writestr(info, data)
            result = output.getvalue()
            if len(result) > 32 * 1024 * 1024:
                raise ValueError('随谱包超过32MB，请分段导出')
            return result
