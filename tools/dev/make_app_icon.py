#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild host/assets/app-icon.ico from the mascot in host/comic-art.js (needs node and Edge)."""
import io
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
EDGE = next(p for p in (Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'),
                        Path(r'C:\Program Files\Microsoft\Edge\Application\msedge.exe')) if p.is_file())
NODE = "global.window=global;require(%s);process.stdout.write(ComicArt.mascot('idle','icon'))" % json.dumps(str(ROOT / 'host' / 'comic-art.js'))


def main():
    mascot = subprocess.run(['node', '-e', NODE], capture_output=True, text=True, encoding='utf-8', check=True).stdout
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        (work / 'icon.html').write_text('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:transparent}'
            '#b{width:512px;height:512px;display:grid;place-items:center}'
            'svg{width:512px;height:512px}</style><div id="b">' + mascot + '</div>', encoding='utf-8')
        subprocess.run([str(EDGE), '--headless=new', '--disable-gpu', '--hide-scrollbars', '--default-background-color=00000000',
                        '--force-device-scale-factor=1', '--window-size=512,512', '--user-data-dir=' + str(work / 'profile'),
                        '--screenshot=' + str(work / 'icon.png'), (work / 'icon.html').as_uri()],
                       check=True, capture_output=True, timeout=60)
        image = Image.open(work / 'icon.png').convert('RGBA')
        buffer = io.BytesIO()
        image.save(buffer, format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    (ROOT / 'host' / 'assets' / 'app-icon.ico').write_bytes(buffer.getvalue())
    print('icon bytes', len(buffer.getvalue()))


if __name__ == '__main__':
    main()
