"""后台记录调手套页的串口日志（用户测插拔舵机编号/校准时用）。只读页面文字，不发任何指令。
    python tools/dev/record_glove_log.py <输出.txt> [调试口=9350]
每 1 秒读一次所有页面里的日志框，新出现的行带时间写进文件；建同名 .stop 文件结束。"""
import json, sys, time, urllib.request, datetime, pathlib
import websocket

out = pathlib.Path(sys.argv[1]); port = int(sys.argv[2]) if len(sys.argv) > 2 else 9350
out.parent.mkdir(parents=True, exist_ok=True)
stop = out.with_suffix('.stop')
JS = r"""(()=>{const pick=[...document.querySelectorAll('#log,#demoLog,.p-log')].map(e=>(e.value||e.innerText||'')).join('\n');
const st=[document.title,document.getElementById('connection')?.textContent||'',document.getElementById('demoNotice')?.textContent||'',document.getElementById('demoVersion')?.textContent||'',document.getElementById('demoEnrollStatus')?.textContent||'',document.getElementById('demoCalibrationProgress')?.textContent||''].join(' | ');
return {log:pick,st}})()"""
seen = {}; last_state = {}


def now():
    return datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]


with out.open('a', encoding='utf-8') as f:
    f.write(f'==== 开始记录 {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ====\n'); f.flush()
    while not stop.exists():
        try:
            pages = [p for p in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=3)) if p.get('type') == 'page']
        except Exception:
            time.sleep(2); continue
        for p in pages:
            try:
                ws = websocket.create_connection(p['webSocketDebuggerUrl'], timeout=5)
                ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': JS, 'returnByValue': True}}))
                while True:
                    r = json.loads(ws.recv())
                    if r.get('id') == 1:
                        break
                ws.close()
                v = r['result']['result'].get('value') or {}
            except Exception:
                continue
            key = p['url'].split('/')[-1].split('#')[0]
            if v.get('st') and last_state.get(key) != v['st']:
                last_state[key] = v['st']; f.write(f'{now()} [{key}] 状态: {v["st"]}\n')
            lines = [l for l in (v.get('log') or '').splitlines() if l.strip()]
            old = seen.get(key, [])
            if old and old[-1] in lines:
                idx = len(lines) - 1 - lines[::-1].index(old[-1]); new = lines[idx + 1:]
            else:
                new = lines if not old else lines[-50:]
            for l in new:
                f.write(f'{now()} [{key}] {l}\n')
            seen[key] = lines[-200:]
        f.flush(); time.sleep(1)
    f.write(f'==== 结束 {datetime.datetime.now():%H:%M:%S} ====\n')
