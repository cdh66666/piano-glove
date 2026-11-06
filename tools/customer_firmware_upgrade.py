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
import time
import os
from pathlib import Path
import re
import struct
import sys
import zlib
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
    # The shipped boards use the default Arduino OTA layout, where app0 is ota_0
    # (subtype 0x10) next to otadata; upgrade() then checks ota_0 is the boot slot.
    if actual.get('app0', (None, None))[1] == 0x10 and 'otadata' in actual:
        expected['app0'] = (0, 0x10, 0x10000, 0x140000)
    if any(actual.get(label) != entry for label, entry in expected.items()):
        raise ValueError('该主板分区布局与本升级包不同，已停止；未写入固件。')
    return {label: list(value) for label, value in actual.items()}


def ota_boot_slot(blob):
    """Slot otadata boots (0 = ota_0), or None when no entry is valid (boots ota_0)."""
    best = None
    for offset in (0, 0x1000):
        if offset + 32 > len(blob):
            continue
        seq, = struct.unpack_from('<I', blob, offset)
        crc, = struct.unpack_from('<I', blob, offset + 28)
        if seq in (0, 0xffffffff) or zlib.crc32(blob[offset:offset + 4], 0xffffffff) != crc:
            continue
        best = seq if best is None else max(best, seq)
    return None if best is None else (best - 1) % 2


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


def release_torque(serial_port):
    """11-05 用户：更新前把舵机失能就行。直接向主控发 SAFE（舵机松开力气）；主控没有手套程序时不回话也照样升级。"""
    try:
        import serial
        with serial.Serial(serial_port, 115200, timeout=0.2) as link:
            time.sleep(0.3)
            link.reset_input_buffer()
            link.write(b'SAFE\n')
            deadline = time.time() + 1.2
            reply = b''
            while time.time() < deadline and b'OK SAFE' not in reply:
                reply += link.read(256)
            return b'OK SAFE' in reply
    except Exception:
        return False


def upgrade(serial_port, image, manifest, stage=None):
    # stage(name, start, end): the GUI maps esptool's own percentages into this
    # share of the overall progress bar. The console path passes nothing.
    stage = stage or (lambda *_: None)
    release_local_console(serial_port)
    release_torque(serial_port)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'PianoGloveFirmwareUpgrade' / (stamp + '-' + serial_port)
    backup.mkdir(parents=True)
    partition_file = backup / 'partition-table.bin'
    stage('检查主板', 0, 4)
    tool_command(serial_port, ['read-flash', '0x8000', '0x1000', str(partition_file)])
    layout = validate_partitions(partition_file.read_bytes())
    if 'otadata' in layout:
        otadata = backup / 'otadata.bin'
        tool_command(serial_port, ['read-flash', hex(layout['otadata'][2]), hex(layout['otadata'][3]), str(otadata)])
        if ota_boot_slot(otadata.read_bytes()) not in (None, 0):
            raise ValueError('主板当前从第二个应用分区启动，与本升级包不同，已停止；未写入固件。')
    nvs_before = backup / 'nvs-before.bin'
    nvs_after = backup / 'nvs-after.bin'
    stage('备份校准数据', 4, 10)
    tool_command(serial_port, ['read-flash', '0x9000', '0x5000', str(nvs_before)])
    # Only this write command can change flash. It never touches IDs, NVS,
    # SPIFFS, bootloader or the partition table; no whole-chip erase is issued.
    stage('写入新程序', 10, 70)
    tool_command(serial_port, ['write-flash', '0x10000', str(image)])
    stage('核对写入', 70, 94)
    tool_command(serial_port, ['verify-flash', '0x10000', str(image)])
    stage('核对校准数据', 94, 100)
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
    print('完成！关闭这个窗口，重新打开「钢琴手套」软件就行。')
    return backup


def friendly_error(error):
    text = str(error)
    if re.search(r'could not open port|PermissionError|Access is denied|拒绝访问|busy', text, re.I):
        return '手套的 USB 口被别的程序占着。请先关掉「钢琴手套」软件（以及调试台黑色窗口），再点「再试一次」。'
    if re.search(r'Failed to connect|No serial data|timed out', text, re.I):
        return '连不上手套的主板。把 USB 线拔下来，等 3 秒再插上，然后点「再试一次」。'
    if '未找到CP210x' in text:
        return '没找到手套。请把手套的 USB 线插到电脑上，再点「再试一次」。'
    if '个手套主板' in text:
        return text
    return '升级没完成：' + text + '\n手套原来的程序一般不会被弄坏。重新插一下 USB 线再试一次；还不行就联系卖家。'


