"""虚拟手机：在电脑上直接测“手机连手套热点”那一套，不碰电脑的 Wi-Fi。

一键启动三样：手套（默认用模拟手套；接了真手套就加 --device COM9）→ USB 桥 → 手机页服务，
然后弹出一个手机大小的窗口（390×844、触屏、安卓），打开的就是手套固件里内置的那份手机页。
可以加无线延迟和卡顿，模拟热点信号不好。关掉手机窗口，三样一起退出。

    python tools/phone_sim/virtual_phone.py                 # 模拟手套
    python tools/phone_sim/virtual_phone.py --device COM9   # 真手套（会真的动）
    python tools/phone_sim/virtual_phone.py --stall-every 8 --stall 1.6   # 每 8 秒卡 1.6 秒

测不到的：手套无线芯片本身（信号强弱、掉线重连）。那部分只能用真手机或 USB 无线网卡。
"""
import argparse, subprocess, sys, threading, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36')


def wait(url, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read(1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--device', help='真手套串口（如 COM9）；不写就用模拟手套')
    p.add_argument('--port', type=int, default=8196, help='手机页端口')
    p.add_argument('--bridge', type=int, default=8197, help='USB 桥端口')
    p.add_argument('--sim-port', type=int, default=9732)
    p.add_argument('--latency', default='20,80')
    p.add_argument('--stall-every', default='0')
    p.add_argument('--stall', default='0')
    p.add_argument('--cpu', type=float, default=4, help='手机 CPU 比电脑慢几倍')
    p.add_argument('--no-window', action='store_true', help='只起服务，不弹手机窗口（自动测试用）')
    a = p.parse_args()
    py = sys.executable
    procs = []
    if a.device:
        url = a.device
    else:
        sys.path.insert(0, str(ROOT / 'tools' / 'dev'))
        import sim_glove
        ready = threading.Event()
        threading.Thread(target=sim_glove.serve, args=(a.sim_port, ready), daemon=True).start()
        ready.wait(10)
        url = 'socket://127.0.0.1:%d' % a.sim_port
    procs.append(subprocess.Popen([py, '-X', 'utf8', str(ROOT / 'host' / 'bridge.py'), '--port', str(a.bridge), '--url', url]))
    procs.append(subprocess.Popen([py, '-X', 'utf8', str(ROOT / 'tools' / 'phone_sim' / 'phone_sim_server.py'),
                                   '--port', str(a.port), '--bridge', str(a.bridge), '--latency', a.latency,
                                   '--stall-every', a.stall_every, '--stall', a.stall]))
    phone = 'http://127.0.0.1:%d/' % a.port
    try:
        if not (wait('http://127.0.0.1:%d/api/status' % a.bridge) and wait(phone)):
            print('启动失败：USB 桥或手机页没起来'); return 1
        print('虚拟手机已就绪：', phone, '（手套：' + (a.device or '模拟') + '）', flush=True)
        if a.no_window:
            while True: time.sleep(1)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=False,
                                         args=['--window-size=420,920', '--autoplay-policy=no-user-gesture-required'])
            ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                      is_mobile=True, has_touch=True, user_agent=UA, locale='zh-CN')
            page = ctx.new_page()
            ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': a.cpu})
            page.goto(phone)
            page.wait_for_event('close', timeout=0)
            browser.close()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            proc.terminate()
    return 0


if __name__ == '__main__':
    sys.exit(main())
