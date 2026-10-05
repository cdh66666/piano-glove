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
VERSION = '2.2.4'


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
        return all(p.exists() for p in (SOURCE/'platformio.ini', PIO, PYTHON, ESPTOOL))

    def status(self):
        with self._lock:
            return dict(self._data, busy=self.busy, serialExclusive=self.serialExclusive, log=list(self._log), version=VERSION,
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
                raise RuntimeError('固定源码或 PlatformIO 工具链不可用')
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

    def run(self, args, timeout=240):
        # No shell, no caller-provided flags; CREATE_NO_WINDOW prevents console flashes.
        proc = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = deque(maxlen=250)
        timed_out = threading.Event()
        def kill():
            timed_out.set()
            proc.kill()
        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    self.log(line)
                    lines.append(line)
            result = proc.wait()
            if timed_out.is_set() or result:
                raise RuntimeError('工具超时' if timed_out.is_set() else '工具失败，退出码 %s' % result)
        finally:
            timer.cancel()
            proc.stdout.close()
        return '\n'.join(lines)

    def build(self):
        config = (SOURCE/'platformio.ini').read_text(encoding='utf-8')
        main = (SOURCE/'src/main.cpp').read_text(encoding='utf-8')
        if not re.search(r'^board\s*=\s*esp32dev\s*$', config, re.M) or not re.search(r'^upload_speed\s*=\s*230400\s*$', config, re.M):
            raise RuntimeError('固定板型或波特率配置已改变，拒绝编译烧录')
        if not re.search(r'#define\s+FW_VER\s+"' + re.escape(VERSION) + '"', main):
            raise RuntimeError('源码版本不匹配安全版 ' + VERSION)
        if not re.search(r'^platform\s*=\s*espressif32@6\.4\.0\s*$', config, re.M):
            raise RuntimeError('平台版本发生变化')
        for package, expected in [('framework-arduinoespressif32', '3.20011.230801'),
                                  ('toolchain-xtensa-esp32', '8.4.0+2021r2-patch5'),
                                  ('tool-esptoolpy', '1.40501.0'), ('tool-scons', '4.40801.0')]:
            manifest = PIO_HOME/'packages'/package/'package.json'
            if not manifest.exists() or json.loads(manifest.read_text())['version'] != expected:
                raise RuntimeError('本机固定工具链缺失或版本变化：' + package)
        self.update(phase='build', progress=10)
        # Block dependency downloads: missing cached packages must fail, never update tools.
        offline = "import socket,runpy; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Firmware build is offline; dependency downloads disabled')); runpy.run_module('platformio',run_name='__main__')"
        self.run([PYTHON, '-c', offline, 'run', '-d', SOURCE, '-e', 'esp32dev'], 300)
        output = SOURCE/'.pio/build/esp32dev'
        partitions = (output/'partitions.bin').read_bytes()
        entries = {}
        for start in range(0, len(partitions)-31, 32):
            magic, kind, subtype, offset, size, name, flags = struct.unpack('<HBBII16sI', partitions[start:start+32])
            if magic == 0x50aa:
                entries[name.rstrip(b'\0').decode()] = (offset, size)
        if entries.get('nvs') != (0x9000, 0x5000) or entries.get('app0') != (0x10000, 0x140000):
            raise RuntimeError('分区布局改变，拒绝覆盖现有 NVS 校准')
        self.update(buildSha256=hashlib.sha256((output/'firmware.bin').read_bytes()).hexdigest())
        return [(0x1000, output/'bootloader.bin'), (0x8000, output/'partitions.bin'),
                (0xe000, PIO_HOME/'packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin'),
                (0x10000, output/'firmware.bin')]

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
            if action == 'build':
                self.update(state='built', phase='complete', progress=100)
                return
            # Recheck current USB identity after potentially lengthy compilation.
            if self.identity(port) != identity:
                raise RuntimeError('USB 设备身份已改变，请重新选择')
            base = [PYTHON, ESPTOOL, '--chip', 'esp32', '--port', port, '--baud', '230400']
            self.update(phase='identify', progress=35)
            info = self.run(base + ['chip_id'], 25)
            mac = re.search(r'MAC:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})', info, re.I)
            if not re.search(r'Chip is ESP32(?:\s|\(|-|$)', info) or re.search(r'Chip is ESP32-[SC][0-9]', info) or not mac:
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
                self.run(base + ['write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep', '--flash_size', 'keep'] + args, 150)
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
                if fields.get('fw') == 'PIANO_GLOVE_2' and fields.get('ver') == VERSION and fields.get('armed') == '0':
                    self.update(readback=fields, verified=True, state='verified', phase='complete', progress=100)
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
