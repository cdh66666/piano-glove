"""全按钮测试：连上正在运行的钢琴手套程序（WebView2 调试口），每个页面把看得见、能点的按钮/勾选框/下拉框/滑条
都动一下，记录：点了有没有反应（页面有变化、有提示或弹窗）、有没有 JS 报错。每页截图。

    启动程序时带调试口：set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9360
    python tools/dev/button_sweep.py --port 9360 --out D:/cc_work/测试视频_20261109/全按钮

不点的（会开系统选文件窗口、会删东西、会烧固件）：名字里带 删除/移除/上传/选择文件/选择 PDF/添加 PDF/下载/烧录/升级/更新固件。
这些另测。没接手套时，要手套的按钮本来就是灰的，只检查它“灰得对”（有提示为什么灰）。
"""
import argparse, base64, json, sys, time, urllib.request
from pathlib import Path
import websocket

SKIP = ('删除', '移除', '上传', '选择文件', '选择 PDF', '添加 PDF', '下载', '烧录', '升级', '更新固件', '重新编号', '全部重新校准', '开始调', '再调一遍')
PAGES = ('开始', '手指训练', '曲库', 'PDF 识谱')

PROBE = r"""(async(skip)=>{
 const W=t=>new Promise(r=>setTimeout(r,t));
 window.__sweepErr=window.__sweepErr||[];if(!window.__sweepHooked){window.__sweepHooked=1;addEventListener('error',e=>__sweepErr.push(String(e.message)));addEventListener('unhandledrejection',e=>__sweepErr.push('promise: '+String(e.reason&&e.reason.message||e.reason)));}
 const vis=e=>{const r=e.getBoundingClientRect();return r.width>2&&r.height>2&&getComputedStyle(e).visibility!=='hidden'&&e.offsetParent!==null;};
 const label=e=>(e.innerText||e.value||e.getAttribute('aria-label')||e.title||e.id||e.tagName).trim().replace(/\s+/g,' ').slice(0,30);
 const nodes=[...document.querySelectorAll('main button, main [role=button], main input[type=checkbox], main input[type=range], main select, main summary, header button, nav button')].filter(vis);
 const out=[];const seen=new Set();
 for(const e of nodes){
  const name=label(e);const key=name+'|'+e.id;if(seen.has(key))continue;seen.add(key);
  if(e.closest('nav')&&e.tagName==='BUTTON'){out.push({name,kind:'导航',result:'另测'});continue;}
  if(skip.some(w=>name.includes(w))){out.push({name,kind:'跳过',result:'会开系统窗口/删数据/改设备，另测'});continue;}
  if(e.disabled){out.push({name,kind:'灰',result:e.title?('灰：'+e.title.slice(0,40)):'灰'});continue;}
  const before=document.body.innerHTML.length,errs=__sweepErr.length;let changed=0;
  const mo=new MutationObserver(m=>changed+=m.length);mo.observe(document.body,{subtree:true,childList:true,attributes:true,characterData:true});
  try{
   if(e.type==='range'){const v=e.value;e.value=String(Math.min(Number(e.max||100),Number(v)+Number(e.step||1)*5));e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));await W(300);e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}
   else if(e.tagName==='SELECT'){const v=e.value;const opts=[...e.options].map(o=>o.value);const other=opts.find(o=>o!==v);if(other!==undefined){e.value=other;e.dispatchEvent(new Event('change',{bubbles:true}));await W(500);e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}));}}
   else e.click();
  }catch(x){__sweepErr.push('点击异常 '+name+': '+x.message);}
  await W(700);mo.disconnect();
  const newErr=__sweepErr.slice(errs);
  out.push({name,kind:e.tagName.toLowerCase(),result:newErr.length?'报错：'+newErr.join(' / ').slice(0,120):changed?'有反应':'没反应'});
  // 收尾：关掉弹出来的东西，停掉动作，别影响下一个
  for(const b of document.querySelectorAll('.app-confirm-back button')){if(/取消|关闭|知道了/.test(b.textContent)){b.click();break;}}
  document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  for(const id of ['proof-coach-close','comic-coach-close']){const x=document.getElementById(id);if(x&&vis(x))x.click();}
  await W(200);
 }
 return out;
})"""


class Cdp:
    def __init__(self, port):
        self.port = port; self.i = 0; self.connect()

    def connect(self):
        pages = [p for p in json.load(urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json')) if p.get('type') == 'page']
        self.ws = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=300)

    def call(self, method, params=None):
        self.i += 1; self.ws.send(json.dumps({'id': self.i, 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == self.i: return r

    def eval(self, expr):
        r = self.call('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        return r.get('result', {}).get('result', {}).get('value')

    def shot(self, path):
        r = self.call('Page.captureScreenshot', {'format': 'png'})
        Path(path).write_bytes(base64.b64decode(r['result']['data']))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=9360)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cdp = Cdp(a.port)
    report = {}
    for n, page in enumerate(PAGES, 1):
        cdp.eval("(()=>{document.getElementById('comic-coach-close')?.click();const b=[...document.querySelectorAll('nav button, header button, button')].find(b=>b.textContent.trim()===%s);b&&b.click();return !!b})()" % json.dumps(page))
        time.sleep(1.5)
        cdp.shot(out / f'{n:02d}_{page}.png')
        rows = cdp.eval(PROBE + '(%s)' % json.dumps(SKIP, ensure_ascii=False)) or []
        report[page] = rows
        cdp.shot(out / f'{n:02d}_{page}_点完.png')
    # 调手套是另一个页面
    cdp.eval("(()=>{const b=[...document.querySelectorAll('button,a')].find(b=>b.textContent.trim()==='调手套');b&&b.click();return 1})()")
    time.sleep(8); cdp.connect()
    cdp.shot(out / '05_调手套.png')
    rows = cdp.eval(PROBE.replace("main button, main [role=button], main input[type=checkbox], main input[type=range], main select, main summary, header button, nav button", "#demoRoot button, #demoRoot input[type=range], #demoRoot select, #demoTabs button") + '(%s)' % json.dumps(SKIP, ensure_ascii=False)) or []
    report['调手套'] = rows
    cdp.shot(out / '05_调手套_点完.png')
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    bad = 0
    for page, rows in report.items():
        print('==', page, len(rows), '个')
        for r in rows:
            mark = '✗' if r['result'].startswith(('报错', '没反应')) else ' '
            bad += mark == '✗'
            print(f"  {mark} [{r['kind']}] {r['name']} → {r['result']}")
    print('有问题的：', bad)


if __name__ == '__main__':
    main()
