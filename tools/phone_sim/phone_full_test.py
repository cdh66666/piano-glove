"""虚拟手机全流程测试：起虚拟手机（模拟手套或真手套），在手机尺寸的浏览器里把手机页能点的都点一遍，
每一步截图，最后写 summary.json。两轮：信号正常；信号差（每 6 秒卡 1.6 秒）。

    python tools/phone_sim/phone_full_test.py --out D:/cc_work/测试视频_20261109/虚拟手机 [--device COM9]
"""
import argparse, json, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36')


def up(url, seconds=25):
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read(1); return True
        except Exception:
            time.sleep(0.3)
    return False


def run_round(name, out, device, stall_every, stall, port, results):
    cmd = [sys.executable, '-X', 'utf8', str(ROOT / 'tools/phone_sim/virtual_phone.py'), '--no-window',
           '--port', str(port), '--bridge', str(port + 1), '--sim-port', str(port + 500),
           '--stall-every', str(stall_every), '--stall', str(stall)]
    if device:
        cmd += ['--device', device]
    server = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shots, steps, errors = [], [], []
    try:
        assert up(f'http://127.0.0.1:{port}/'), '虚拟手机没起来'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True, args=['--autoplay-policy=no-user-gesture-required'])
            ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                      is_mobile=True, has_touch=True, user_agent=UA, locale='zh-CN')
            page = ctx.new_page()
            ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': 4})
            page.on('pageerror', lambda e: errors.append(str(e)))
            n = [0]

            def shot(label):
                n[0] += 1
                path = out / f'{name}_{n[0]:02d}_{label}.png'
                page.screenshot(path=str(path), full_page=False)
                shots.append(path.name)

            def step(label, ok, detail=''):
                steps.append(dict(step=label, ok=bool(ok), detail=str(detail)[:200]))

            def lost():
                text = page.locator('#connection').inner_text()
                return ('中断' in text or '断开' in text), text

            page.goto(f'http://127.0.0.1:{port}/')
            try:
                page.wait_for_function("document.getElementById('connection').textContent.includes('已就绪')", timeout=30000)
                step('打开手机页，连上手套', True, page.locator('#connection').inner_text())
            except Exception as e:
                step('打开手机页，连上手套', False, e)
            shot('打开')
            # 手指训练：五根手指逐个按下、抬起
            page.tap('nav [data-tab="train"]'); page.wait_for_timeout(500)
            cards = page.locator('#fingers .finger-card')
            for i in range(cards.count()):
                cards.nth(i).tap(); page.wait_for_timeout(700)
                if i == 2: shot('按下中指')
                cards.nth(i).tap(); page.wait_for_timeout(500)
            step('五指逐个按下抬起', not lost()[0], lost()[1])
            # 三种连续练习，各跑 3 秒再停
            for label in ('逐指', '组合', '交替'):
                btn = page.locator('#train .actions button', has_text=label).first
                if btn.count() and btn.is_enabled():
                    btn.tap(); page.wait_for_timeout(3000); shot(label)
                    page.tap('#stop'); page.wait_for_timeout(800)
                    step(label + ' 3 秒后停止', not lost()[0], page.locator('#training-status').inner_text() if page.locator('#training-status').count() else '')
                else:
                    step(label, False, '按钮不可用')
            # 速度/幅度滑条、最快速度
            for sel, value in (('#tempo', '150'), ('#amplitude', '70')):
                if page.locator(sel).count():
                    page.evaluate("([s,v])=>{const e=document.querySelector(s);e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}", [sel, value])
            if page.locator('#fastest-training').count():
                page.tap('#fastest-training'); page.wait_for_timeout(500)
            shot('调速度幅度')
            step('滑条和最快速度', not lost()[0])
            if page.locator('#tempo').count():
                page.evaluate("()=>{const e=document.querySelector('#tempo');e.value='100';e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
            # 曲库：列表、播一首到底（最长 25 秒）、重新开始、返回
            page.tap('nav [data-tab="library"]')
            try:
                page.wait_for_selector('#songs .song', timeout=15000)
                step('曲库列出曲谱', True, f'{page.locator("#songs .song").count()} 首')
            except Exception as e:
                step('曲库列出曲谱', False, e)
            shot('曲库')
            song = page.locator('#songs .song').first
            play = song.locator('button', has_text='开始训练').first
            if play.count():
                play.tap()
                t0 = time.time(); worst = None; midshot = False
                while time.time() - t0 < 25:
                    page.wait_for_timeout(500)
                    bad, text = lost()
                    if bad and worst is None: worst = f'{time.time()-t0:.1f}s {text}'
                    if not midshot and time.time() - t0 > 2:
                        shot('播放中'); midshot = True
                    if '待机' in page.locator('body').inner_text()[-200:] and time.time() - t0 > 4: break
                step('曲库播放一首（全程不断联）', worst is None, worst or f'{time.time()-t0:.1f}s')
                for bid, label in (('#player-replay', '重新开始'), ('#stop', '停止'), ('#player-back', '返回曲库')):
                    if page.locator(bid).count() and page.locator(bid).is_visible():
                        page.tap(bid); page.wait_for_timeout(1500)
                        step(label, not lost()[0])
                shot('返回曲库')
            # PDF 识谱页
            # 全按钮扫：每页可见可点的按钮都点一下，页面不能报错、不能断联
            clicked = 0
            for tab in ('train', 'library'):
                page.tap(f'nav [data-tab="{tab}"]'); page.wait_for_timeout(400)
                for i in range(page.locator('main button:visible').count()):
                    b = page.locator('main button:visible').nth(i)
                    try:
                        txt = b.inner_text(timeout=500).strip()
                        if not b.is_enabled() or txt in ('删除',) or '上传' in txt: continue
                        b.tap(timeout=1500); clicked += 1; page.wait_for_timeout(250)
                        if page.locator('#stop').is_visible(): page.tap('#stop')
                    except Exception:
                        pass
            page.wait_for_timeout(1500)
            step('全按钮扫一遍（跳过删除/上传）', not errors and not lost()[0], f'点了 {clicked} 个')
            shot('全按钮之后')
            browser.close()
    finally:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(server.pid)], capture_output=True)  # 连同桥和手机页服务一起关
    results[name] = dict(stall_every=stall_every, stall=stall, steps=steps, page_errors=errors, shots=shots,
                         passed=sum(s['ok'] for s in steps), total=len(steps))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--device')
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    results = {}
    run_round('信号正常', out, a.device, 0, 0, 8296, results)
    run_round('信号差', out, a.device, 6, 1.6, 8396, results)
    (out / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    for name, r in results.items():
        print(name, f"{r['passed']}/{r['total']}", '页面报错', len(r['page_errors']))
        for s in r['steps']:
            print('  ', '过' if s['ok'] else '✗', s['step'], s['detail'])


if __name__ == '__main__':
    main()
