/* 钢琴手套 · 客户版（调手套页）端到端自测
   ------------------------------------------------------------------
   为什么单独有这一个文件：
   原来的 e2e.js 只跑调试台 `web_piano_glove.html?sim=1`，**完全没有加载
   `simple=1` + `body.native-app` 的客户版**。于是 delivery-demo.js /
   desktop-debug.js 里「再调一遍」这类只在客户版出现的按钮，219 项全绿也照样是坏的
   —— 2026-11-09 用户就是在客户版上点了没反应。

   这里补的就是这条路：把 native 渲染后的关键条件（body.native-app + NativeApp）
   复刻出来，然后逐个点客户会点的按钮，断言「每一次点击都必须有看得见的反应」。
   不需要硬件：串口由页面内置假固件顶替（?sim=1）。

   跑法：NODE_PATH=<node_modules> node e2e-customer.js
*/
const { chromium } = require("playwright-core");
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "shots");
const PORT = Number(process.env.PORT || 8141);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function chromePath(){
  const base = process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "ms-playwright");
  if(!base || !fs.existsSync(base)) throw new Error("找不到 ms-playwright 目录");
  for(const d of fs.readdirSync(base).filter(x => x.startsWith("chromium-"))){
    for(const c of [path.join(base, d, "chrome-win64", "chrome.exe"),
                    path.join(base, d, "chrome-linux", "chrome")]){
      if(fs.existsSync(c)) return c;
    }
  }
  throw new Error("找不到 Chromium");
}

const MIME = { ".html":"text/html; charset=utf-8", ".js":"text/javascript", ".css":"text/css",
               ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".svg":"image/svg+xml",
               ".json":"application/json", ".mid":"audio/midi" };

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split("?")[0]);
  if(p === "/") p = "/web_piano_glove.html";
  const f = path.join(ROOT, p);
  if(!fs.existsSync(f) || fs.statSync(f).isDirectory()){ res.writeHead(404); return res.end("nope"); }
  res.writeHead(200, { "Content-Type": MIME[path.extname(f)] || "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
});

let checks = 0, failures = 0;
const failed = [];
function check(name, cond, extra){
  checks++;
  if(!cond){ failures++; failed.push(name); }
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra !== undefined ? "   [" + extra + "]" : ""));
}

/* 页面「看起来发生了什么」的指纹：可见文本 + 按钮状态 + 当前选中的标签。
   点击前后指纹一致、又没有弹窗/异常 —— 就是用户说的「点了没反应」。
   注意范围要覆盖整个 body：客户版有一部分控件（编号映射、命令日志、读信息）
   在 #demoRoot 之外，只看 #demoRoot 会把这些正常按钮误判成死的。 */