class Progress:
    """Receives esptool's printed output (its progress lines included) in the worker thread."""
    def __init__(self, post, log):
        self.post, self.log, self.span = post, log, (0, 0)

    def write(self, text):
        self.log.append(text)
        found = re.findall(r'(\d{1,3}(?:\.\d+)?)\s?%', text)
        if found:
            start, end = self.span
            self.post(('progress', start + (end - start) * min(100.0, float(found[-1])) / 100))
        return len(text)

    def flush(self):
        pass


def find_board(explicit=None):
    if explicit:
        return select_port(explicit)
    from serial.tools import list_ports
    found = [item.device for item in list_ports.comports() if (item.vid, item.pid) == (0x10C4, 0xEA60)]
    if not found:
        raise ValueError('未找到CP210x主控')
    if len(found) > 1:
        raise ValueError('电脑上插了 %d 个手套主板（%s），请只留下要升级的那一个，再点「再试一次」。' % (len(found), '、'.join(found)))
    return found[0]


def headless(image, manifest, explicit=None):
    """11-05 用户：更新固件不要重启软件。软件在后台调用本模式：不开窗口，每行输出一个 JSON 进度给软件显示。"""
    import contextlib
    out = sys.__stdout__

    def emit(**value):
        out.write(json.dumps(value, ensure_ascii=False) + chr(10)); out.flush()
    progress = Progress(lambda event: emit(percent=round(event[-1])) if event[0] in ('stage', 'progress') else None, [])

    def stage(name, start, end):
        progress.span = (start, end)
        emit(stage=name, percent=start)
    try:
        port = find_board(explicit)
        emit(stage='找到手套 ' + port, percent=0)
        with contextlib.redirect_stdout(progress), contextlib.redirect_stderr(progress):
            upgrade(port, image, manifest, stage)
        emit(done=True, percent=100, version=manifest.get('version'))
    except BaseException as error:  # esptool may raise SystemExit
        emit(error=friendly_error(error))
        sys.exit(1)


