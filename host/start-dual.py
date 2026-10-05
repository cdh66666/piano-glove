"""Two isolated local consoles; enumerate USB only, never assign servo IDs."""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from serial.tools import list_ports


def choose_ports(explicit, available):
    ports = explicit or sorted([p.device for p in available if p.vid == 0x10C4 and p.pid == 0xEA60], key=lambda p: int(p[3:]))
    if len(ports) != 2 or len(set(ports)) != 2 or any(not re.fullmatch(r'COM[1-9][0-9]*', p) for p in ports):
        raise ValueError('需要两个不同的 COM 口。例如：start-dual.bat COM3 COM27')
    return ports


def status(port):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/status' % port, timeout=1) as reply:
            return json.load(reply)
    except urllib.error.URLError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ports', nargs='*')
    args = parser.parse_args()
    ports = choose_ports(args.ports, list_ports.comports())
    root = pathlib.Path(__file__).resolve().parent
    # Validate both existing services before starting either one; never stop another service.
    states = [status(p) for p in (8123, 8124)]
    for http_port, serial_port, current in zip((8123, 8124), ports, states):
        if current is not None and current.get('fixed') != serial_port:
            raise RuntimeError('%d 已有其他调试台，请先关闭该调试台窗口后重试。' % http_port)
    for http_port, serial_port, current in zip((8123, 8124), ports, states):
        if current is None:
            subprocess.Popen([sys.executable, '-u', str(root/'bridge.py'), '--url', serial_port, '--port', str(http_port)], cwd=root,
                             creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        for _ in range(40):
            current = status(http_port)
            if current is not None:
                break
            time.sleep(.25)
        if not current or current.get('fixed') != serial_port:
            raise RuntimeError('%d 调试台启动失败；请查看对应窗口。' % http_port)
        webbrowser.open('http://127.0.0.1:%d/web_piano_glove.html?simple=1' % http_port)
        print('%s -> http://127.0.0.1:%d' % (serial_port, http_port))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
