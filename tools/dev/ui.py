"""像真人一样操作程序：截图看页面 → 在某个位置点一下 / 打字 / 按键 → 再截图。
不动电脑真鼠标（用 WebView2 调试口发鼠标事件），截图也是后台截，不抢屏幕。

    python tools/dev/ui.py shot  <保存路径.png>        截当前页面（1266 宽左右，坐标就是图上的像素）
    python tools/dev/ui.py click <x> <y>               在图上这个位置点一下
    python tools/dev/ui.py type  <文字>                往当前输入框打字
    python tools/dev/ui.py key   Escape|Enter|Tab      按一个键
    python tools/dev/ui.py scroll <x> <y> <dy>         在这个位置滚动
    python tools/dev/ui.py caption <文字>              改录像底部字幕（录像要先 record 起来）
    python tools/dev/ui.py record <out.mp4> [camera]   后台录像：左程序、右摄像头，直到 caption STOP
    python tools/dev/ui.py state                       读手套状态（在不在动、有没有报错）
"""
import base64, json, sys, time, urllib.request
from pathlib import Path
import websocket

PORT = 9350
CAPTION = Path(__file__).resolve().parent / '.ui_caption.txt'


def cdp():
    pages = [p for p in json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=3)) if p.get('type') == 'page']
    pages.sort(key=lambda p: not any(k in p.get('url', '') for k in ('software', 'debug')))
    ws = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=60)
    n = [0]

    def call(method, params=None):
        n[0] += 1; ws.send(json.dumps({'id': n[0], 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get('id') == n[0]: return r
    return call


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == 'caption':
        CAPTION.write_text(' '.join(args), encoding='utf-8'); return
    if cmd == 'record':
        sys.path.insert(0, str(Path(__file__).parent))
        from full_hw_test import Recorder
        CAPTION.write_text('开始录制', encoding='utf-8')
        rec = Recorder(PORT, int(args[1]) if len(args) > 1 else 1, args[0])
        while True:
            text = CAPTION.read_text(encoding='utf-8').strip() if CAPTION.exists() else ''
            if text == 'STOP': break
            rec.caption = text; time.sleep(0.2)
        rec.stop(); return
    call = cdp()
    if cmd == 'shot':
        r = call('Page.captureScreenshot', {'format': 'png'})
        Path(args[0]).write_bytes(base64.b64decode(r['result']['data'])); print('saved', args[0])
    elif cmd == 'click':
        x, y = float(args[0]), float(args[1])
        call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})
        for t in ('mousePressed', 'mouseReleased'):
            call('Input.dispatchMouseEvent', {'type': t, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        print('clicked', x, y)
    elif cmd == 'type':
        call('Input.insertText', {'text': ' '.join(args)}); print('typed')
    elif cmd == 'key':
        k = args[0]; code = {'Escape': 27, 'Enter': 13, 'Tab': 9}.get(k, 0)
        for t in ('keyDown', 'keyUp'):
            call('Input.dispatchKeyEvent', {'type': t, 'key': k, 'code': k, 'windowsVirtualKeyCode': code})
        print('key', k)
    elif cmd == 'scroll':
        call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': float(args[0]), 'y': float(args[1]), 'deltaX': 0, 'deltaY': float(args[2])}); print('scrolled')
    elif cmd == 'state':
        r = call('Runtime.evaluate', {'expression': "(async()=>{try{const s=await (await fetch('/api/state')).json();return JSON.stringify({active:s.active,mode:s.mode,mask:s.mask,error:s.error,stop:s.last_stop_reason,cal:(s.feedback||[]).map(f=>f.calibration_valid?1:0).join('')})}catch(e){return 'ERR '+e.message}})()", 'awaitPromise': True, 'returnByValue': True})
        print(r.get('result', {}).get('result', {}).get('value'))


if __name__ == '__main__':
    main()
