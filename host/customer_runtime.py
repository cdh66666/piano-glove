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

BUILD_DATE = '20261030'
# Both pages share the USB connection. Compare their actual assets before reusing
# an existing process, including PDF review changes outside software.js.
WEB_ASSETS = (
    'software.html', 'software.js', 'software.css', 'software-audio.js',
    'software-pack.js', 'software-review.js', 'software-review.css',
    'software-tempo.js', 'software-tempo.css', 'software-upload.js',
    'software-upload.css', 'web_piano_glove.html', 'delivery-shell.js',
    'delivery-shell.css', 'delivery-speed-chart.js', 'delivery-speed-chart.css',
    'delivery-demo.js', 'delivery-mount.js', 'delivery-mount.css',
    'delivery-validation.js', 'delivery-validation.css', 'usb-driver.js',
    'usb-driver.css',
    'guide.html', 'native-transport.js', 'desktop-ui.css', 'desktop-shell.js',
    'desktop-debug.css', 'desktop-debug.js', 'native-catalog.js', 'desktop-catalog.css',
    'comic-ui.css', 'comic-art.js', 'comic-shell.js', 'comic-guide.js', 'comic-pages.css', 'proof-coach.js', 'score-list.js', 'reading-lesson.js',
)
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
    root = resources()
    opener = build_opener(ProxyHandler({}))
    try:
        for name in WEB_ASSETS:
            with opener.open('http://127.0.0.1:%d/%s' % (port, name), timeout=2) as reply:
                served = reply.read()
            expected = (root / name).read_bytes()
            if served.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n'):
                raise RuntimeError('另一版本软件正在运行（%s 不同），请先退出旧版本，再启动本包。' % name)
    except (URLError, OSError) as error:
        raise RuntimeError('无法核对已运行的软件版本，请先退出旧版本，再启动本包。') from error
    if launch_browser:
        webbrowser.open('http://127.0.0.1:%d/%s' % (port, page))
    print('已使用正在运行的同版调试台。')
    return True


def catalog_source_counts(entries):
    """Keep document formats and human-authored scores separate in reports."""
    return dict(bundled_original_documents=len(entries),
                bundled_original_pdfs=sum(Path(entry.get('file') or '').suffix.lower() == '.pdf' for entry in entries),
                bundled_manual_scores=sum(entry.get('source_kind') == 'manual' for entry in entries))


def self_test():
    """Checks the frozen native dependencies and real PDF pipeline, without COM access."""
    import serial
    import pypdfium2
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    import bridge
    from usb_driver import get_driver_status
    from score_codec import encode, decode
    asset_root = resources()
    required = WEB_ASSETS
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
    driver = get_driver_status(list(serial.tools.list_ports.comports()), refresh=True)
    from score_catalog import ScoreCatalog
    catalog = ScoreCatalog(asset_root / 'assets' / 'score-library')
    bundled = catalog.list()
    for entry in bundled:
        catalog.read(entry['id'])
        if entry.get('source_kind') == 'manual':
            catalog.project(entry['id'])
    output = dict(ok=True, build_date=BUILD_DATE, python=sys.version.split()[0],
                  serial_version=serial.__version__, pdfium_version=importlib.metadata.version('pypdfium2'),
                  pypdf_version=importlib.metadata.version('pypdf'),
                  assets=len(required), pgl_roundtrip=True, pdf_pipeline=True,
                  pdf_preview_png=True, driver_helper=True, driver_diagnostics=driver['state'], serial_opened=False,
                  **catalog_source_counts(bundled), manual_pdf_holdouts=len(catalog.manifest['holdout_ids']))
    print(json.dumps(output, ensure_ascii=False))
    return output


def serve(args, on_ready=None):
    import bridge
    # The staged frozen bridge redirects recording writes here. The source
    # bridge keeps its usual recording path; no source bridge patch is needed.
    bridge.HOST_DIR = str(resources())
    bridge.RUNTIME_DATA_DIR = str(data_directory())
    page = 'web_piano_glove.html?simple=1' if args.debug else 'software.html'
    url = 'http://127.0.0.1:%d/%s' % (args.port, page)
    if open_existing(args.port, args.url, page, not args.no_open):
        if on_ready:
            on_ready(None, None, url)
        return
    session = bridge.Bridge(url=args.url, baud=args.baud, auto=not args.no_auto)
    server = None
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), bridge.make_handler(session))
        server.daemon_threads = True
        threading.Thread(target=session._autoloop, name='pg-auto', daemon=True).start()
        print('钢琴手套 · 软件测试版 ' + BUILD_DATE)
        print('页面：' + url)
        print('记录：' + str(data_directory()))
        print('关闭启动窗口退出本程序；独立手机播放不受本程序退出影响。')
        if on_ready:
            on_ready(server, session, url)
        if not args.no_open:
            threading.Timer(.8, lambda: webbrowser.open(url)).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Stop discovery before releasing USB, so the auto loop cannot reopen
        # the port after cleanup. This does not stop a run owned by the phone.
        session._stop = True
        session.paused = True
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


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description='钢琴手套 Windows 电脑软件')
    parser.add_argument('--port', type=int, default=8123, help='本地网页端口，默认8123')
    parser.add_argument('--url', help='指定串口，例如COM3；省略时自动发现，也可在校准页选择')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--no-auto', action='store_true', help='不自动连接串口')
    parser.add_argument('--no-open', action='store_true', help='启动后不自动打开浏览器')
    parser.add_argument('--debug', action='store_true', help='先打开调试和校准页')
    parser.add_argument('--self-test', action='store_true', help='只检查运行文件和PDF模块，不打开串口')
    parser.add_argument('--list-ports', action='store_true', help='只列出USB串口，不打开串口')
    parser.add_argument('--report', help='将自检或串口清单写入指定的绝对JSON文件路径')
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('网页端口须为1024至65535')
    if args.url and not re.fullmatch(r'COM[1-9][0-9]*', args.url, flags=re.I):
        parser.error('请指定COM串口，例如COM3')
    if args.url:
        args.url = args.url.upper()
    if args.report and (not (args.self_test or args.list_ports) or not Path(args.report).is_absolute()):
        parser.error('--report 须与 --self-test 或 --list-ports 一起使用，并指定绝对路径')
    return args


def write_report(path, output):
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(args):
    try:
        if args.self_test:
            output = self_test()
        elif args.list_ports:
            from serial.tools import list_ports
            output = [dict(port=p.device, description=p.description, vid=p.vid, pid=p.pid)
                      for p in list_ports.comports()]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            return serve(args)
    except Exception as error:
        write_report(args.report, dict(ok=False, build_date=BUILD_DATE, error=str(error)))
        raise
    write_report(args.report, output)
    return output


def main(argv=None):
    return run(parse_arguments(argv))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('启动失败：' + str(error), file=sys.stderr)
        sys.exit(1)