def gui(image, manifest, explicit=None, auto=False, relaunch=None):
    """大字中文窗口：三件事 → 开始升级 → 进度条 → 完成。不需要输入 YES。"""
    import contextlib
    import queue
    import threading
    import tkinter as tk
    from tkinter import ttk
    try:  # 只留图形窗口：自己单独占着的黑色控制台藏起来（从命令行启动时不藏）
        import ctypes
        kernel = ctypes.windll.kernel32
        if kernel.GetConsoleWindow() and kernel.GetConsoleProcessList((ctypes.c_uint * 4)(), 4) <= 1:
            ctypes.windll.user32.ShowWindow(kernel.GetConsoleWindow(), 0)
    except Exception:
        pass
    try:  # 高分屏上字不发虚
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.title('钢琴手套 · 固件升级')
    scale = max(1.0, root.winfo_fpixels('1i') / 96)
    root.geometry('%dx%d' % (660 * scale, 430 * scale))
    paper = '#fffdf6'
    root.configure(bg=paper)
    tk.Label(root, text='给手套升级新程序', font=('Microsoft YaHei UI', 20, 'bold'), bg=paper).pack(pady=(18, 6))
    tk.Label(root, text='升级前会先让舵机松开（戴着也没关系）。USB 线别拔。\n校准、编号和存好的曲子都会保留。',
             font=('Microsoft YaHei UI', 12), justify='left', fg='#52687c', bg=paper).pack(padx=28, anchor='w', pady=(2, 10))
    status = tk.Label(root, text='', font=('Microsoft YaHei UI', 14, 'bold'), bg=paper, wraplength=int(600 * scale), justify='left')
    status.pack(padx=28, pady=6, anchor='w')
    bar = ttk.Progressbar(root, length=int(600 * scale), maximum=100)
    bar.pack(padx=28, pady=6)
    button = tk.Button(root, text='开始升级', font=('Microsoft YaHei UI', 16, 'bold'), bg='#2e8b6e', fg='white',
                       activebackground='#24705a', activeforeground='white', relief='flat', padx=28, pady=8)
    button.pack(pady=16)
    events, log = queue.Queue(), []
    state = {'port': None, 'busy': False, 'done': False}

    def ready():
        try:
            state['port'] = find_board(explicit)
            status.config(text='已经找到手套。点下面的「开始升级」，大约 2 分钟。', fg='#24394c')
            button.config(text='开始升级', state='normal')
            if auto and not state['busy'] and not state['done']:
                root.after(300, press)
        except Exception as error:
            state['port'] = None
            status.config(text=friendly_error(error), fg='#b03a2e')
            button.config(text='再试一次', state='normal')

    def work(port):
        progress = Progress(events.put, log)

        def stage(name, start, end):
            progress.span = (start, end)
            events.put(('stage', name, start))
        try:
            with contextlib.redirect_stdout(progress), contextlib.redirect_stderr(progress):
                upgrade(port, image, manifest, stage)
            events.put(('done',))
        except BaseException as error:  # esptool may raise SystemExit
            events.put(('error', friendly_error(error)))

    def pump():
        try:
            while True:
                event = events.get_nowait()
                if event[0] in ('stage', 'progress'):
                    bar['value'] = event[-1]
                    status.config(text='正在升级 %d%% … 千万别拔线' % event[-1], fg='#24394c')
                elif event[0] == 'done':
                    state['busy'], state['done'] = False, True
                    bar['value'] = 100
                    if relaunch:
                        status.config(text='完成！正在重新打开「钢琴手套」…', fg='#2e8b6e')
                        button.config(text='关闭', state='normal')
                        try:
                            import subprocess
                            subprocess.Popen([relaunch], cwd=str(Path(relaunch).parent), close_fds=True)
                        except OSError:
                            status.config(text='完成！请自己重新打开「钢琴手套」软件。', fg='#2e8b6e')
                        root.after(2500, root.destroy)
                    else:
                        status.config(text='完成！关掉这个窗口，重新打开「钢琴手套」软件就行。', fg='#2e8b6e')
                        button.config(text='关闭', state='normal')
                elif event[0] == 'error':
                    state['busy'] = False
                    status.config(text=event[1], fg='#b03a2e')
                    button.config(text='再试一次', state='normal')
        except queue.Empty:
            pass
        root.after(120, pump)

    def press():
        if state['done']:
            root.destroy()
            return
        if state['busy']:
            return
        if not state['port']:
            ready()
            if not state['port']:
                return
        state['busy'] = True
        button.config(text='正在升级…', state='disabled')
        bar['value'] = 0
        threading.Thread(target=work, args=(state['port'],), daemon=True).start()

    def closing():
        if state['busy']:
            status.config(text='正在升级，现在不能关。请等进度走完（千万别拔线）。', fg='#b03a2e')
            return
        root.destroy()

    button.config(command=press)
    root.protocol('WM_DELETE_WINDOW', closing)
    ready()
    pump()
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='钢琴手套ESP32编译固件升级；不含固件源码')
    parser.add_argument('--port', help='指定COM口，省略则显示可选主控')
    parser.add_argument('--self-test', action='store_true', help='仅离线检查镜像和烧录工具，不打开COM')
    parser.add_argument('--console', action='store_true', help='文字窗口（输入编号和 YES），给售后/开发用')
    parser.add_argument('--auto', action='store_true', help='从钢琴手套软件「一键更新」打开：找到主板就自动开始')
    parser.add_argument('--relaunch', help='升级完自动重新打开的软件路径')
    parser.add_argument('--headless', action='store_true', help='给钢琴手套软件在后台调用：不开窗口，按行输出 JSON 进度')
    args = parser.parse_args(argv)
    image, manifest = load_image()
    if args.self_test:
        import esptool
        print(json.dumps(dict(ok=True, esptool_version=esptool.__version__,
                              firmware_sha256=manifest['sha256'], firmware_bytes=manifest['bytes'],
                              serial_opened=False, firmware_written=False), ensure_ascii=False))
        return
    if args.headless:
        headless(image, manifest, args.port)
        return
    if not args.console:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            pass
        else:
            gui(image, manifest, args.port, auto=args.auto, relaunch=args.relaunch)
            return
    print('本工具只升级主控应用固件；不设置舵机ID，保留校准和曲库。')
    print('请关掉钢琴手套软件，把手套摘下平放；主控USB保持连接。')
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
