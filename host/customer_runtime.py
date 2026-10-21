"""Customer executable / source launcher. Starting the UI never sends movement goals."""
import argparse
import base64
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

BUILD_DATE = '20261014'
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def resources():
    return Path(sys._MEIPASS) / 'web' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def data_directory():
    root = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'PianoGloveSoftware'
    root.mkdir(parents=True, exist_ok=True)
    return root


def json_get(url, timeout=2):
    with build_opener(ProxyHandler({})).open(url, timeout=timeout) as response:
        return json.load(response)


def existing_service(port):
    try:
        return json_get('http://127.0.0.1:%d/api/status' % port)
    except (URLError, OSError):
        return None


def open_existing(port, expected_serial, page, launch_browser):
    state = existing_service(port)
    if state is None:
        return False
    if not isinstance(state, dict) or 'connected' not in state:
        raise RuntimeError('%d 端口已有其他程序，请关闭该程序或指定其他端口。' % port)
    if expected_serial and state.get('fixed') != expected_serial:
        raise RuntimeError('现有调试台连接其他串口，请先关闭其窗口再启动本包。')
    # Do not silently open an old console with incompatible software files.
    try:
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:%d/software.js' % port, timeout=2) as reply:
            served = reply.read()
    except (URLError, OSError) as error:
        raise RuntimeError('旧版调试台正在运行，请先关闭其黑色窗口，再启动本包。') from error
    expected = (resources() / 'software.js').read_bytes()
    if served.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n'):
        raise RuntimeError('另一版本调试台正在运行，请先关闭它的黑色窗口，再启动本包。')
    if launch_browser:
        webbrowser.open('http://127.0.0.1:%d/%s' % (port, page))
    print('已使用正在运行的同版调试台。')
    return True


def self_test():
    """Checks the frozen native dependencies and real PDF pipeline, without COM access."""
    import serial
    import pypdfium2
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    import bridge
    from score_codec import encode, decode
    asset_root = resources()
    required = ['software.html', 'software.js', 'software.css', 'software-audio.js', 'software-pack.js', 'software-review.js', 'software-review.css', 'web_piano_glove.html',
                'delivery-demo.js', 'delivery-shell.js', 'delivery-shell.css']
    for name in required:
        if not (asset_root / name).is_file():
            raise RuntimeError('运行文件缺失：' + name)
    score = dict(version=1, hand='right', title='运行包自检', duration_ms=1000,
                 notes=[dict(t_ms=0, duration_ms=1000, finger=1, pitch=60, velocity=96, amplitude_pct=100)])
    if decode(encode(score))['notes'][0]['pitch'] != 60:
        raise RuntimeError('PGL 往返校验失败')
    with tempfile.TemporaryDirectory(prefix='piano-runtime-check-') as temporary:
        pdf = Path(temporary) / 'runtime-check.pdf'
        doc = PdfWriter()
        page = doc.add_blank_page(width=400, height=200)
        stream = DecodedStreamObject()
        stream.set_data(b'0.5 w\n' + b'\n'.join(('20 %d m 380 %d l S' % (y, y)).encode('ascii')
                                            for y in (70, 78, 86, 94, 102)))
        page[NameObject('/Contents')] = stream
        with pdf.open('wb') as handle:
            doc.write(handle)
        result = bridge.SoftwareConsole(None).convert(dict(filename=pdf.name, bpm=120,
                   base64=base64.b64encode(pdf.read_bytes()).decode('ascii')))
        preview = result['project']['page_previews'][0]
        if not preview['data'].startswith('data:image/png;base64,'):
            raise RuntimeError('PDF 页面渲染失败')
        data = base64.b64decode(preview['data'].split(',', 1)[1])
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('PDF 页面不是 PNG')
    output = dict(ok=True, build_date=BUILD_DATE, python=sys.version.split()[0],
                  serial_version=serial.__version__, pdfium_version=importlib.metadata.version('pypdfium2'),
                  pypdf_version=importlib.metadata.version('pypdf'),
                  assets=len(required), pgl_roundtrip=True, pdf_pipeline=True,
                  pdf_preview_png=True, serial_opened=False)
    print(json.dumps(output, ensure_ascii=False))
    return output


def serve(args):
    import bridge
    # The staged frozen bridge redirects recording writes here. The source
    # bridge keeps its usual recording path; no source bridge patch is needed.
    bridge.HOST_DIR = str(resources())
    bridge.RUNTIME_DATA_DIR = str(data_directory())
    page = 'web_piano_glove.html?simple=1' if args.debug else 'software.html'
    if open_existing(args.port, args.url, page, not args.no_open):
        return
    session = bridge.Bridge(url=args.url, baud=args.baud, auto=not args.no_auto)
    server = None
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), bridge.make_handler(session))
        server.daemon_threads = True
        threading.Thread(target=session._autoloop, name='pg-auto', daemon=True).start()
        url = 'http://127.0.0.1:%d/%s' % (args.port, page)
        print('钢琴手套 · 软件测试版 ' + BUILD_DATE)
        print('页面：' + url)
        print('记录：' + str(data_directory()))
        print('请保留此窗口。退出前在网页点“停止”；Ctrl+C 关闭本程序。')
        if not args.no_open:
            threading.Timer(.8, lambda: webbrowser.open(url)).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if session.connected:
            try:
                # Closing an idle USB program must leave independent phone
                # playback running. Firmware performs an atomic USB release;
                # the adapter handles older firmware conservatively.
                bridge.SoftwareConsole(session).release_usb()
            except Exception:
                pass
        session.close()
        if server:
            server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='钢琴手套 Windows 软件训练测试版')
    parser.add_argument('--port', type=int, default=8123, help='本地网页端口，默认8123')
    parser.add_argument('--url', help='指定串口，例如COM3；省略时自动发现，也可在校准页选择')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--no-auto', action='store_true', help='不自动连接串口')
    parser.add_argument('--no-open', action='store_true', help='启动后不自动打开浏览器')
    parser.add_argument('--debug', action='store_true', help='先打开调试和校准页')
    parser.add_argument('--self-test', action='store_true', help='只检查运行文件和PDF模块，不打开串口')
    parser.add_argument('--list-ports', action='store_true', help='只列出USB串口，不打开串口')
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('网页端口须为1024至65535')
    if args.url and not re.fullmatch(r'COM[1-9][0-9]*', args.url, flags=re.I):
        parser.error('请指定COM串口，例如COM3')
    if args.url:
        args.url = args.url.upper()
    if args.self_test:
        return self_test()
    if args.list_ports:
        from serial.tools import list_ports
        print(json.dumps([dict(port=p.device, description=p.description, vid=p.vid, pid=p.pid)
                          for p in list_ports.comports()], ensure_ascii=False, indent=2))
        return
    return serve(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('启动失败：' + str(error), file=sys.stderr)
        sys.exit(1)
