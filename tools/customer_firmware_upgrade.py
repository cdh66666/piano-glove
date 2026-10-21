"""Standalone compiled-image upgrader, distributed separately from the main app.

SPDX-License-Identifier: GPL-2.0-or-later
This wrapper links the unmodified official Espressif esptool. Its source and the
corresponding official tool source accompany the upgrade executable. It contains
no piano-glove firmware source or customer application's source.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def resource_root():
    return Path(sys._MEIPASS) / 'image' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent / 'image'


def load_image(root=None):
    root = Path(root) if root else resource_root()
    manifest = json.loads((root / 'firmware-manifest.json').read_text(encoding='utf-8'))
    image = root / 'firmware.bin'
    data = image.read_bytes()
    if manifest.get('chip') != 'esp32' or manifest.get('address') != 0x10000 or manifest.get('max_size') != 0x140000:
        raise ValueError('升级镜像配置不匹配ESP32应用分区。')
    if not data or data[0] != 0xE9 or len(data) != manifest.get('bytes') or len(data) > 0x140000:
        raise ValueError('升级镜像尺寸或格式错误。')
    if hashlib.sha256(data).hexdigest() != manifest.get('sha256'):
        raise ValueError('升级镜像SHA256不匹配，请重新取得升级包。')
    return image, manifest


def validate_partitions(blob):
    if len(blob) != 4096:
        raise ValueError('无法读取主板分区表。')
    actual = {}
    for offset in range(0, 4096, 32):
        magic = struct.unpack_from('<H', blob, offset)[0]
        if magic == 0xffff:
            break
        if magic == 0xebeb:  # ESP-IDF partition-table MD5 record.
            break
        if magic != 0x50aa:
            raise ValueError('主板分区表格式不匹配。')
        _, kind, subtype, address, size, label, flags = struct.unpack_from('<HBBII16sI', blob, offset)
        label = label.split(b'\0', 1)[0].decode('ascii')
        actual[label] = (kind, subtype, address, size)
    expected = {'nvs': (1, 2, 0x9000, 0x5000), 'app0': (0, 0, 0x10000, 0x140000),
                'spiffs': (1, 0x82, 0x290000, 0x160000)}
    if any(actual.get(label) != entry for label, entry in expected.items()):
        raise ValueError('该主板分区布局与本升级包不同，已停止；未写入固件。')
    return {label: list(value) for label, value in actual.items()}


def api_request(port, path, data=None):
    payload = None if data is None else json.dumps(data).encode('utf-8')
    request = Request('http://127.0.0.1:%d%s' % (port, path), data=payload,
                      headers={'Content-Type': 'application/json'} if data is not None else {})
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        if not response.headers.get('Server', '').startswith('piano-glove-bridge'):
            raise ValueError('该网页端口不属于钢琴手套调试台。')
        return json.load(response)


def release_local_console(serial_port):
    for http_port in (8123, 8124):
        try:
            status = api_request(http_port, '/api/status')
        except (URLError, OSError, ValueError):
            continue
        if status.get('connected') and status.get('port') == serial_port:
            reply = api_request(http_port, '/api/send', {'cmd': 'SAFE', 'timeoutMs': 1500, 'quietMs': 25})
            if not any(line.startswith('OK SAFE') and re.search(r'\barmed=0\b', line)
                       for line in reply.get('lines', [])):
                raise ValueError('现有调试台未确认停止，请先在调试台停止并关闭黑色窗口。')
            api_request(http_port, '/api/disconnect', {})
            if api_request(http_port, '/api/status').get('connected'):
                raise ValueError('串口尚未释放，请先关闭调试台。')


def select_port(explicit=None):
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if explicit:
        if not re.fullmatch(r'COM[1-9][0-9]*', explicit, flags=re.I):
            raise ValueError('串口格式错误，例如COM3。')
        target = explicit.upper()
        match = next((item for item in ports if item.device.upper() == target), None)
        if match is None or (match.vid, match.pid) != (0x10C4, 0xEA60):
            raise ValueError('指定串口不是已连接的CP210x钢琴手套主控。')
        return target
    candidates = [item for item in ports if (item.vid, item.pid) == (0x10C4, 0xEA60)]
    if not candidates:
        raise ValueError('未找到CP210x主控，请连接USB并检查串口驱动。')
    print('连接的主控：')
    for index, item in enumerate(candidates, 1):
        print('%d. %s  %s' % (index, item.device, item.description))
    answer = input('输入要升级的编号：').strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(candidates):
        raise ValueError('编号无效，已停止。')
    return candidates[int(answer) - 1].device


def tool_command(serial_port, command, after='no-reset'):
    import esptool
    return esptool.main(['--chip', 'esp32', '--port', serial_port, '--baud', '230400',
                         '--after', after] + command)


def upgrade(serial_port, image, manifest):
    release_local_console(serial_port)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'PianoGloveFirmwareUpgrade' / (stamp + '-' + serial_port)
    backup.mkdir(parents=True)
    partition_file = backup / 'partition-table.bin'
    tool_command(serial_port, ['read-flash', '0x8000', '0x1000', str(partition_file)])
    layout = validate_partitions(partition_file.read_bytes())
    nvs_before = backup / 'nvs-before.bin'
    nvs_after = backup / 'nvs-after.bin'
    tool_command(serial_port, ['read-flash', '0x9000', '0x5000', str(nvs_before)])
    # Only this write command can change flash. It never touches IDs, NVS,
    # SPIFFS, bootloader or the partition table; no whole-chip erase is issued.
    tool_command(serial_port, ['write-flash', '0x10000', str(image)])
    tool_command(serial_port, ['verify-flash', '0x10000', str(image)])
    tool_command(serial_port, ['read-flash', '0x9000', '0x5000', str(nvs_after)], after='hard-reset')
    preserved = nvs_before.read_bytes() == nvs_after.read_bytes()
    report = dict(ok=preserved, serial_port=serial_port, firmware_sha256=manifest['sha256'],
                  image_bytes=manifest['bytes'], address=0x10000, partition_layout=layout,
                  calibration_nvs_preserved=preserved, ids_written=False, filesystem_written=False)
    (backup / 'upgrade-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not preserved:
        raise ValueError('固件写入完成，但校准存储校验不同；备份在' + str(backup) + '，请联系供应方。')
    print('升级完成。校准存储逐字节核对一致，曲库分区未写入。')
    print('记录：' + str(backup))
    print('关闭此窗口，重新启动软件；网页选择对应COM口并核对舵机型号。')


def main(argv=None):
    parser = argparse.ArgumentParser(description='钢琴手套ESP32编译固件升级；不含固件源码')
    parser.add_argument('--port', help='指定COM口，省略则显示可选主控')
    parser.add_argument('--self-test', action='store_true', help='仅离线检查镜像和烧录工具，不打开COM')
    args = parser.parse_args(argv)
    image, manifest = load_image()
    if args.self_test:
        import esptool
        print(json.dumps(dict(ok=True, esptool_version=esptool.__version__,
                              firmware_sha256=manifest['sha256'], firmware_bytes=manifest['bytes'],
                              serial_opened=False, firmware_written=False), ensure_ascii=False))
        return
    print('本工具只升级主控应用固件；不设置舵机ID，保留校准和曲库。')
    print('请摘下手套、关闭训练，并暂时断开舵机电源；主控USB保持连接。')
    port = select_port(args.port)
    if input('确认升级 ' + port + '？输入 YES 开始：').strip() != 'YES':
        print('已取消，没有写入。')
        return
    upgrade(port, image, manifest)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('升级停止：' + str(error), file=sys.stderr)
        sys.exit(1)