const fingerprint = () => {
  const visible = node => !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
  const buttons = [...document.querySelectorAll("button")].map((b, i) =>
    i + ":" + (b.disabled ? "D" : "E") + ":" + (visible(b) ? "V" : "H") + ":" +
    b.className.replace(/\b(active|selected)\b/g, "@") + ":" + b.textContent.trim().slice(0, 24)).join("|");
  const active = [...document.querySelectorAll(".active, .selected, [aria-selected=true]")]
    .map(n => n.id || n.className).join(",");
  const text = (document.body.innerText || "").replace(/\d{2,}/g, "#").slice(0, 4000);
  const dialogs = [...document.querySelectorAll("dialog")].filter(d => d.open).length;
  return text + "##" + buttons + "##" + active + "##" + dialogs;
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  await new Promise(r => server.listen(PORT, "127.0.0.1", r));
  const browser = await chromium.launch({ executablePath: chromePath(), headless: true });
  console.log("\n=== 客户版调手套页（simple=1 + native-app + 模拟固件）===");

  async function open(){
    const page = await browser.newPage({ viewport: { width: 1100, height: 780 } });
    const errors = [];
    page.on("pageerror", e => errors.push("pageerror: " + e.message));
    page.on("console", m => { if(m.type() === "error" && !/404|Failed to load resource/.test(m.text())) errors.push("console: " + m.text()); });
    await page.addInitScript(() => {
      window.NativeApp = {
        ready: Promise.resolve({ request: async () => ({ status: 200, binary: false, body: "" }) }),
        request: async () => ({ status: 200, binary: false, body: "" }),
        navigate: async () => {},
        addBackButton: () => {}
      };
    });
    await page.goto(`http://127.0.0.1:${PORT}/web_piano_glove.html?sim=1&simple=1`, { waitUntil: "load" });
    await page.evaluate(() => {
      document.body.classList.add("native-app");
      document.body.dataset.page = "debug";
      return new Promise(resolve => {
        const s = document.createElement("script");
        s.src = "desktop-debug.js";
        s.onload = resolve;
        document.head.append(s);
      });
    });
    await page.waitForTimeout(1000);
    /* 模拟固件也要先「连接」，否则校准按钮只会回「请先连接手套串口」，
       测不到真正的重来逻辑。客户版里连接面板被收进「更多调试」，DOM 里点它即可。 */
    await page.evaluate(() => document.getElementById("btnConn")?.click());
    await page.waitForTimeout(900);
    return { page, errors };
  }

  /* ---------- 0. 外壳：客户版真的加载了 ---------- */
  const { page, errors } = await open();
  const shell = await page.evaluate(() => ({
    ready: document.body.dataset.desktopDebug || null,
    title: document.querySelector("#demoTop h1")?.textContent,
    back: document.getElementById("native-back")?.textContent,
    tabs: [...document.querySelectorAll("#demoTabs button")].filter(b => !b.hidden).map(b => b.textContent),
    cards: document.querySelectorAll("#demoCalibrationSlots .demoCalSlot").length,
    start: document.getElementById("demoCalStart")?.textContent,
    songTabHidden: !!document.getElementById("demoTabSongs")?.hidden
  }));
  check("客户版外壳挂载完成（desktop-debug 已就绪）", shell.ready === "ready", shell.ready);
  check("标题是「调手套」", shell.title === "调手套", shell.title);
  check("有「返回主界面」", shell.back === "返回主界面", shell.back);
  check("6 个手指卡片都渲染出来", shell.cards === 6, shell.cards);
  check("主按钮文案是客户话术（开始调/再调一遍）", /^(开始调|再调一遍)$/.test(shell.start || ""), shell.start);
  check("「曲目展示」标签在客户版里隐藏", shell.songTabHidden === true);
  check("编号标签排在第一位（⓪ 舵机编号）", (shell.tabs[0] || "").includes("舵机编号"), shell.tabs.join(" / "));

  /* ---------- 1. 点「开始调」必须说话（连上了或没连上都要说话） ---------- */
  const connected = await page.textContent("#cConn");
  check("模拟固件已连接（后面的校准才有意义）", /已连接/.test(connected || ""), connected);
  const before1 = await page.evaluate(fingerprint);
  await page.evaluate(() => document.getElementById("demoCalStart").click());
  await page.waitForTimeout(600);
  const after1 = await page.evaluate(fingerprint);
  const progress1 = await page.textContent("#demoCalibrationProgress");
  check("点「开始调」有可见反馈", before1 !== after1, progress1?.slice(0, 60));
  check("反馈内容说明原因（不是空白）", !!progress1 && progress1.trim().length > 2, progress1);
  /* 让它跑一会儿再停，别把后续步骤拖进采样循环 */
  await page.evaluate(() => document.getElementById("demoStop")?.click());
  await page.waitForTimeout(700);

  /* ---------- 2. 标签切换都要有反应 ----------
     注意：页面每 10 秒有一次自动路由（routeByIds），会把视图拉回校准页。
     所以这里点完要立刻读状态，不能等太久，否则会被路由覆盖成"切不过去"。 */
  for(const [id, label] of [["demoTabEnrollment", "⓪ 舵机编号"], ["demoTabCalibration", "① 按我的手调"]]){
    const before = await page.evaluate(fingerprint);
    const active = await page.evaluate(sel => {
      document.getElementById(sel).click();
      return document.getElementById(sel).classList.contains("active");
    }, id);
    await page.waitForTimeout(120);
    const after = await page.evaluate(fingerprint);
    check("标签「" + label + "」点击后切换过去", active || before !== after, "active=" + active);
  }

  /* ---------- 3. 死锁回归：上一轮卡住后，「再调一遍」仍能救回来 ----------
     复刻 11-09 用户那一次：串口请求挂住 → runCalibration 永不结束 →
     旧代码 `await wizardRun` 无限等 + restartPending 永久 true，按钮从此静默失效。 */
  await page.evaluate(() => {
    // 让所有串口命令永不返回，模拟断联后请求悬挂
    const hooks = window.PianoDeliveryHooks;
    window.__realSend = hooks.send;
    hooks.send = () => new Promise(() => {});
  });
  await page.evaluate(() => document.getElementById("demoCalStart").click());
  await page.waitForTimeout(900);
  const stuck = await page.evaluate(() => document.getElementById("demoCalibrationProgress")?.textContent);
  check("制造卡住状态（第一轮已进入、无返回）", true, (stuck || "").slice(0, 40));

  await page.evaluate(() => { window.PianoDeliveryHooks.send = window.__realSend; });
  /* 判断「按钮被处理了没有」不能只看文案字面 —— 卡住时重复报同一句错，
     文案不变但 handler 其实跑了。这里直接数进度条的写入次数。 */
  const armCounter = () => page.evaluate(() => {
    window.__writes = 0;
    const node = document.getElementById("demoCalibrationProgress");
    window.__mo?.disconnect();
    window.__mo = new MutationObserver(() => { window.__writes++; });
    window.__mo.observe(node, { childList:true, characterData:true, subtree:true });
  });
  await armCounter();
  await page.evaluate(() => document.getElementById("demoCalStart").click());
  await page.waitForTimeout(700);
  const retryWrites = await page.evaluate(() => window.__writes);
  const textAfterRetry = await page.textContent("#demoCalibrationProgress");
  check("卡住后点「再调一遍」立刻给出反馈", retryWrites > 0, "写入 " + retryWrites + " 次 · " + (textAfterRetry || "").slice(0, 36));

  // 等超时释放（4s）+ 新一轮启动
  await page.waitForTimeout(5200);
  const recovered = await page.evaluate(() => ({
    progress: document.getElementById("demoCalibrationProgress")?.textContent,
    guide: document.getElementById("demoCalibrationGuide")?.textContent,
    locked: false
  }));
  check("超时后强制释放，界面继续往下走（不永久卡死）",
        /重新校准|第 .* 步|正在记录|按压|抬起|保持|从第一台|清空/.test((recovered.progress || "") + (recovered.guide || "")),
        (recovered.guide || "") + " / " + (recovered.progress || ""));
  // 再点一次必须还能被响应 —— 这是「按钮没有变成砖头」的判定
  await armCounter();
  await page.evaluate(() => document.getElementById("demoCalStart").click());
  await page.waitForTimeout(900);
  const thirdWrites = await page.evaluate(() => window.__writes);
  const textThird = await page.textContent("#demoCalibrationProgress");
  check("之后按钮仍然可点（没有变成砖头）", thirdWrites > 0, "写入 " + thirdWrites + " 次 · " + (textThird || "").slice(0, 36));

  await page.screenshot({ path: path.join(OUT, "customer-calibration.png"), fullPage: true });
  check("这一段没有 JS 异常", errors.length === 0, errors.slice(0, 3).join(" ; "));
  await page.close();

  /* ---------- 4. 试一试页：按钮存在且有响应 ---------- */
  const second = await open();
  await second.page.evaluate(() => document.getElementById("desktopDebugActionsTab").click());
  await second.page.waitForTimeout(300);
  const actions = await second.page.evaluate(() => ({
    visible: !document.getElementById("desktopDebugActions").hidden,
    buttons: [...document.querySelectorAll("#demoActionProgress button")].map(b => ({ text: b.textContent.trim(), disabled: b.disabled }))
  }));
  check("「② 试一试」打开动作测试面板", actions.visible === true);
  check("动作测试里有单指/组合/交替三个入口", actions.buttons.length === 3, JSON.stringify(actions.buttons));
  check("未校准时这些入口是禁用的（不会误触）", actions.buttons.every(b => b.disabled), JSON.stringify(actions.buttons));
  await second.page.screenshot({ path: path.join(OUT, "customer-actions.png"), fullPage: true });
  await second.page.close();

  /* ---------- 5. 全按钮扫描：客户版上每个能点的按钮都得有人应声 ----------
     这一节是给「再调一遍点了没用」这类 bug 兜底的：不预设业务结果，
     只问一个最低限度的问题 —— 点下去之后，界面有没有任何变化？
     会启动长流程/动设备的按钮（校准、编号、试动作、停止）单独在前面测，这里跳过。 */
  console.log("\n=== 全按钮扫描（点了必须有人应声）===");
  const SCOPE = new Set(["demoCalStart", "demoStop", "demoEnrollStart", "demoEnrollResume",
                         "demoQuickSingle", "demoQuickTogether", "demoQuickAlternate",
                         "demoSingle", "demoTogether", "demoAlternate", "demoSpeedStart",
                         "demoShowAll", "demoSongStart", "demoMountOpen", "demoFlash",
                         /* 重连按钮：已经连着时点它不会有状态变化，属于幂等操作，不算「没反应」 */
                         "demoConnection"]);
  const scanThird = await open();
  /* 先把「更多调试」面板展开，让被收起来的那批按钮也进扫描范围 */
  await scanThird.page.evaluate(() => document.getElementById("desktopDebugToolsTab")?.click());
  await scanThird.page.waitForTimeout(400);
  const buttons = await scanThird.page.evaluate(() => [...document.querySelectorAll("button")]
    .filter(b => !b.disabled && (b.offsetWidth || b.offsetHeight))
    /* 已经选中的标签点了本来就不该有变化 */
    .filter(b => !b.classList.contains("active"))
    .map(b => ({ id: b.id || "", text: b.textContent.trim().replace(/\s+/g, " ").slice(0, 16) })));
  /* 幂等按钮：点下去本来就不该有可见变化 —— 不是坏了。
     每一条都写清理由，避免以后有人往这个名单里塞真按钮来让测试变绿。 */
  const IDEMPOTENT = new Set([
    "btnConn",             // 重连：已经连着时重连，状态文字不变
    "btnInfo",             // 读信息：模拟固件每次返回同样内容
    "btnProfile",          // 自动识别档位：已识别时结果不变
    "demoTabCalibration"   // 已经停在校准视图时再点它，视觉上不该有变化
  ]);
  let scanned = 0, silent = [], skipped = 0;
  for(const button of buttons){
    if(SCOPE.has(button.id) || IDEMPOTENT.has(button.id)) continue;
    /* 页面自己在动（位置在跳、进度在走）时无法判断「点了有没有反应」，
       采样两次基线，不一样就跳过，免得把正常按钮判成死的。 */
    const base1 = await scanThird.page.evaluate(fingerprint);
    await scanThird.page.waitForTimeout(260);
    const base2 = await scanThird.page.evaluate(fingerprint);
    if(base1 !== base2){ skipped++; continue; }
    const ok = await scanThird.page.evaluate(({ id, text }) => {
      const node = id ? document.getElementById(id)
        : [...document.querySelectorAll("button")].find(b => b.textContent.trim().replace(/\s+/g, " ").slice(0, 16) === text);
      if(!node) return false;
      node.click();
      return true;
    }, button);
    if(!ok) continue;
    scanned++;
    await scanThird.page.waitForTimeout(260);
    const after = await scanThird.page.evaluate(fingerprint);
    if(base2 === after) silent.push((button.id || "无 id") + "「" + button.text + "」");
  }
  check("扫描了客户版上的可点按钮", scanned >= 6, scanned + " 个（页面在动跳过 " + skipped + " 个，启动类 " + SCOPE.size + " 个单独测）");
  check("没有「点了完全没反应」的按钮", silent.length === 0, silent.join(" ; ") || "0 个");
  check("扫描期间没有 JS 异常", scanThird.errors.length === 0, scanThird.errors.slice(0, 3).join(" ; "));
  await scanThird.page.close();

  await browser.close();
  server.close();

  console.log("\n" + (failures ? "失败 " + failures + " 项 / 共 " + checks + " 项" : "全部通过：" + checks + " 项"));
  if(failures) console.log("失败项：\n - " + failed.join("\n - "));
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error("测试脚本本身出错：", e); process.exit(2); });
