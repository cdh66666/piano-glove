/* 音画对齐实测：声音到底有没有落在「手指压到琴键」那一刻。
 *
 * 用户的原话：「你这个声音对不对准，我觉得应该自己能测出来啊，这是有反馈的舵机啊；
 * 然后再单独加一个测试这个声音有没有对准的程序」。
 *
 * 为什么要单独一个程序，而不是看页面上的「实测 60ms」：
 *   页面上那个数是**声卡自报**的 baseLatency + outputLatency，它只是"应该补多少"的一半，
 *   另一半 —— 手指到底用了多久才走到琴键 —— 只有舵机反馈知道。
 *   这个程序把两条时间线**分别实测**出来，再合成一个净偏移，最后给出
 *   「音画对齐滑块该设成多少」这个**可以直接照做**的结论。
 *
 * 两条时间线：
 *   ① 声音侧：调用 tone() 的**提交时刻** vs 图里**真的出现信号**的时刻（挂 AnalyserNode 读波形）。
 *             这一差 = 调度误差，理论 0；它不为 0 说明提交时刻本身算错了。
 *   ② 舵机侧：发 MOVE 的时刻 vs POSALL 读到手指**越过起音点位置**的时刻（真舵机反馈）。
 *             这一步是"这是有反馈的舵机"那句话的兑现 —— 不用猜机械有多快。
 *
 * 用法：
 *   node diag_align.js                     模拟固件：只验 ①（②在模拟里没有意义，MOVE 是瞬时的）
 *   node diag_align.js --real              真板子：走 8123 上的本地桥。**会真的驱动舵机**
 *   HEADED=1 node diag_align.js --real     开窗口（真实声卡时 ①④ 才完全作数）
 *   URL=http://127.0.0.1:9000 node diag_align.js
 *   ROUNDS=10 node diag_align.js           每段测几轮（默认 6）
 *
 * ⚠️ --real 会让**参与演奏的那根手指真的按下**（满行程），一共 ROUNDS×3 次左右。
 *    手套戴在手上时请先摘下来，或者确认手指活动范围内没有人。
 *    测完会自动把手指放回待命位并失能。
 */
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const BASE   = process.env.URL || "http://127.0.0.1:8123";
const REAL   = process.argv.includes("--real");
const ROUNDS = Math.max(3, parseInt(process.env.ROUNDS || "6", 10) || 6);

