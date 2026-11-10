"""把编译好的固件冻结进程序资源（现场不再编译）。

用法（在本机做过一次固件构建后）：
    python tools/bundle_firmware.py

做的事：
  1. 从 firmware/.pio/build/esp32dev 取 bootloader / partitions / firmware
  2. 从 PlatformIO 的 Arduino 框架里取 boot_app0.bin（固定分区表要它）
  3. 校验分区表里 nvs=0x9000/0x5000、app0=0x10000/0x140000（绝不能碰校准数据）
  4. 写到 host/assets/firmware/，并生成带 SHA-256 的 manifest.json

manifest.json 是烧录器唯一信任的来源：偏移、大小、哈希全部在这里固定，
运行时不接受任何来自界面的镜像路径/偏移/波特率覆盖。
"""
import hashlib
import json
import re
import subprocess
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIRMWARE = REPO / 'firmware'
BUILD = FIRMWARE / '.pio' / 'build' / 'esp32dev'
TARGET = REPO / 'host' / 'assets' / 'firmware'
PIO_HOME = Path((__import__('os').environ.get('PLATFORMIO_CORE_DIR')
                 or Path.home() / '.platformio'))
BOOT_APP0 = PIO_HOME / 'packages' / 'framework-arduinoespressif32' / 'tools' / 'partitions' / 'boot_app0.bin'

OFFSETS = [('bootloader.bin', 0x1000), ('partitions.bin', 0x8000),
           ('boot_app0.bin', 0xe000), ('firmware.bin', 0x10000)]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def firmware_version():
    source = (FIRMWARE / 'src' / 'main.cpp').read_text(encoding='utf-8')
    match = re.search(r'#define\s+FW_VER\s+"([^"]+)"', source)
    if not match:
        raise SystemExit('firmware/src/main.cpp 里找不到 FW_VER')
    return match.group(1)


def check_partitions(blob):
    entries = {}
    for start in range(0, len(blob) - 31, 32):
        magic, kind, subtype, offset, size, name, flags = struct.unpack('<HBBII16sI', blob[start:start + 32])
        if magic == 0x50aa:
            entries[name.rstrip(b'\0').decode()] = (offset, size)
    if entries.get('nvs') != (0x9000, 0x5000):
        raise SystemExit('分区表 nvs 区不是 0x9000/0x5000，拒绝打包（会碰到校准数据）')
    if entries.get('app0') != (0x10000, 0x140000):
        raise SystemExit('分区表 app0 区不是 0x10000/0x140000，拒绝打包')
    return {'nvs': '0x9000/0x5000', 'app0': '0x10000/0x140000'}


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ''


def main():
    pieces = {'bootloader.bin': BUILD / 'bootloader.bin',
              'partitions.bin': BUILD / 'partitions.bin',
              'boot_app0.bin': BOOT_APP0,
              'firmware.bin': BUILD / 'firmware.bin'}
    missing = [name for name, path in pieces.items() if not path.is_file()]
    if missing:
        raise SystemExit('缺少构建产物：' + '、'.join(missing) +
                         '\n先在 firmware/ 里跑一次 pio run -e esp32dev')
    layouts = check_partitions(pieces['partitions.bin'].read_bytes())
    size = pieces['firmware.bin'].stat().st_size
    if size > 0x140000:
        raise SystemExit('固件超出 app0 分区：%d 字节' % size)

    TARGET.mkdir(parents=True, exist_ok=True)
    images = []
    for name, offset in OFFSETS:
        source = pieces[name]
        target = TARGET / name
        target.write_bytes(source.read_bytes())
        images.append(dict(name=name, offset=hex(offset), offset_int=offset,
                           bytes=target.stat().st_size, sha256=sha256(target)))
    version = firmware_version()
    manifest = dict(
        format=1,
        version=version,
        board='esp32dev',
        chip='esp32',
        baud=230400,
        flash_mode='keep',
        flash_freq='keep',
        flash_size='keep',
        partitions=layouts,
        images=images,
        built_at=datetime.fromtimestamp(
            pieces['firmware.bin'].stat().st_mtime, timezone.utc).astimezone().isoformat(timespec='seconds'),
        git_commit=git_commit(),
        note='现场只烧录这份冻结镜像；不在客户机上编译。',
    )
    (TARGET / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'images'},
                     ensure_ascii=False, indent=2))
    for item in images:
        print('  %-16s %s  %8d 字节  %s' % (item['name'], item['offset'], item['bytes'], item['sha256'][:16]))
    print('已写入', TARGET)


if __name__ == '__main__':
    sys.exit(main())
