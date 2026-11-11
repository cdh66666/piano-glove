"""Fixed-target local firmware maintenance. No hardware access until explicit flash.

Deployment source: sibling firmware, or PIANO_GLOVE_FIRMWARE_SOURCE at startup.
PlatformIO defaults to the current user home. GET status
reports the actual absolute source, board, baud and detected MAC for review.
The API accepts no arbitrary path, binary, command, board or baud override.
GET /api/firmware; POST /api/firmware/build {}; POST /api/firmware/flash
{port: COMx}. Only flash reserves the serial interface. External bus power may stay on.
Only flash opens/resets the board. Failed flash leaves reconnection paused.
No erase-all: write ranges are 1000,8000,e000,10000; NVS 9000..dfff is retained.
written/hashVerified/verified distinguish write, byte verification and INFO readback.
"""
import os
import functools
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

LOCAL_SOURCE = Path(__file__).resolve().parent.parent / 'firmware'
# Startup-only deployment configuration; never accepted from an HTTP request.
SOURCE = Path(os.environ.get('PIANO_GLOVE_FIRMWARE_SOURCE', str(LOCAL_SOURCE))).resolve()
PIO_HOME = Path(os.environ.get('PLATFORMIO_CORE_DIR', str(Path.home() / '.platformio')))
PYTHON = PIO_HOME / 'penv/Scripts/python.exe'
PIO = PIO_HOME / 'penv/Scripts/pio.exe'
ESPTOOL = PIO_HOME / 'packages/tool-esptoolpy/esptool.py'
# 冻结镜像：随程序一起分发，现场只烧这一份，不做任何编译。
IMAGE_DIR = Path(__file__).resolve().parent / 'assets' / 'firmware'
IMAGE_MANIFEST = IMAGE_DIR / 'manifest.json'
FALLBACK_VERSION = '2.2.5-r29.8'


def image_directory():
    """开发时在 host/assets/firmware，打包后在 _MEIPASS/web/firmware。"""
    candidates = []
    try:
        import customer_runtime as runtime
        candidates.append(Path(runtime.resources()) / 'firmware')
    except Exception:
        pass
    candidates.append(IMAGE_DIR)
    for path in candidates:
        if (path / 'manifest.json').is_file():
            return path
    return candidates[-1]


class FirmwareImageError(RuntimeError):
    pass