function findChrome(){
  if(process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = path.join(process.env.LOCALAPPDATA || "", "ms-playwright");
  if(fs.existsSync(root)){
    for(const d of fs.readdirSync(root)){
      if(!d.startsWith("chromium-")) continue;
      const p = path.join(root, d, "chrome-win64", "chrome.exe");
      if(fs.existsSync(p)) return p;
    }
  }
  for(const p of ["C:/Program Files/Google/Chrome/Application/chrome.exe",
                  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]){
    if(fs.existsSync(p)) return p;
  }
  throw new Error("找不到 Chromium/Chrome，设 CHROME_PATH");
}

const median = a => {
  if(!a.length) return null;
  const b = a.slice().sort((x, y) => x - y);
  return b[Math.floor(b.length / 2)];
};
const ms = v => v === null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(1) + " ms";

/* ============ 在页面里跑的全部测量 ============ */
const PROBE = async opt => {
  const out = {
    mode: opt.real ? "real" : "sim", n: opt.n,
    sched: [], mech: [], full: [], miss: 0,
    stroke: strokeMs(), attack: attackPct(), lead: audioLeadMs(), offset: alignOffset(),
    base: 0, output: 0, toneLead: TONE_LEAD_MS
  };
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  /* ---------- ① 声音侧：从「提交」到「图里真的有信号」 ---------- */
  const ctx = audioCtx();
  if(!ctx) return { error: "这个浏览器没有 Web Audio" };
  if(ctx.state === "suspended"){ try{ await ctx.resume(); }catch(e){} await sleep(300); }
  if(ctx.state !== "running")
    return { error: "AudioContext 起不来（" + ctx.state + "）—— 先在页面上点一下「🔔 试听一下」再来" };
  out.base = (ctx.baseLatency || 0) * 1000;
  out.output = (ctx.outputLatency || 0) * 1000;

  /* 挂一个分析器读**波形**：声音有没有真的从图里出来、什么时候出来。
     分析器挂在 master 后面，再经一个 0 增益的 sink 接到 destination ——
     不是为了出声，是为了保证它**一定在渲染路径上**（否则可能压根不被拉取）。 */
  const an = ctx.createAnalyser();
  an.fftSize = 512;
  const sink = ctx.createGain(); sink.gain.value = 0;
  SND.master.connect(an); an.connect(sink); sink.connect(ctx.destination);
  const buf = new Float32Array(an.fftSize);
  const scan = () => {
    an.getFloatTimeDomainData(buf);
    let max = 0;
    for(let i = 0; i < buf.length; i++) max = Math.max(max, Math.abs(buf[i]));
    const th = Math.max(1e-6, max * 0.02);        // 相对阈值：包络是从 0.0001 起爬的
    for(let i = 0; i < buf.length; i++) if(Math.abs(buf[i]) > th) return { max, first: i };
    return { max, first: -1 };
  };
  const quiet = async () => {
    for(let i = 0; i < 60; i++){ if(scan().max < 1e-5) return true; await sleep(25); }
    return false;
  };

  if(!(await quiet()))
    return { error: "环境里有别的声音（或上一个音还没衰减完），等不安静 —— 关掉其它发声的程序再试" };

  for(let i = 0; i < opt.n; i++){
    const want = ctx.currentTime + TONE_LEAD_MS / 1000;
    tone(69, 90, 0.9, true);                       // force=true：试听/测量不受「播放声音」勾选影响
    let hit = null;
    const t0 = performance.now();
    while(performance.now() - t0 < 250){
      const s = scan();
      if(s.first >= 0){
        /* 缓冲里第 first 个样本 ≈ 当前时刻往前 (fftSize − first) 个样本。
           ctx.currentTime 按 128 样本的量子推进，所以这里自带约 ±1.5ms 的量化。 */
        hit = ctx.currentTime - (an.fftSize - s.first) / ctx.sampleRate;
        break;
      }
      await sleep(1);
    }
    if(hit === null) out.miss++;
    else out.sched.push((hit - want) * 1000);
    await quiet();
  }

  try{ SND.master.disconnect(an); }catch(e){}
  try{ an.disconnect(sink); sink.disconnect(); }catch(e){}
  if(!opt.real){
    out.note = "模拟固件：舵机是瞬时的，②③ 不测（测了也是 0ms，会误导）";
    return out;
  }

  /* ---------- ②③ 舵机侧：真舵机反馈 ---------- */
  const slot = (typeof PLAY_SLOTS !== "undefined" && PLAY_SLOTS.length) ? PLAY_SLOTS[0] : 0;
  await refreshSlots(true);
  const c = S.slots[slot] || {};
  const id = slotIdOf(slot);
  const dir = c.press === "min" ? -1 : 1;
  const standby = +c.standby, endPos = dir > 0 ? +c.max : +c.min;
  out.slot = slot; out.id = id; out.standby = standby; out.endPos = endPos;
  out.online = c.online === 1 || c.online === "1";
  out.calibrated = S.info.calibrated;
  if(!out.online || !c.valid || !Number.isFinite(standby) || !Number.isFinite(endPos)){
    out.note = "槽位 " + slot + " 没校准 / 不在线 —— 先回第 3 步校准";
    return out;
  }
  /* 起音点对应的是**位置**：待命位 → 按到底之间那一段的 attack 处 */
  const strike = Math.round(standby + (endPos - standby) * out.attack);
  out.strike = strike;
  const tol = posTolOf();

  if(S.info.armed !== "1" || S.needArm){
    const r = await T.send("ARM", 4000);
    if(!r.some(l => l.startsWith("OK ARM"))){ out.note = "使能失败 —— ARM 没回 OK"; return out; }
    S.needArm = false;
    await refreshInfo();
  }

  /* 一次「发 MOVE → 反复 POSALL 直到看见」的过程。
     返回 {cross, full}：越过起音点位置的耗时 / 走完全程到位的耗时。 */
  const once = async () => {
    await T.send("MOVE " + id + " " + standby + " 0 0 ARM", 2500);
    await sleep(260);                              // 先稳稳地回到待命位
    let p0 = await T.pollPos();
    for(let i = 0; i < 12 && !(p0 && Math.abs(p0[slot] - standby) <= tol); i++){
      await sleep(40); p0 = await T.pollPos();
    }
    const t0 = performance.now();
    T.fire("MOVE " + id + " " + endPos + " 0 0 ARM");
    let cross = null, full = null;
    for(let i = 0; i < 60; i++){
      const p = await T.pollPos();
      if(p && p[slot] >= 0){
        const v = p[slot];
        if(cross === null && (dir > 0 ? v >= strike : v <= strike)) cross = performance.now() - t0;
        if(full  === null && Math.abs(v - endPos) <= tol){ full = performance.now() - t0; break; }
      }
      await sleep(5);
    }
    return { cross, full };
  };

  for(let i = 0; i < opt.n; i++){
    const r = await once();
    if(r.cross !== null) out.mech.push(r.cross);
    if(r.full  !== null) out.full.push(r.full);
    await sleep(80);
  }
  /* 收尾：放回待命位、失能（和人离开时一样的状态） */
  await T.send("MOVE " + id + " " + standby + " 0 0 ARM", 2500);
  await sleep(300);
  T.fire("DISARM");
  out.note = "测完已把手指放回待命位并失能";
  return out;
};

/* ============ 报告 ============ */
(async () => {
  const headed = !!process.env.HEADED;
  const browser = await chromium.launch({
    executablePath: findChrome(),
    headless: !headed,
    args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required"]
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 950 } });
  page.on("console", m => { if(m.type() === "error") console.log("  [页面报错] " + m.text()); });

  await page.goto(BASE + "/web_piano_glove.html" + (REAL ? "" : "?sim=1"), { waitUntil: "load" });
  await page.waitForTimeout(800);
  const conn = await page.evaluate(() => ({ mode: T.mode, connected: T.connected, port: T.portName }));
  console.log("=== 音画对齐实测" + (REAL ? "（真板子）" : "（模拟固件）") + " ===");
  console.log("  页面通路：" + conn.mode + (conn.port ? " · " + conn.port : "") +
              ((REAL && !conn.connected) ? "　← 没连上，②③ 测不了" : ""));

  const r = await page.evaluate(PROBE, { real: REAL, n: ROUNDS });
  await browser.close();

  if(r.error){ console.log("\n测不了：" + r.error); process.exit(1); }

  const M = median(r.mech), F = median(r.full), S = median(r.sched);
  console.log("\n  行程时间（页面按它排曲）: " + r.stroke + " ms");
  console.log("  起音点                  : " + Math.round(r.attack * 100) + "%"
              + " → 手指压到琴键位置 = 按下后 " + Math.round(r.stroke * r.attack) + " ms");
  console.log("  页面补偿 sndLead        : " + r.lead + " ms"
              + "（声卡自报 " + r.base + "+" + r.output + "，调度提前 " + r.toneLead
              + "，微调 " + (r.offset > 0 ? "+" : "") + r.offset + "）");

  console.log("\n① 声音侧：提交 → 图里真的有信号");
  if(r.sched.length){
    const lo = Math.min(...r.sched), hi = Math.max(...r.sched);
    console.log("   中位 " + ms(S) + "（n=" + r.sched.length + "，范围 " + lo.toFixed(1)
                + "~" + hi.toFixed(1) + "，理论 0）"
                + (Math.abs(S) <= 4 ? "　✔ 调度准" : "　⚠ 提交时刻本身算错了"));
  }else{
    console.log("   ✗ 一个音都没检测到 —— 音频链路根本没出声（先去页面上点「🔔 试听一下」）");
  }
  if(r.miss) console.log("   （有 " + r.miss + " 轮没检测到，已跳过）");

  if(!REAL){
    console.log("\n② 舵机侧：跳过（" + (r.note || "模拟固件") + "）");
    console.log("\n要看真的净偏移，接上板子后跑：node diag_align.js --real");
    return;
  }

  console.log("\n② 舵机侧（真舵机反馈）：");
  if(!r.mech.length){
    console.log("   ✗ 没测到 —— " + (r.note || "POSALL 一直没读到位置"));
    return;
  }
  const A = r.stroke * r.attack;                       // 页面假定的「按下 → 压到琴键」
  const D = r.base + r.output;                         // 设备缓冲（浏览器自报）
  console.log("   发 MOVE → 手指越过起音点位置(槽位 " + r.slot + " id=" + r.id + " pos=" + r.strike + ")"
              + " ：中位 " + M.toFixed(0) + " ms（n=" + r.mech.length + "）");
  console.log("   页面假定这一段是 " + A.toFixed(0) + " ms　→　差 " + (M - A).toFixed(0) + " ms");
  if(F !== null){
    console.log("   发 MOVE → 满行程真的到位           ：中位 " + F.toFixed(0) + " ms（n="
                + r.full.length + "）");
    console.log("   页面按行程时间 " + r.stroke + " ms 排　→　差 " + (F - r.stroke).toFixed(0) + " ms"
                + (Math.abs(F - r.stroke) > 25 ? "　⚠ 差得多，回页面点一次「📏 自测」重量" : ""));
  }

  const net = A - r.lead + S + D - M;
  console.log("\n③ 合成净偏移（正 = 声音比手指压键晚）");
  console.log("   = 起音点 " + A.toFixed(0) + " − 补偿 " + r.lead + " + 调度 " + S.toFixed(1)
              + " + 设备缓冲 " + D.toFixed(0) + " − 机械 " + M.toFixed(0) + " = " + ms(net));
  const verdict = Math.abs(net) <= 25 ? "✔ 听觉上算对齐"
                : net > 0 ? "⚠ 声音偏晚" : "⚠ 声音偏早";
  console.log("   " + verdict + "（人耳对音画不同步的分辨力大约从 25~30ms 起）");
  if(Math.abs(net) > 10){
    const want = Math.max(-80, Math.min(80, Math.round(r.offset + net)));
    console.log("   → 把页面上的「音画对齐」滑块设成 " + (want > 0 ? "+" : "") + want + " ms"
                + "（现在是 " + (r.offset > 0 ? "+" : "") + r.offset + "）");
  }
  console.log("\n   说明：其中「设备缓冲 " + D.toFixed(0) + " ms」是**浏览器自己报的**，"
              + "不同驱动/蓝牙耳机报得未必准 ——");
  console.log("   所以这行结论是「按浏览器的说法」算出来的。真要定死，戴着手套弹两句，"
              + "用耳朵把滑块微调到你觉得齐为止。");
  console.log("   换了声卡 / 插上蓝牙耳机之后，重跑一遍这个程序。");
})().catch(e => { console.error("诊断脚本本身出错：" + e.message); process.exit(1); });
