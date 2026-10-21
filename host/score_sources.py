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
        source = project.get('source_sha256')
        if not isinstance(source, str) or not re.fullmatch(r'[0-9a-f]{64}', source):
            return False
        with self.lock:
            document = self.root / 'documents' / source / 'manifest.json'
            if not document.is_file():
                return False
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
            if not selected:
                selected = page_set
            digest = hashlib.sha256(blob).hexdigest()
            value = dict(source_sha256=source, score_sha256=digest, pages=[p for p in pages if p['page'] in selected], note_pages=note_pages)
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
            manifest = dict(version=1, source_sha256=self.key(value['source_sha256']),
                            score_sha256=self.key(value['score_sha256']),
                            pages=[], note_pages=value['note_pages'])
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
            if len(encoded_manifest) > 2 * 1024 * 1024:
                raise ValueError('原谱索引超过2MB，无法生成随谱包')
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
