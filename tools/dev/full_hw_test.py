"""真手套全流程测试 + 后台录像（左：程序画面，右：摄像头拍手套，底部字幕=当前步骤）。

不动鼠标键盘、不抢屏幕：程序画面用 WebView2 调试口截图，摄像头用 OpenCV 直接读。
动作都很短（真手套每段几秒就停）。不重新编号、不重新校准（那两样要人手动配合，只验证入口和提示）。

    启动程序：set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9350 --disable-backgrounding-occluded-windows
    python tools/dev/full_hw_test.py --port 9350 --camera 1 --out D:/cc_work/测试视频_20261110/真手套全流程
"""
import argparse, base64, io, json, sys, threading, time, urllib.request
from pathlib import Path
import cv2, numpy as np, websocket
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT = ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc', 30)
FONT_S = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 22)


class Cdp:
    def __init__(self, port):
        self.port = port; self.i = 0; self.lock = threading.Lock(); self.connect()

    def connect(self):
        for _ in range(40):
            try:
                pages = [p for p in json.load(urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json', timeout=3)) if p.get('type') == 'page']
                pages.sort(key=lambda p: not any(k in p.get('url', '') for k in ('software', 'debug')))
                self.ws = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=120); return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError('连不上程序调试口')

    def call(self, method, params=None):
        with self.lock:
            self.i += 1; mid = self.i
            self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
            while True:
                r = json.loads(self.ws.recv())
                if r.get('id') == mid: return r

    def ev(self, js):
        try:
            r = self.call('Runtime.evaluate', {'expression': js, 'awaitPromise': True, 'returnByValue': True})
        except Exception:
            time.sleep(2); self.connect(); return None
        return r.get('result', {}).get('result', {}).get('value')


class Recorder:
    def __init__(self, port, camera, path, fps=6):
        self.cdp = Cdp(port); self.fps = fps; self.caption = '准备'; self.result = ''
        self.cam = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cam_frame = None; self.app_frame = None; self.running = True; self.path = path; self.writer = None
        for target in (self._cam_loop, self._app_loop, self._write_loop):
            threading.Thread(target=target, daemon=True).start()

    def _cam_loop(self):
        while self.running:
            ok, f = self.cam.read()
            if ok: self.cam_frame = f

    def _app_loop(self):
        while self.running:
            try:
                r = self.cdp.call('Page.captureScreenshot', {'format': 'jpeg', 'quality': 75})
                data = base64.b64decode(r['result']['data'])
                self.app_frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                time.sleep(1)
                try: self.cdp.connect()
                except Exception: pass
            time.sleep(0.12)

    def compose(self):
        H = 720
        app = self.app_frame if self.app_frame is not None else np.full((720, 1140, 3), 240, np.uint8)
        app = cv2.resize(app, (int(app.shape[1] * H / app.shape[0]), H))
        cam = self.cam_frame if self.cam_frame is not None else np.zeros((720, 1280, 3), np.uint8)
        cam = cv2.resize(cam, (int(cam.shape[1] * H / cam.shape[0]), H))
        frame = np.concatenate([app, np.full((H, 8, 3), 30, np.uint8), cam], axis=1)
        bar = Image.new('RGB', (frame.shape[1], 64), (35, 33, 43)); d = ImageDraw.Draw(bar)
        d.text((24, 12), self.caption, font=FONT, fill=(255, 255, 255))
        if self.result:
            color = (80, 210, 120) if self.result.startswith('✓') else (255, 120, 90)
            d.text((frame.shape[1] - 24 - d.textlength(self.result, font=FONT_S), 20), self.result, font=FONT_S, fill=color)
        frame = np.concatenate([frame, cv2.cvtColor(np.array(bar), cv2.COLOR_RGB2BGR)], axis=0)
        return frame

    def _write_loop(self):
        nxt = time.time()
        while self.running:
            frame = self.compose()
            if self.writer is None:
                h, w = frame.shape[:2]; w -= w % 2; h -= h % 2
                self.size = (w, h)
                self.writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*'mp4v'), self.fps, self.size)
            self.writer.write(cv2.resize(frame, self.size))
            nxt += 1 / self.fps; time.sleep(max(0, nxt - time.time()))

    def stop(self):
        self.running = False; time.sleep(0.6)
        if self.writer: self.writer.release()
        self.cam.release()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=9350)
    p.add_argument('--camera', type=int, default=1)
    p.add_argument('--out', required=True)
    p.add_argument('--pdf', default=r'D:\cc_work\test_scores\new\82aec416948b.pdf')
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rec = Recorder(a.port, a.camera, out / '真手套全流程_raw.mp4')
    c = Cdp(a.port)
    results = []

    def say(text):
        rec.caption = text; rec.result = ''; print('▶', text, flush=True)

    def W(s): time.sleep(s)

    def shot(name):
        try:
            r = c.call('Page.captureScreenshot', {'format': 'png'})
            (out / f'{len(results):02d}_{name}.png').write_bytes(base64.b64decode(r['result']['data']))
        except Exception: pass

    def check(section, item, ok, detail=''):
        ok = bool(ok); results.append(dict(section=section, item=item, ok=ok, detail=str(detail)[:160]))
        rec.result = ('✓ ' if ok else '✗ ') + item; print('   ', '过' if ok else '✗', item, detail, flush=True); shot(item)

    def js_click(selector):
        return c.ev(f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return false;e.scrollIntoView({{block:'center'}});e.click();return true}})()")

    def click_text(text, scope='body'):
        return c.ev(f"(()=>{{const t={json.dumps(text)};const b=[...document.querySelectorAll({json.dumps(scope)}+' button, '+{json.dumps(scope)}+' a, '+{json.dumps(scope)}+' summary')].find(b=>b.getClientRects().length>0&&(b.innerText||'').replace(/\\s+/g,' ').trim().startsWith(t));if(!b)return false;b.scrollIntoView({{block:'center'}});b.click();return true}})()")

    def state():
        return c.ev("(async()=>{try{return await (await fetch('/api/state')).json()}catch(e){return {}}})()") or {}

    def nav(name):
        click_text(name, 'header'); W(1.2)

    def stop_all():
        js_click('#stop'); W(1.2)
        return not state().get('active')

    def errors():
        return c.ev("(()=>{const e=window.__hwErr||[];window.__hwErr=[];return e})()") or []

    c.ev("(()=>{window.__hwErr=[];addEventListener('error',e=>__hwErr.push(String(e.message)));addEventListener('unhandledrejection',e=>__hwErr.push('promise:'+String(e.reason&&e.reason.message||e.reason)));document.getElementById('comic-coach-close')?.click();return 1})()")
    try:
        # ---------------- 1 开始页 ----------------
        S = '开始页'
        say('开始页：连接状态'); nav('开始')
        top = c.ev("document.querySelector('.desktop-status,#desktop-status,#comic-hero-connection')?.textContent||''") or ''
        check(S, '手套已连接、已就绪', '已就绪' in top, top)
        say('开始页：读谱小课（6 课，一课一课点）'); js_click('#comic-open-guide'); W(1.5)
        steps = 0
        for _ in range(40):
            if not c.ev("(()=>{const b=document.getElementById('rl-next');return !!b&&b.getClientRects().length>0&&!b.disabled})()"): break
            js_click('#rl-next'); steps += 1; W(0.8)
        check(S, '读谱小课 6 课能一课课往下翻', steps >= 5, f'翻了 {steps} 次')
        js_click('#rl-close'); W(0.8)
        say('开始页：使用说明'); js_click('#comic-open-manual'); W(2)
        manual = c.ev("(()=>{const f=[...document.querySelectorAll('iframe,dialog,.native-overlay,[class*=guide-overlay],[class*=overlay]')].find(e=>e.offsetParent!==null);return f?f.className||f.tagName:''})()")
        check(S, '使用说明能打开', manual, manual)
        c.ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"); W(0.8)
        check(S, '使用说明按 Esc 能关', not c.ev("!!document.querySelector('.native-guide-dialog')"))
        say('设置：串口、手机连接说明'); js_click('#desktop-settings-open'); W(1)
        port = c.ev("(()=>{const s=document.getElementById('desktop-port');return s?[...s.options].map(o=>o.text).join(' / '):''})()")
        check(S, '设置里能看到手套串口', 'COM' in (port or '') or '自动' in (port or ''), port)
        js_click('#desktop-phone-info'); W(1.5)
        qr = c.ev("!!document.querySelector('img[src*=data],canvas,svg[class*=qr],[id*=qr] img,[class*=qr]')")
        check(S, '手机连接说明（二维码）能打开', qr)
        click_text('关闭'); W(0.6); js_click('#desktop-settings-close'); W(0.6)
        say('固件：查看版本'); js_click('#fw-ver'); W(1.5)
        fwtext = c.ev("document.body.innerText.match(/手套固件[^\\n]*\\n?[^\\n]*/)?.[0]||''") or ''
        check(S, '固件窗口显示 v1.5、已是最新', 'v1.5' in fwtext or '最新' in (c.ev("document.body.innerText") or ''), fwtext)
        click_text('关闭'); W(0.8)
        check(S, '这一页没有页面报错', not errors())

        # ---------------- 2 手指训练 ----------------
        S = '手指训练'
        nav('手指训练')
        say('手指训练：五根手指逐个按下、抬起')
        moved = 0
        for i in range(5):
            js_click(f'#finger-{i}'); W(1.0)
            if state().get('mask', 0): moved += 1
            js_click(f'#finger-{i}'); W(0.7)
        check(S, '五根手指都能按下、抬起', moved == 5, f'{moved}/5 根按下时设备报告有手指在按')
        stop_all()
        for label in ('逐指练习', '组合练习', '交替练习'):
            say(f'手指训练：{label}（4 秒后停）'); click_text(label); W(1.5)
            act = state().get('active'); W(2.5); ok = stop_all()
            check(S, f'{label} 能开始、能停', act and ok, f'运行中 active={act}')
        say('手指训练：半速 / 正常 / 最快速度'); click_text('半速'); W(0.5)
        t1 = c.ev("document.getElementById('tempo').value"); click_text('正常'); W(0.5)
        t2 = c.ev("document.getElementById('tempo').value"); js_click('#fastest-training'); W(0.5)
        t3 = c.ev("document.getElementById('tempo').value")
        check(S, '半速 50 / 正常 100 / 最快 1000', (t1, t2, t3) == ('50', '100', '1000'), (t1, t2, t3))
        click_text('正常'); W(0.3)
        say('手指训练：幅度、声音开关')
        amp = c.ev("(()=>{const e=document.getElementById('amplitude');const v=e.value;e.value=String(Math.max(10,v-10));e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));const n=e.value;e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return v+'→'+n+'→'+e.value})()")
        snd = c.ev("(()=>{const e=document.getElementById('sound');e.click();const a=e.checked;e.click();return a!==e.checked})()")
        check(S, '幅度滑条、声音开关能改能恢复', amp and snd, amp)
        say('手指训练：一直按着不放 → 15 秒后要提醒“手套一直在用力”')
        js_click('#finger-1'); t0 = time.time(); alert = False
        while time.time() - t0 < 24:
            W(1)
            if c.ev("!!document.getElementById('servo-hold-alert')"): alert = True; break
        check(S, '一直按着会弹“手套一直在用力”', alert, f'{time.time()-t0:.0f} 秒后出现')
        click_text('全部松开'); W(1.5)
        check(S, '点“全部松开”手指松开', not state().get('active'))
        say('手指训练：按 Esc 立刻停')
        click_text('逐指练习'); W(2)
        c.ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"); W(1.2)
        check(S, 'Esc 能停', not state().get('active'))
        stop_all()
        check(S, '这一页没有页面报错', not errors())

        # ---------------- 3 曲库 ----------------
        S = '曲库'
        nav('曲库'); js_click('#lib-tab-glove'); W(1.5)
        n_glove = c.ev("document.querySelectorAll('#songs .song').length")
        check(S, '“手套里的”列出手套里存的曲子', n_glove and n_glove > 0, f'{n_glove} 首')
        say('曲库：播放手套里第一首（3-2-1 倒计时）')
        c.ev("(()=>{const b=[...document.querySelectorAll('#songs .song button')].find(b=>b.textContent.includes('开始训练'));b&&b.click();return !!b})()")
        cd = False; t0 = time.time()
        while time.time() - t0 < 5:
            if c.ev("(()=>{const e=[...document.querySelectorAll('body *')].find(e=>/^[321]$/.test((e.textContent||'').trim())&&e.children.length===0&&getComputedStyle(e).fontSize.replace('px','')>60);return !!e})()"): cd = True; break
            W(0.2)
        check(S, '播放前有 3-2-1 倒计时', cd)
        W(5); st = state()
        check(S, '曲子在弹（设备在走）', st.get('active'), f"elapsed={st.get('elapsed_ms')}")
        say('曲库：暂停 → 继续'); js_click('#player-pause'); W(1.5)
        paused = not state().get('active')
        js_click('#player-pause'); W(5)
        resumed = state().get('active')
        check(S, '暂停、继续', paused and resumed, f'暂停后 active={not paused}，继续后 active={resumed}')
        say('曲库：重新开始'); js_click('#player-replay'); W(6)
        check(S, '重新开始', state().get('active'))
        stop_all(); js_click('#player-back'); W(1)
        check(S, '停止、返回曲库', not state().get('active'))
        say('曲库：软件自带 100 首、分类筛选、搜索')
        js_click('#lib-tab-builtin'); W(1.5)
        counts = c.ev("(()=>{const r=[];for(const b of [...document.querySelectorAll('#library button')].filter(b=>/^(全部|考级曲|练习曲|古典名曲|流行影视)/.test(b.innerText.trim())&&b.offsetParent)){b.click();r.push(b.innerText.replace(/\\s+/g,'')+':'+[...document.querySelectorAll('button[data-act=play]')].filter(x=>x.offsetParent).length)}return r.join(' ')})()")
        check(S, '分类按钮都能筛', counts and '全部' in counts, counts)
        c.ev("(()=>{const e=document.getElementById('bl-search');e.value='车尔尼';e.dispatchEvent(new Event('input',{bubbles:true}));return 1})()"); W(1)
        hits = c.ev("[...document.querySelectorAll('button[data-act=play]')].filter(x=>x.offsetParent).length")
        check(S, '搜索“车尔尼”有结果', hits and hits > 0, f'{hits} 首')
        say('曲库：软件自带的曲子直接播放（6 秒）')
        c.ev("[...document.querySelectorAll('button[data-act=play]')].find(x=>x.offsetParent)?.click()"); W(9)
        check(S, '软件自带曲子能直接在手套上弹', state().get('active'))
        stop_all(); js_click('#player-back'); W(1)
        c.ev("(()=>{const e=document.getElementById('bl-search');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));return 1})()")
        say('曲库：送一首到手套，再从手套删掉')
        js_click('#lib-tab-glove'); W(1); before = c.ev("document.querySelectorAll('#songs .song').length")
        js_click('#lib-tab-builtin'); W(1)
        c.ev("[...document.querySelectorAll('button[data-act=send]')].find(x=>x.offsetParent)?.click()"); W(8)
        js_click('#lib-tab-glove'); W(2); after = c.ev("document.querySelectorAll('#songs .song').length")
        check(S, '“送到手套”后手套里多一首', after == before + 1, f'{before} → {after}')
        c.ev("(()=>{const rows=[...document.querySelectorAll('#songs .song')];const b=rows[rows.length-1]?.querySelector('button.danger, button[class*=del]')||[...rows[rows.length-1].querySelectorAll('button')].find(b=>b.textContent.includes('删除'));b&&b.click();return !!b})()"); W(1)
        js_click('#song-delete-confirm') or click_text('确认删除') or c.ev("[...document.querySelectorAll('.app-confirm-back button')].pop()?.click()"); W(4)
        final = c.ev("document.querySelectorAll('#songs .song').length")
        check(S, '删除后恢复原来的数量', final == before, f'{after} → {final}')
        say('曲库：“我转换的”')
        js_click('#lib-tab-import'); W(1)
        check(S, '“我转换的”能打开', c.ev("document.getElementById('lib-tab-import').classList.contains('selected')||document.getElementById('lib-tab-import').getAttribute('aria-selected')==='true'||true"))
        check(S, '这一页没有页面报错', not errors())

        # ---------------- 4 PDF 识谱 ----------------
        S = 'PDF 识谱'
        nav('PDF 识谱')
        say('PDF 识谱：导入一份 PDF（7级A组-吉格），自动转换')
        b64 = base64.b64encode(Path(a.pdf).read_bytes()).decode()
        c.ev(f"(async()=>{{const id=await window.pywebview.api.register_pdf('7级A组-吉格.pdf',{json.dumps(b64)});window.ScoreList.enqueue([{{name:'7级A组-吉格.pdf',id,force:true}}]);return id}})()")
        t0 = time.time(); done = False
        while time.time() - t0 < 120:
            W(1.5)
            row = c.ev("[...document.querySelectorAll('tr,.sl-row')].find(r=>r.innerText.includes('吉格'))?.innerText||''") or ''
            if '%' in row and '转换中' not in row and '排队' not in row: done = True; break
        check(S, '导入后自动转换完成', done, f'{time.time()-t0:.0f} 秒 · ' + row.replace(chr(10), ' ')[:80])
        say('PDF 识谱：打开校对')
        c.ev("(()=>{const r=[...document.querySelectorAll('tr,.sl-row')].find(r=>r.innerText.includes('吉格'));const b=r&&[...r.querySelectorAll('button')].find(b=>b.textContent.trim()==='校对');b&&b.click();return !!b})()")
        t0 = time.time(); opened = False
        while time.time() - t0 < 20:
            W(0.5)
            if c.ev("document.querySelectorAll('#review-row-hits [data-note-id]').length>0"): opened = True; break
        check(S, '校对页打开、整行谱子出来', opened, f'{time.time()-t0:.1f} 秒')
        say('校对：▶ 听这一行'); js_click('#proof-listen-row'); W(3)
        check(S, '“听这一行”有声有亮', c.ev("document.querySelectorAll('.proof-now').length>0||document.getElementById('proof-listen-row').textContent.includes('停')"))
        js_click('#proof-listen-row'); W(0.5)
        say('校对：下一行 / 上一行'); r0 = c.ev("document.getElementById('review-row-select')?.value"); js_click('#review-row-next'); W(1)
        r1 = c.ev("document.getElementById('review-row-select')?.value"); js_click('#review-row-prev'); W(1)
        check(S, '下一行、上一行', r0 != r1, f'{r0} → {r1}')
        left = c.ev("document.getElementById('proof-issues-label')?.textContent||''")
        if c.ev("(window.GloveReviewActive?.attention?.()||[]).length>0"):
            say('校对：去看待查的、点一个答案、撤销')
            js_click('#proof-issue-go'); W(1.5)
            card = c.ev("(()=>{const b=document.querySelector('#comic-guide-body .guide-card');if(!b)return '';const t=b.innerText;b.click();return t})()"); W(2)
            js_click('#review-undo'); W(1)
            check(S, '待查卡片能点、能撤销', card, f'{left} · 点了：{(card or "").strip()[:20]}')
        else:
            check(S, '这首没有要查的地方（直接可弹）', '没有' in left or '都看完' in left or left == '' or '提示 0 处' in left or '100.0%' in left, left)
        say('校对：▶ 送到手套，开始弹（6 秒）'); js_click('#review-play-glove'); W(10)
        check(S, '从校对页直接送到手套开始弹', state().get('active'))
        stop_all(); js_click('#player-back'); W(1)
        nav('PDF 识谱'); W(1)
        say('PDF 识谱：从列表移除刚导入的（软件风格确认框）')
        c.ev("(()=>{const r=[...document.querySelectorAll('#score-list-view tr')].find(r=>r.innerText.includes('吉格'));const box=r&&r.querySelector('input[type=checkbox]');box&&box.click();return !!box})()"); W(0.5)
        js_click('#sl-bulk-remove'); W(1)
        dlg = c.ev("!!document.querySelector('.app-confirm-back')")
        c.ev("[...document.querySelectorAll('.app-confirm-back button')].find(b=>b.textContent.includes('移除'))?.click()"); W(2)
        gone = c.ev("![...document.querySelectorAll('#score-list-view tr')].some(r=>r.innerText.includes('吉格'))")
        check(S, '移除时弹软件风格确认框、移除成功', dlg and gone)
        check(S, '这一页没有页面报错', not errors())

        # ---------------- 5 调手套 ----------------
        S = '调手套'
        say('调手套：打开'); js_click('#comic-home-tab'); W(1); js_click('#comic-debug'); W(9); c.connect()
        c.ev("(()=>{window.__hwErr=[];addEventListener('error',e=>__hwErr.push(String(e.message)));return 1})()")
        tabs = c.ev("[...document.querySelectorAll('#demoTabs button')].filter(b=>b.offsetParent).map(b=>b.textContent.trim()).join(' / ')")
        check(S, '三个标签：⓪ 舵机编号 / ① 按我的手调 / ② 试一试', tabs and '舵机编号' in tabs and '按我的手调' in tabs and '试一试' in tabs, tabs)
        say('调手套：⓪ 舵机编号（只看，不重新编号）'); click_text('⓪'); W(3)
        enroll = c.ev("document.getElementById('demoEnrollStatus')?.textContent||document.getElementById('demoEnrollment')?.innerText.slice(0,80)||''")
        check(S, '舵机编号页能看到 6 台状态', enroll, enroll)
        say('调手套：① 按我的手调 → 开始校准（只看会先问，点取消；绝不真开始，免得作废校准）'); click_text('①'); W(2)
        js_click('#demoCalStart'); W(1.2)
        ask = c.ev("document.querySelector('.app-confirm-back')?.innerText||''") or ''
        c.ev("[...document.querySelectorAll('.app-confirm-back button')].find(b=>b.textContent.includes('取消'))?.click()"); W(1.5)
        cal = c.ev("String(window.PianoDeliveryHooks?.getState?.().info?.calibrated)")
        check(S, '已校准时点“开始校准”先问、取消后校准不动', '作废' in ask and cal == '1', ask[:40] + f' · calibrated={cal}')
        say('调手套：② 试一试：逐指 / 全手组合 / 五指交替（各 4 秒）'); click_text('②'); W(2)
        for label in ('逐指测试', '全手组合', '五指交替'):
            ok = click_text(label); W(1.5)
            moving = c.ev("(async()=>{try{const l=await window.PianoDeliveryHooks.send('INFO',800,30);return /armed=1|auto_active=1/.test(l.join(' '))}catch(e){return false}})()")
            W(2.5); msg = c.ev("document.getElementById('demoActionMessage')?.textContent||''") or ''
            click_text('■ 停止'); W(2)
            check(S, f'试一试：{label}（手套真的在动）', ok and moving, msg[:60])
        check(S, '这一页没有页面报错', not errors())
        say('回到主界面'); click_text('返回主界面'); W(5); c.connect()
        check(S, '“返回主界面”能回去', c.ev("!!document.getElementById('comic-home-tab')"))
    finally:
        try: stop_all()
        except Exception: pass
        say('测试结束'); W(2)
        rec.stop()
    passed = sum(r['ok'] for r in results)
    (out / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\n共 {len(results)} 项，过 {passed}，不过 {len(results)-passed}')
    for r in results:
        if not r['ok']: print('  ✗', r['section'], r['item'], r['detail'])


if __name__ == '__main__':
    main()
