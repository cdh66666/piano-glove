"""用“模拟手机”浏览器打开手机页，播放一首曲谱，记录会不会“连接中断”。

先启动 host/bridge.py（接 COM9）和 phone_sim_server.py，再运行：
  python tools/phone_sim/run_phone_sim.py --slot 3 --seconds 40 --cpu 6 --out out_dir [--headed]
手机尺寸 390x844、触屏、安卓 UA，CPU 降速 --cpu 倍（模拟中低端手机）。
"""
import argparse, json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://127.0.0.1:8196/')
    p.add_argument('--slot', type=int, default=3)
    p.add_argument('--tempo', type=int, default=100)
    p.add_argument('--seconds', type=float, default=40)
    p.add_argument('--cpu', type=float, default=6)
    p.add_argument('--out', required=True)
    p.add_argument('--headed', action='store_true')
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=not a.headed,
                                     args=['--window-size=430,940', '--autoplay-policy=no-user-gesture-required'])
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3,
                                  is_mobile=True, has_touch=True, user_agent=UA, locale='zh-CN')
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': a.cpu})
        page.goto(a.url)
        page.wait_for_function("document.getElementById('connection').textContent.includes('已就绪')", timeout=30000)
        page.evaluate("v=>{const t=document.getElementById('tempo');t.value=v;t.dispatchEvent(new Event('input'))}", str(a.tempo))
        page.tap('nav [data-tab="library"]')
        page.wait_for_selector('#songs .song')
        row = page.locator('#songs .song').filter(has_text=f'{a.slot}. ').first
        row.locator('button', has_text='开始训练').tap()
        t0 = time.time(); shot = 0
        while time.time() - t0 < a.seconds:
            r = page.evaluate("""()=>({activity:document.getElementById('activity').textContent,
                note:document.getElementById('player-note').textContent,
                time:document.getElementById('player-time').textContent,
                sync:document.getElementById('sync').textContent,
                msg:document.getElementById('message').textContent,
                conn:document.getElementById('connection').textContent})""")
            r['t'] = round(time.time() - t0, 2); rows.append(r)
            if time.time() - t0 > shot * 10:
                page.screenshot(path=str(out / f'shot_{shot:02d}.png')); shot += 1
            if '中断' in r['activity'] or '中断' in r['msg'] or ('已完成' in r['activity'] and r['t'] > 3):
                page.screenshot(path=str(out / 'end.png'))
                if '中断' in r['activity'] or '中断' in r['msg']:
                    break
            time.sleep(0.25)
        page.screenshot(path=str(out / 'last.png'))
        try:  # 测完马上停手套，别让它接着弹
            page.tap('#stop'); time.sleep(0.8)
        except Exception:
            pass
        try:
            log = json.loads(page.evaluate("fetch('/sim/log').then(r=>r.text())"))
        except Exception:
            log = []
        browser.close()
    lost = [r for r in rows if '中断' in r['activity'] or '中断' in r['msg'] or '中断' in r['conn']]
    summary = dict(slot=a.slot, cpu=a.cpu, seconds=rows[-1]['t'] if rows else 0, lost_at=lost[0]['t'] if lost else None,
                   last=rows[-1] if rows else None, stops=[x for x in log if x.get('path') == '/api/stop'],
                   slow_requests=[x for x in log if x.get('ms', 0) > 900][:20],
                   state_requests=sum(1 for x in log if x.get('path') == '/api/state'))
    (out / 'rows.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