def read_image(directory=None):
    """读取并校验冻结镜像。任何一项对不上就抛错 —— 宁可烧不了，也不烧错东西。

    返回 dict(version, images=[(offset, Path, sha256)], manifest)。
    校验项：分区表布局、每个文件的大小与 SHA-256、固件是否超出 app0 分区。
    """
    directory = Path(directory or image_directory())
    manifest_path = directory / 'manifest.json'
    if not manifest_path.is_file():
        raise FirmwareImageError('程序里没有固件镜像（缺少 manifest.json），无法烧录')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as error:
        raise FirmwareImageError('固件清单损坏：' + str(error))
    rows = manifest.get('images')
    if not isinstance(rows, list) or len(rows) != 4:
        raise FirmwareImageError('固件清单内容不完整')
    images, seen = [], set()
    for row in rows:
        name = str(row.get('name') or '')
        path = directory / Path(name).name
        if not name or Path(name).name != name or name in seen:
            raise FirmwareImageError('固件清单里有非法文件名')
        seen.add(name)
        if not path.is_file():
            raise FirmwareImageError('固件文件缺失：' + name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != str(row.get('sha256')):
            raise FirmwareImageError('固件文件被改动或损坏：' + name)
        offset = int(row.get('offset_int', int(str(row.get('offset', '0')), 16)))
        size = path.stat().st_size
        if offset + size > 0x400000:
            raise FirmwareImageError('固件偏移超出 4MB Flash：' + name)
        if offset < 0xe000 and offset + size > 0x9000:
            raise FirmwareImageError('镜像侵入校准 NVS（0x9000~0xdfff），拒绝写入')
        if offset == 0x10000 and size > 0x140000:
            raise FirmwareImageError('固件超出 app0 分区')
        images.append((offset, path, digest))
    images.sort(key=lambda item: item[0])
    needed = {0x1000, 0x8000, 0xe000, 0x10000}
    if {offset for offset, _, _ in images} != needed:
        raise FirmwareImageError('固件清单的写入区间不是固定的 1000/8000/e000/10000')
    return dict(version=str(manifest.get('version') or FALLBACK_VERSION),
                images=images, manifest=manifest)


def esptool_command():
    """返回 (前缀参数)。冻结后跑自己（--esptool 透传给 esptool），未冻结用 python -m esptool。"""
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--esptool']
    try:
        import esptool  # noqa: F401
        return [sys.executable, '-m', 'esptool']
    except Exception:
        pass
    if ESPTOOL.exists():
        return [str(PYTHON), str(ESPTOOL)]
    raise FirmwareImageError('找不到 esptool：既没有安装模块，也没有 PlatformIO 工具链')



def exclusive(method):
    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        with self._maintenance_lock:
            if self.firmware.serialExclusive and self.firmware.owner != threading.get_ident():
                raise RuntimeError('固件维护中：串口操作已锁定')
            return method(self, *args, **kwargs)
    return guarded


class FirmwareManager:
    def __init__(self, bridge, enumerate_ports=None):
        self.bridge = bridge
        self.owner = None
        self.busy = False
        self.serialExclusive = False
        self._lock = threading.RLock()
        self._log = deque(maxlen=180)
        self._data = dict(state='idle', phase='idle', progress=0, error='',
                          verified=False, readback=None, written=False, hashVerified=False)
        if enumerate_ports is None:
            from serial.tools.list_ports import comports
            enumerate_ports = comports
        self.enumerate_ports = enumerate_ports

    def ports(self):
        return [dict(port=p.device, device=p.device, label=p.description,
                     vid=p.vid, pid=p.pid, serialNumber=p.serial_number,
                     eligible=p.vid == 0x10c4 and p.pid == 0xea60)
                for p in self.enumerate_ports()]

    def available(self):
        """有冻结镜像就能烧 —— 不再要求本机装 PlatformIO 或源码。"""
        try:
            read_image()
            return True
        except FirmwareImageError:
            return False

    def status(self):
        with self._lock:
            data = dict(self._data)
        try:
            image = read_image()
            bundle = dict(bundled=True, version=image['version'],
                          built_at=image['manifest'].get('built_at', ''),
                          images=[dict(name=path.name, offset=hex(offset), bytes=path.stat().st_size,
                                       sha256=digest)
                                  for offset, path, digest in image['images']])
            version, error = image['version'], ''
        except FirmwareImageError as exc:
            bundle, version, error = dict(bundled=False), FALLBACK_VERSION, str(exc)
        return dict(data, busy=self.busy, serialExclusive=self.serialExclusive, log=list(self._log),
                    version=version, buildRequired=False, image=bundle,
                    imageError=error, imageDir=str(image_directory()),
                    board='esp32dev', baud=230400, ports=self.ports(), available=self.available(),
                    source=str(SOURCE), selected=self.bridge.port if self.bridge else None)

    def update(self, **values):
        with self._lock:
            self._data.update(values)

    def log(self, line):
        with self._lock:
            self._log.append(str(line)[-1200:])

    def identity(self, port):
        if not isinstance(port, str) or not re.fullmatch(r'COM[1-9][0-9]*', port):
            raise ValueError('请选择明确的 COM 串口')
        p = next((p for p in self.ports() if p['port'] == port), None)
        if not p or not p['eligible']:
            raise ValueError('仅支持 CP2102 (10C4:EA60) 的指定 ESP32 主控；禁止 ESP32-S3')
        return (p['port'], p['vid'], p['pid'], p['serialNumber'])

    def start(self, action, body):
        if not isinstance(body, dict):
            raise ValueError('请求必须为对象')
        if action == 'build':
            if body:
                raise ValueError('编译请求必须为空对象')
            identity = None
        elif action == 'flash':
            if set(body) != {'port'}:
                raise ValueError('烧录请求仅接受所选 port')
            identity = self.identity(body['port'])
        else:
            raise ValueError('未知维护操作')
        with self.bridge._maintenance_lock, self._lock:
            if self.busy:
                raise RuntimeError('固件维护正在执行')
            if not self.available():
                raise RuntimeError('程序里没有可用的固件镜像（assets/firmware），或镜像校验未通过')
            if action == 'flash' and self.bridge.connected and self.bridge.port != body['port']:
                raise ValueError('所选端口与当前已连接主控不一致')
            self.busy = True
            self.serialExclusive = action == 'flash'
            self._log.clear()
            self._data = dict(state='running', phase='queued', progress=0, error='',
                              verified=False, readback=None, written=False, hashVerified=False)
            threading.Thread(target=self._worker, args=(action, body.get('port'), identity),
                             name='pg-firmware', daemon=True).start()
        return self.status()

    def run(self, args, timeout=240, on_line=None):
        # No shell, no caller-provided flags; CREATE_NO_WINDOW prevents console flashes.
        # 子进程输出要不带缓冲，否则进度攒成一大块才到（写入停在一个数很久再突然跳到验证）
        proc = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                env=dict(os.environ, PYTHONUNBUFFERED='1'),
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = deque(maxlen=250)
        timed_out = threading.Event()
        def kill():
            timed_out.set()
            proc.kill()
        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            # 11-11 用户：写入时进度一直不动，突然跳到“验证”。esptool 用回车 \r 在同一行里刷新百分比，
            # 按换行读要等整个文件写完才收到；所以 \r 和换行都当一行。
            buffer = []
            def emit():
                line = ''.join(buffer).strip()
                buffer.clear()
                if not line:
                    return
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:
                        pass
                if not re.search(r'\d%\s+\d+/\d+ bytes', line) or line.endswith('100.0%') or ' 100.0% ' in line:
                    self.log(line)
                lines.append(line)
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                if ch in '\r\n':
                    emit()
                else:
                    buffer.append(ch)
            emit()
            result = proc.wait()
            if timed_out.is_set() or result:
                raise RuntimeError('工具超时' if timed_out.is_set() else '工具失败，退出码 %s' % result)
        finally:
            timer.cancel()
            proc.stdout.close()
        return '\n'.join(lines)

    def build(self):
        """返回要烧写的 (偏移, 文件) 列表。

        现场**不再编译**：直接交出随程序分发的冻结镜像。原来这里跑 PlatformIO，
        客户机上只要没装工具链就整个烧录按钮是灰的；现在只要程序本身在就能烧。
        """
        image = read_image()
        firmware = next(path for offset, path, _ in image['images'] if offset == 0x10000)
        self.update(phase='build', progress=10, buildSha256=hashlib.sha256(firmware.read_bytes()).hexdigest())
        self.log('使用内置镜像 ' + image['version'] + '（' + firmware.name + '），未做本地编译')
        return [(offset, path) for offset, path, _ in image['images']]

    def _worker(self, action, port, identity):
        self.owner = threading.get_ident()
        bridge = self.bridge
        if action == 'flash':
            bridge.paused = True
        try:
            if action == 'flash':
                self.update(phase='stop', progress=2)
                if not bridge.connected:
                    ok, why = bridge.open(port, 115200)
                    if not ok:
                        raise RuntimeError(why)
                    time.sleep(2)
                if bridge.port != port:
                    raise RuntimeError('连接端口改变，拒绝烧录')
                stopped = []
                # Legacy SAFE/RATE STOP release old goals; DISARM must precede them.
                for command in ('DISARM', 'RATE STOP', 'SAFE'):
                    result = bridge.send(command, timeout_ms=1200)
                    stopped.extend(result.get('lines', []))
                confirmed = (any(s.startswith('OK DISARM') and 'armed=0' in s for s in stopped)
                             and any(s.startswith('OK RATE stopped') for s in stopped)
                             and any(s.startswith('OK SAFE') and 'armed=0' in s for s in stopped))
                self.update(stopConfirmed=confirmed, stopLog=stopped[-20:])
                self.log('旧动作停止已确认' if confirmed else '旧固件未确认停止；后续仅进入 ROM 识别，不恢复任何目标')
                bridge.close()
            artifacts = self.build()
            expected_version = read_image()['version']
            if action == 'build':
                self.update(state='built', phase='complete', progress=100)
                return
            # Recheck current USB identity after preparing the image.
            if self.identity(port) != identity:
                raise RuntimeError('USB 设备身份已改变，请重新选择')
            base = esptool_command() + ['--chip', 'esp32', '--port', port, '--baud', '230400']
            self.update(phase='identify', progress=35)
            info = self.run(base + ['chip_id'], 25)
            mac = re.search(r'MAC:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})', info, re.I)
            # esptool 4 写 “Chip is ESP32-D0WD…”，5 写 “Chip type:  ESP32-D0WD-V3”；两种都认，S/C 系列一律拒绝
            chip = re.search(r'Chip (?:is|type:)\s*(ESP32[^\s(]*)', info)
            if not chip or re.match(r'ESP32-[SCHP][0-9]', chip.group(1)) or not mac:
                raise RuntimeError('未确认经典 ESP32 芯片及 MAC，拒绝写入')
            self.update(detectedMac=mac.group(1).lower(), chip='ESP32')
            with tempfile.TemporaryDirectory(prefix='piano-firmware-') as directory:
                args, hashes = [], {}
                for offset, source in artifacts:
                    target = Path(directory)/source.name
                    shutil.copyfile(source, target)
                    # Never touch the calibration NVS interval 0x9000..0xdfff.
                    size = target.stat().st_size
                    if offset < 0xe000 and offset + size > 0x9000:
                        raise RuntimeError('镜像侵入 NVS，拒绝写入')
                    if offset == 0x10000 and size > 0x140000:
                        raise RuntimeError('固件超出固定 app0 分区')
                    hashes[source.name] = hashlib.sha256(target.read_bytes()).hexdigest()
                    args += [hex(offset), target]
                self.update(phase='write', progress=45, hashes=hashes)
                # esptool 的输出不接屏幕时，写程序本体只报 0% 和一次 2.6%，之后 20~30 秒一声不吭。
                # 按“压缩后字节数 ÷ 实测速度”估算总用时，每半秒按时间推进；真报了百分比就按真的走。
                baud = next((int(base[i + 1]) for i in range(len(base) - 1) if str(base[i]) in ('--baud', '-b')), 230400)
                timing = dict(start=None, expected=None, real=0.0, done=False)
                def write_progress(line):
                    c = re.search(r'Compressed (\d+) bytes to (\d+)', line)
                    if c and int(c.group(1)) > 100000:
                        timing.update(start=time.monotonic(), expected=max(3.0, int(c.group(2)) / (22000.0 * baud / 230400)))
                    m = re.search(r'Writing at 0x([0-9a-fA-F]+).*?(\d+(?:\.\d+)?)%\s+(\d+)/(\d+) bytes', line)
                    if m and timing['start'] is not None and int(m.group(4)) > 100000:
                        timing['real'] = max(timing['real'], float(m.group(2)) / 100)
                    if re.search(r'Wrote \d+ bytes .* at 0x0*10000', line):
                        timing['done'] = True
                def ticker():
                    while not timing['done']:
                        time.sleep(0.5)
                        if timing['start'] is None:
                            continue
                        guess = min(0.97, (time.monotonic() - timing['start']) / timing['expected'])
                        self.update(phase='write', progress=45 + min(29, int(max(guess, timing['real']) * 29)))
                tick = threading.Thread(target=ticker, daemon=True)
                tick.start()
                try:
                    self.run(base + ['write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep', '--flash_size', 'keep'] + args, 150,
                             on_line=write_progress)
                finally:
                    timing['done'] = True
                self.update(written=True, phase='verify', progress=75)
                self.run(base + ['verify_flash'] + args, 150)
                self.update(hashVerified=True, phase='readback', progress=90)
            if self.identity(port) != identity:
                raise RuntimeError('回读前 USB 身份改变')
            ok, why = bridge.open(port, 115200)
            if not ok:
                raise RuntimeError(why)
            time.sleep(2)
            for attempt in range(5):
                response = bridge.send('INFO', timeout_ms=1500)
                line = next((s for s in response.get('lines', []) if s.startswith('OK INFO ')), '')
                fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
                if fields.get('fw') == 'PIANO_GLOVE_2' and fields.get('ver') == expected_version and fields.get('armed') == '0':
                    self.update(readback=fields, verified=True, state='verified', phase='complete', progress=100,
                                flashedVersion=expected_version)
                    return
                self.update(readback=fields or None)
                time.sleep(.4)
            raise RuntimeError('写入及 Flash 校验完成，但 INFO 版本/armed=0 回读未通过')
        except Exception as exc:
            self.log(str(exc))
            self.update(state='written_unverified' if self._data.get('written') else 'failed',
                        phase='failed', error=str(exc))
            if action == 'flash':
                bridge.close()
        finally:
            # Verified firmware is already disarmed. Resume connection checks only;
            # failed/unverified writes stay paused, and movement is never resumed.
            if action == 'flash':
                bridge.paused = not self._data.get('verified', False)
            with self._lock:
                self.busy = False
                self.serialExclusive = False
                self.owner = None
