#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在普通浏览器里预览「EXE 桌面窗口」界面，供离线界面开发与截图核对。

真实的 DesktopAPI / NativeAPI / bridge 逻辑全部在本进程运行；只把
pywebview 的 js_api 换成一个本机 HTTP 代理（/rpc），页面内容仍由
native_window.render_page 生成，与 EXE 内使用同一套内联规则。

默认连接 tools/dev/sim_glove.py 的模拟手套，不打开真实串口：

    python tools/dev/dev_preview.py            # http://127.0.0.1:8130/
    python tools/dev/dev_preview.py --no-device   # 模拟「手套未连接」
    python tools/dev/dev_preview.py --device COM9 # 真实手套（只在空载时用）

数据目录放在临时目录（不碰 %LOCALAPPDATA%\\PianoGloveSoftware）。
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / 'host'
sys.path.insert(0, str(HOST))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SHIM = r"""<script>
(function(){
 const realFetch=window.fetch.bind(window);
 const call=(name,args)=>realFetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,args})}).then(r=>r.json()).then(v=>{if(v.error)throw Error(v.error);if(name==='open_page'&&v.navigate)setTimeout(()=>location.href=v.navigate,60);return v.result;});
 const api=new Proxy({},{get:(_,name)=>name==='then'?undefined:(...args)=>call(String(name),args)});
 window.pywebview={api};
 setTimeout(()=>window.dispatchEvent(new Event('pywebviewready')),0);
})();
</script>"""


def build(args):
    data = Path(args.data or tempfile.mkdtemp(prefix='piano-glove-preview-'))
    os.environ['LOCALAPPDATA'] = str(data)
    import bridge
    import customer_runtime as runtime
    import native_window
    bridge.HOST_DIR = str(HOST)
    bridge.RUNTIME_DATA_DIR = str(runtime.data_directory())
    url = args.device
    if not url and not args.no_device:
        import sim_glove
        ready = threading.Event()
        threading.Thread(target=sim_glove.serve, args=(args.sim_port, ready), daemon=True).start()
        ready.wait(3)
        url = 'socket://127.0.0.1:%d' % args.sim_port
    session = bridge.Bridge(url=url, baud=115200, auto=bool(url))
    session.paused = not url

    class PreviewAPI(native_window.DesktopAPI):
        def open_page(self, page):
            if page not in native_window.PAGES:
                raise ValueError('未知页面')
            return {'ok': True, '_navigate': '/page/' + page + ('#licenses' if page == 'licenses' else '#connect' if page == 'debug' else '')}

        def save_file(self, content, name):
            import base64
            target = data / 'saved' / Path(str(name)).name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(base64.b64decode(content))
            return {'ok': True, 'saved': True, 'path': str(target)}

        def phone_connection(self):
            try:
                return super().phone_connection()
            except ImportError:
                return {'ok': True, 'ssid': 'PIANO_GLOVE_SIM', 'url': 'http://192.168.4.1/', 'wifi_qr': '', 'url_qr': ''}

    api = PreviewAPI(session)
    if url:
        threading.Thread(target=session._autoloop, name='glove-usb', daemon=True).start()
    return api, native_window, data


def serve(args):
    api, native_window, data = build(args)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, kind='text/html; charset=utf-8'):
            body = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path in ('/', '/index.html'):
                self.send_response(302)
                self.send_header('Location', '/page/software')
                self.end_headers()
                return
            if path.startswith('/page/'):
                name = path[6:]
                if name not in native_window.PAGES:
                    return self.send(404, 'no page')
                text = native_window.render_page(name, HOST)
                text = text.replace('<head>', '<head>' + SHIM, 1) if '<head>' in text else SHIM + text
                return self.send(200, text)
            self.send(404, 'not found', 'text/plain')

        def do_POST(self):
            if self.path != '/rpc':
                return self.send(404, 'not found', 'text/plain')
            payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            name, call_args = payload.get('name', ''), payload.get('args') or []
            try:
                if name.startswith('_') or not callable(getattr(api, name, None)):
                    raise AttributeError('没有这个接口：' + name)
                result = getattr(api, name)(*call_args)
                reply = {'result': result}
                if name == 'open_page' and isinstance(result, dict) and result.get('_navigate'):
                    reply['navigate'] = result.pop('_navigate')
            except Exception as error:  # surfaced to the page like a pywebview rejection
                reply = {'error': str(error)}
            self.send(200, json.dumps(reply, ensure_ascii=False, default=str), 'application/json; charset=utf-8')

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print('预览：http://127.0.0.1:%d/   数据目录：%s' % (args.port, data), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='桌面界面浏览器预览（模拟手套）')
    p.add_argument('--port', type=int, default=8130)
    p.add_argument('--sim-port', type=int, default=9702)
    p.add_argument('--no-device', action='store_true', help='不连接模拟手套')
    p.add_argument('--device', help='显式连接真实手套串口（如 COM9），会驱动真实动作')
    p.add_argument('--data', help='数据目录（默认临时目录）')
    serve(p.parse_args())
