"""模拟手机连手套热点（不碰电脑的网络）。

手机连热点后打开的是手套固件里内置的手机页（firmware/phone-ui），它通过
/api/... 跟手套说话。这里在本机 127.0.0.1 上原样提供这一套手机页，
把 /api/... 转给 USB 串口桥（host/bridge.py，接真手套），并可以人为制造
Wi-Fi 那样的延迟和“卡一下”。电脑的网卡、路由、Wi-Fi 一概不动。

和真热点的差别（如实说明）：
- 没有经过手套的无线芯片，测不到无线信号本身的问题；
- 固件对 Wi-Fi 播放给 5 秒续约宽限，对 USB 只给 2 秒。这里在卡顿期间按
  “手机最后一次续约后 5 秒内”替手机向 USB 续约，模拟固件的 Wi-Fi 宽限。

用法：python tools/phone_sim/phone_sim_server.py --bridge 8197 --port 8196 \
        --latency 20,80 --stall-every 8 --stall 1.6
"""
import argparse, json, random, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHONE = ROOT / 'firmware' / 'phone-ui'
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}
WIFI_LEASE_S = 5.0  # firmware/src/library_controller.h leaseTimeoutMs(wireless, score)


class Sim:
    def __init__(self, a):
        self.bridge = f'http://127.0.0.1:{a.bridge}'
        self.lat = tuple(int(x) for x in a.latency.split(','))
        self.stall_every, self.stall = a.stall_every, a.stall
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.last_keep = 0.0
        self.controller = ''
        self.playing = False
        self.log = []
        self.kbps = a.air_kbps
        self.device = threading.Lock()  # the glove's web server answers one request at a time
        self.ui = Path(a.ui_dir) if a.ui_dir else PHONE

    def stalled_until(self, now):
        """Wi-Fi hiccup windows: every stall_every s, all traffic waits stall s."""
        if not self.stall_every or not self.stall:
            return 0
        phase = (now - self.t0) % self.stall_every
        start = self.stall_every - self.stall
        return now + (self.stall_every - phase) if phase >= start else 0

    def delay(self):
        now = time.time()
        until = self.stalled_until(now)
        wait = (until - now if until else 0) + random.uniform(*self.lat) / 1000
        time.sleep(max(0, wait))
        return wait

    def note(self, **kw):
        with self.lock:
            self.log.append(dict(t=round(time.time() - self.t0, 3), **kw))

    def forward(self, method, path, body, headers):
        req = urllib.request.Request(self.bridge + path, data=body if method == 'POST' else None, method=method)
        for k in ('Content-Type', 'X-Piano-Controller'):
            if headers.get(k):
                req.add_header(k, headers[k])
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers.get('Content-Type', 'application/json'), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Content-Type', 'application/json'), e.read()

    def keeper(self):
        """Firmware gives Wi-Fi score playback 5 s; USB owner only 2 s."""
        while True:
            time.sleep(0.4)
            if self.playing and self.controller and time.time() - self.last_keep < WIFI_LEASE_S:
                try:
                    self.forward('POST', '/api/keep', b'', {'Content-Type': 'application/x-www-form-urlencoded',
                                                            'X-Piano-Controller': self.controller})
                except Exception:
                    pass


def make_handler(sim):
    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'  # firmware closes after each response

        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                sim.note(path=self.path, aborted=True)

        def _api(self, method):
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0)) if method == 'POST' else b''
            path = self.path.split('?')[0]
            began = time.time()
            waited = sim.delay()  # request travels over the air
            if path == '/api/keep':
                sim.last_keep = time.time()
                sim.controller = self.headers.get('X-Piano-Controller') or sim.controller
            if path == '/api/play':
                sim.controller = self.headers.get('X-Piano-Controller') or sim.controller
                sim.last_keep = time.time()
            with sim.device:
                code, ctype, data = sim.forward(method, self.path, body, self.headers)
                air = len(data) / (sim.kbps * 1024) if sim.kbps else 0
                time.sleep(air)  # sending the reply over the air keeps the glove busy
            if path == '/api/play' and code == 200:
                sim.playing = True
            if path == '/api/stop':
                sim.playing = False
                sim.note(path=path, body=body.decode('utf-8', 'replace')[:80])
            if path == '/api/software/status' and code == 200:
                # On the glove hotspot there is no bridge: the page then says "手套热点".
                j = json.loads(data)
                for k in ('bridge', 'connected', 'port', 'ports', 'firmware'):
                    j.pop(k, None)
                data = json.dumps(j).encode()
            if path == '/api/state' and code == 200:
                j = json.loads(data)
                if not j.get('active'):
                    sim.playing = False
            sim.note(path=path, code=code, ms=round((time.time() - began) * 1000), air_ms=round(waited * 1000))
            self._send(code, ctype, data)

        def do_GET(self):
            if self.path.startswith('/api/'):
                return self._api('GET')
            if self.path == '/sim/log':
                with sim.lock:
                    return self._send(200, 'application/json', json.dumps(sim.log).encode())
            name = self.path.split('?')[0].lstrip('/') or 'software.html'
            f = sim.ui / name
            if f.suffix in TYPES and f.is_file() and f.parent == sim.ui:
                return self._send(200, TYPES[f.suffix], f.read_bytes())
            self._send(404, 'text/plain', b'not found')

        def do_POST(self):
            if self.path.startswith('/api/'):
                return self._api('POST')
            self._send(404, 'text/plain', b'not found')
    return H


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=8196)
    p.add_argument('--bridge', type=int, default=8197)
    p.add_argument('--latency', default='20,80', help='每次请求的无线往返毫秒范围')
    p.add_argument('--stall-every', type=float, default=0, help='每隔几秒卡一次（0=不卡）')
    p.add_argument('--stall', type=float, default=0, help='每次卡几秒')
    p.add_argument('--air-kbps', type=float, default=120, help='手套热点下发数据速度 KB/s（0=不算）')
    p.add_argument('--ui-dir', help='换一份手机页（比如改动前的版本）')
    a = p.parse_args()
    sim = Sim(a)
    threading.Thread(target=sim.keeper, daemon=True).start()
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), make_handler(sim))
    print(f'phone sim on http://127.0.0.1:{a.port}/ -> bridge {a.bridge}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
