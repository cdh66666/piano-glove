#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线开发用的「模拟手套」：TCP 装串口，说软件界面用到的 LIB 协议子集。

仅用于界面开发和演示，不在产品里，也不代表真实设备行为或性能：
- 手指位置按固定速度线性逼近目标，数值是示意，不是实测；
- 曲库存在内存里，进程退出即丢失；
- 不模拟断电保存、热点、真实舵机错误。

用法：
    python tools/dev/sim_glove.py 9702
    python host/bridge.py --url socket://127.0.0.1:9702
"""
import json
import socket
import socketserver
import struct
import sys
import threading
import time
import zlib
from pathlib import Path

HOST = Path(__file__).resolve().parents[2] / 'host'
sys.path.insert(0, str(HOST))
sys.path.insert(0, str(HOST / 'tests'))
from score_codec import decode, encode  # noqa: E402
import fake_glove  # noqa: E402

LO, HI, RANGE = 1180, 2620, 4095          # 示意行程：按下方向为 min
SPEED = 9000                              # counts/s，示意


def demo_scores():
    """两首很短的演示曲（自写简单旋律，非任何客户或版权资料）。"""
    def song(title, pitches, fingers, beat=420):
        notes = [dict(t_ms=i * beat, duration_ms=int(beat * .8), pitch=p, finger=f, velocity=96, amplitude_pct=100)
                 for i, (p, f) in enumerate(zip(pitches, fingers))]
        return encode(dict(version=1, hand='right', title=title, duration_ms=len(notes) * beat, notes=notes))
    return {
        1: song('五指热身 · 上行下行', [60, 62, 64, 65, 67, 65, 64, 62, 60], [1, 2, 3, 4, 5, 4, 3, 2, 1]),
        2: song('跳跳音阶小练习', [60, 64, 62, 65, 64, 67, 65, 64, 60], [1, 3, 2, 4, 3, 5, 4, 3, 1], 360),
    }


class Glove:
    def __init__(self):
        self.base = fake_glove.Device()
        self.base.calibrated = '1'
        self.lock = threading.RLock()
        self.library = demo_scores()
        self.pos = [2400, HI, HI, HI, HI, HI]
        self.target = list(self.pos)
        self.started = time.monotonic()
        self.reset_run()
        self.last_stop = 'none'
        self.upload = None
        self.tick_at = time.monotonic()

    def now_ms(self):
        return int((time.monotonic() - self.started) * 1000) & 0xffffffff

    def reset_run(self):
        self.active = False
        self.mode = 0
        self.slot = 0
        self.mask = 0
        self.tempo = 100
        self.hold = 100
        self.amp = 100
        self.owner = 0
        self.elapsed = 0.0
        self.duration = 0
        self.notes = []
        self.pattern = None
        self.keep_at = time.monotonic()

    # ---------- motion model ----------
    def press_target(self, amp):
        return int(HI - (HI - LO) * amp / 100)

    def tick(self):
        now = time.monotonic()
        dt, self.tick_at = now - self.tick_at, now
        if self.active and now - self.keep_at > 5:
            self.stop('keep_timeout')
        if self.active and self.mode == 0:
            self.elapsed += dt * 1000 * self.tempo / 100
            if self.elapsed >= self.duration:
                self.stop('complete')
            else:
                down = 0
                for n in self.notes:
                    if n['t_ms'] <= self.elapsed < n['t_ms'] + n['duration_ms']:
                        down |= 1 << (n['finger'] - 1)
                self.mask = down
        elif self.active and self.mode == 2:
            p = self.pattern
            step_ms = max(120, 600 * 100 / max(self.tempo, 50)) if p['rate'] else 180
            self.elapsed += dt * 1000
            p['step'] = min(p['total'], int(self.elapsed // step_ms))
            if p['step'] >= p['total']:
                self.stop('complete')
            else:
                seq = p['seq'][p['step']]
                self.mask = seq
        for i in range(1, 6):
            pressed = self.active and self.mask & (1 << (i - 1))
            self.target[i] = self.press_target(self.amp) if pressed else HI
        for i in range(6):
            delta = self.target[i] - self.pos[i]
            step = SPEED * dt
            self.pos[i] += max(-step, min(step, delta))
            self.pos[i] = int(self.pos[i])

    def stop(self, reason='stopped'):
        if self.active:
            self.last_stop = reason
        self.reset_run()

    def pattern_sequence(self, kind, repeats):
        one = [1 << i for i in range(5)]
        if kind == 0:
            seq = one + one[::-1][1:-1]
        elif kind == 1:
            seq = [0b00011, 0b00110, 0b01100, 0b11000, 0b10101, 0b01010]
        else:
            seq = [0b00001, 0b00100, 0b00010, 0b01000, 0b00100, 0b10000]
        out = []
        for _ in range(repeats):
            out.extend(seq)
            out.append(0)
        return out

    # ---------- protocol ----------
    def state_json(self):
        self.tick()
        now = self.now_ms()
        p = self.pattern or {}
        f = [[self.pos[i], self.target[i], 12, 120, 31, 4, 1000, 40, 1] for i in range(6)]
        b = [[LO, HI, 40, 1] for _ in range(6)]
        sn = len(self.notes)
        si = sum(1 for n in self.notes if n['t_ms'] <= self.elapsed) if self.mode == 0 else 0
        return json.dumps(dict(v=1, ct=1, ca=1, a=int(self.active), i=0, m=self.mode, s=self.slot,
                               t=int(self.elapsed), d=int(self.duration), q=self.tempo, k=self.mask, h=self.hold,
                               r=1, o=self.owner, e='none', x=0, z=0, p=0, l=self.last_stop, la=0, pa=0, pm=0,
                               ts=now, mm=0, pt=p.get('kind', 0), ps=p.get('step', 0), pc=p.get('total', 0),
                               pf=int(bool(p) and not p.get('rate')), cp=0, cl=-1, er=RANGE, b=b, f=f, pv=63,
                               si=si, sn=sn), separators=(',', ':'))

    def handle(self, cmd, out):
        with self.lock:
            self._handle(cmd, out)

    def _handle(self, cmd, out):
        t = cmd.strip().split()
        if not t:
            return
        v = t[0].upper()
        if v == 'INFO':
            out('OK INFO fw=PIANO_GLOVE_2 profile=STS3032 range=4095 probed=1 ap=PIANO_GLOVE_SIM ip=192.168.4.1 '
                'ap_ready=1 software_protocol=1 calibrated=1 armed=0 auto_active=0 enroll_active=0 enroll_next=1 '
                'enroll_temp=20 enroll_phase=OFF enroll_flow=3 enroll_resume=1 enroll_fix=20261021 online=6 sweep=0 '
                'ver=2.2.4-sim software_perf=r29 software_speed=native_max simulated=1')
            return
        if v == 'SAFE':
            self.stop('safe')
            out('OK SAFE torque=off')
            return
        if v != 'LIB':
            self.base.handle(cmd, out)
            return
        a = t[1].upper() if len(t) > 1 else 'INFO'
        if a == 'INFO':
            used = sum(len(x) for x in self.library.values())
            out('OK LIB INFO ready=1 count=%d max=100 release_usb=1 score_clock=continuous-v1 calibration_advisory=1 '
                'firmware_perf=r29 software_inset=0 software_speed=native_max play_from=1 chunk_max=384 upload_owner=none '
                'total=1376256 used=%d free=%d ap=PIANO_GLOVE_SIM ip=192.168.4.1' % (len(self.library), used, 1376256 - used))
        elif a == 'LIST':
            for slot in sorted(self.library):
                s = decode(self.library[slot])
                out('LIB_ITEM slot=%d bytes=%d stored=%d notes=%d duration_ms=%d title_hex=%s' % (
                    slot, len(self.library[slot]), len(self.library[slot]), len(s['notes']), s['duration_ms'],
                    s['title'].encode('utf-8').hex()))
            out('OK LIB LIST count=%d' % len(self.library))
        elif a == 'STATE':
            out('LIB_STATE ' + self.state_json())
            out('OK LIB STATE')
        elif a == 'PORTAL':
            out('LIB_PORTAL ' + json.dumps(dict(ssid='PIANO_GLOVE_SIM', ip='192.168.4.1', clients=0, open=True)))
            out('OK LIB PORTAL')
        elif a == 'READ':
            slot = int(t[2])
            blob = self.library.get(slot)
            if blob is None:
                out('ERR LIB empty_slot')
                return
            out('LIB_DATA hex=' + blob[:128].hex())
            for i in range(128, len(blob), 16):
                out('LIB_DATA hex=' + blob[i:i + 16].hex())
            out('OK LIB READ slot=%d' % slot)
        elif a == 'BEGIN':
            if self.active:
                out('ERR LIB active_STOP_first')
                return
            self.upload = dict(slot=int(t[2]), size=int(t[3]), data=bytearray())
            out('OK LIB BEGIN slot=%d' % self.upload['slot'])
        elif a == 'CHUNK':
            if not self.upload:
                out('ERR LIB no_upload')
                return
            self.upload['data'].extend(bytes.fromhex(t[2]))
            out('OK LIB CHUNK received=%d' % len(self.upload['data']))
        elif a == 'COMMIT':
            up, self.upload = self.upload, None
            try:
                decode(bytes(up['data']))
            except Exception:
                out('ERR LIB invalid_score')
                return
            self.library[up['slot']] = bytes(up['data'])
            out('OK LIB COMMIT slot=%d' % up['slot'])
        elif a == 'ABORT':
            self.upload = None
            out('OK LIB ABORT')
        elif a == 'DELETE':
            self.library.pop(int(t[2]), None)
            out('OK LIB DELETE slot=%s' % t[2])
        elif a == 'PLAY':
            slot, tempo, amp, hold = map(int, t[2:6])
            if slot not in self.library:
                out('ERR LIB empty_slot')
                return
            self.reset_run()
            s = decode(self.library[slot])
            self.active, self.mode, self.slot, self.tempo, self.amp, self.hold, self.owner = True, 0, slot, tempo, amp, hold, 1
            self.notes, self.duration = s['notes'], s['duration_ms']
            if len(t) > 6:  # r29.5 resume position
                self.elapsed = float(int(t[6]))
            out('OK LIB PLAY slot=%d' % slot)
        elif a == 'TRAIN':
            mask, hold, amp = map(int, t[2:5])
            self.reset_run()
            self.active, self.mode, self.mask, self.hold, self.amp, self.owner = True, 1, mask, hold, amp, 1
            out('OK LIB TRAIN mask=%d' % mask)
        elif a == 'PATTERN':
            kind, repeats, rate, amp, hold = map(int, t[2:7])
            self.reset_run()
            seq = self.pattern_sequence(kind, repeats)
            self.active, self.mode, self.amp, self.hold, self.owner = True, 2, amp, hold, 1
            self.tempo = rate or 100
            self.pattern = dict(kind=kind, rate=rate, seq=seq, step=0, total=len(seq))
            self.duration = len(seq) * 180
            out('OK LIB PATTERN pattern=%d' % kind)
        elif a == 'TEMPO':
            self.tempo = int(t[2])
            out('OK LIB TEMPO tempo=%d' % self.tempo)
        elif a == 'KEEP':
            self.keep_at = time.monotonic()
            out('OK LIB KEEP')
        elif a == 'STOP':
            self.stop('stopped')
            out('OK LIB STOP')
        elif a == 'RELEASE':
            self.stop('released')
            out('OK LIB RELEASE skipped=0')
        else:
            out('ERR LIB unknown_action')


GLOVE = Glove()


class Session(fake_glove.Session):
    def handle(self):
        self.request.settimeout(0.2)
        self._lock = threading.Lock()
        buf = b''
        self.emit('BOOT fw=PIANO_GLOVE_2 ready=1 simulated=1')
        while True:
            try:
                chunk = self.request.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b'\n' in buf:
                raw, buf = buf.split(b'\n', 1)
                cmd = raw.decode('utf-8', 'replace').strip()
                if cmd:
                    GLOVE.handle(cmd, self.emit)

    def emit(self, line):
        with self._lock:
            try:
                self.request.sendall((line + '\r\n').encode('utf-8'))
            except OSError:
                pass


def serve(port, ready=None):
    srv = fake_glove.Server(('127.0.0.1', port), Session)
    if ready:
        ready.set()
    srv.serve_forever()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9702
    print('模拟手套：socket://127.0.0.1:%d（仅供界面开发）' % port, flush=True)
    serve(port)
