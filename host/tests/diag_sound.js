/* 「演奏没声音」分诊：把可能的断点逐环量出来，不猜，最后直接给结论。
 *
 * 为什么要单独写这个：用户报「演奏没声音」时，真正的断点可能在好几个完全不同的地方 ——
 *   ① 演奏页**第一级门禁**：校准没保存 → `#playBody` 整块被隐藏 → 连曲库下拉都点不到；
 *      这时页面正常、板子也正常，只是**你根本按不到任何东西**
 *   ② 演奏页**第二级门禁**：还没载入曲谱 → `#midiPanel` 隐藏 → 「开始演奏」「播放声音」
 *      「试听一下」全在里面，照样点不到（这一级是**正常设计**：没曲当然不能演奏）
 *   ③ 音频链路没起来 —— `AudioContext` 没创建 / 没解锁 / 音量 0
 *   ④ 页面自己的 `tone()` 不出信号 —— 调度逻辑的锅
 *   ⑤ 系统 / 浏览器的输出设备问题 —— 页面无辜
 * 光读代码分不清，靠耳朵更分不清（而且"我这边听不到"≠"信号没生成"）。
 * 所以按上面的顺序逐环量，每环给一个能自证的读数，最后一段直接说是哪儿断的。
 *
 * 判据是 `AnalyserNode` 读到的**图内信号峰值**（挂在 master 后面）：
 * 页面 `tone()` 真的产生了波形就读到 > 0 的峰值 —— 这只说明"信号生成了"，
 * 与有没有真实输出设备无关，所以**无头模式也完全作数**。
 * 想验"真的从扬声器出来了"，那是 `diag_audio.js`（读声卡自报延迟）的事了。
 *
 * 用法：
 *   node diag_sound.js
 *   URL=http://127.0.0.1:9000/web_piano_glove.html node diag_sound.js
 *
 * 全程只点页面上的按钮，**不碰舵机**。
 */
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const PAGE = process.env.URL || "http://127.0.0.1:8123/web_piano_glove.html";

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

const show = (tag, o) => { console.log("\n=== " + tag + " ==="); console.log(JSON.stringify(o, null, 2)); };

/* 真实可见性 —— 用 offsetParent 判，getComputedStyle **不反映祖先 display:none**，
   以前就因此误判过「按钮是 shown」（其实整块被祖先藏了）。 */
const VIS = () => {
  const real = s => {
    const el = document.querySelector(s); if(!el) return "(无此元素)";
    return el.offsetParent === null ? "HIDDEN" : "shown";
  };
  const g = document.querySelector("#playGate");
  const ap = document.querySelector(".page.active");
  return {
    activePage: ap ? ap.id : "(无)",
    playGate:   real("#playGate"),
    playBody:   real("#playBody"),
    midiPanel:  real("#midiPanel"),
    btnSample:  real("#btnSample"),
    btnPlay:    real("#btnPlay"),
    sndOn:      real("#sndOn"),
    btnSndTest: real("#btnSndTest"),
    calibrated: (typeof S !== "undefined" && S.info) ? S.info.calibrated : "(未知)",
    hasPlan:    (typeof S !== "undefined" && S.plan) ? S.plan.events.length : null,
    gateText:   g ? g.textContent.replace(/\s+/g, " ").trim().slice(0, 160) : "(无)"
  };
};

(async () => {
  const browser = await chromium.launch({
    executablePath: findChrome(), headless: !process.env.HEADED,
    args: ["--no-sandbox", "--disable-dev-shm-usage"]
  });
  const page = await browser.newPage();
  const errs = [];
  page.on("pageerror", e => errs.push("pageerror: " + e.message));
  page.on("console", m => { if(m.type() === "error") errs.push("console.error: " + m.text()); });

  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForTimeout(4500);              // 等页面自动探测桥 + INFO 回来

  /* 用「真点 tab」切到演奏页 —— 既走真实的 goto()，
     又顺手建立 user activation（音频解锁靠的就是它）。 */
  const tab = await page.$('#tabbar button[data-p="play"]');
  if(tab){ await tab.click(); await page.waitForTimeout(500); }

  /* ---------- ① 原始状态：两级门禁各自可见吗 ---------- */
  const before = await page.evaluate(VIS);
  show("① 刚进演奏页（还没动任何东西）", before);

  /* 第一级门禁的根因确证：把 calibrated 假装成 1（**纯页面侧，不动板子**），
     看 playBody 是不是立刻打开。是的话，根因就锁定为「校准没保存」。 */
  let gateFix = null;
  if(before.playBody === "HIDDEN" && before.calibrated !== "(未知)"){
    gateFix = await page.evaluate(() => {
      const real = s => {
        const el = document.querySelector(s);
        return el && el.offsetParent !== null ? "shown" : "HIDDEN";
      };
      const b = { playBody: real("#playBody"), midiPanel: real("#midiPanel") };
      S.info.calibrated = "1";
      try { updateGates(); } catch(e){ return { err: String(e) }; }
      return { before: b, after: { playBody: real("#playBody"), midiPanel: real("#midiPanel") } };
    });
    show("①b 假装 calibrated=1 之后（确证第一级门禁的根因）", gateFix);
    await page.waitForTimeout(200);
  }

  /* ①c 推进到「真正可演奏」的状态 —— 两级门禁都要过。
     第二级（midiPanel）靠**载入一首曲**打开：曲库里全是内嵌 base64，
     点「先拿内置的《两只老虎》试试」就是最省事的路，纯前端、不碰舵机。 */
  const sampleBtn = await page.$("#btnSample");
  let loaded = null;
  if(sampleBtn && await sampleBtn.isVisible()){
    await sampleBtn.click();
    await page.waitForTimeout(2000);
    loaded = await page.evaluate(VIS);
    show("①c 载入内置曲之后（第二级门禁：midiPanel）", loaded);
    if(gateFix) console.log("   ※ 这里的 calibrated 是 ①b 临时假装的**页面侧**值，板子没有变");
  } else {
    console.log("\n!! #btnSample 点不到（playBody 仍隐藏）—— 第二级门禁测不了，后面跳过音频实测");
  }

  /* ---------- ② 音频链路快照 ---------- */
  const snap = await page.evaluate(() => {
    const q = s => document.querySelector(s);
    const T = (fn, d) => { try { return fn(); } catch(e){ return "ERR:" + (e && e.message); } };
    return {
      sndOn:        q("#sndOn")    ? q("#sndOn").checked : "(无此控件)",
      sndVol:       q("#sndVol")   ? q("#sndVol").value  : null,
      sndStateText: q("#sndState") ? q("#sndState").textContent : "(无此元素)",
      ctx:          T(() => SND.ctx ? { state: SND.ctx.state, sr: SND.ctx.sampleRate } : "(未创建)"),
      master:       T(() => SND.master ? SND.master.gain.value : null),
      plan:         T(() => S.plan ? { stroke: S.plan.stroke, n: S.plan.events.length } : null),
      closedLoop:   T(() => closedLoopOn()),
      strokeMs:     T(() => strokeMs()),
      sndLead:      T(() => audioLeadMs()),
      attackPct:    T(() => attackPct())
    };
  });
  show("② 音频链路快照", snap);

  const toneBtn = await page.$("#btnSndTest");
  let pageTone = null, rawPeak = null;

  if(toneBtn && await toneBtn.isVisible()){
    // 挂 AnalyserNode 到 master 后面 —— 这是"信号到底有没有生成"的唯一硬证据
    await page.evaluate(() => {
      window.__rms = { peak: 0, n: 0 };
      try {
        const ctx = SND.ctx;
        if(!ctx){ window.__rms.err = "ctx 还没创建"; return; }
        const an = ctx.createAnalyser(); an.fftSize = 2048;
        try { SND.master.disconnect(); } catch(e){}
        SND.master.connect(an); an.connect(ctx.destination);
        const buf = new Float32Array(an.fftSize);
        window.__anTimer = setInterval(() => {
          an.getFloatTimeDomainData(buf);
          let p = 0;
          for(let i = 0; i < buf.length; i++){ const v = Math.abs(buf[i]); if(v > p) p = v; }
          if(p > window.__rms.peak) window.__rms.peak = p;
          window.__rms.n++;
        }, 25);
      } catch(e){ window.__rms.err = String(e); }
    });

    /* ---------- ③ 页面自己的 tone() ---------- */
    await toneBtn.click();
    await page.waitForTimeout(1800);
    pageTone = await page.evaluate(() => ({
      fired:  (S.sndFired || 0),
      badge:  (document.querySelector("#sndState") || {}).textContent,
      peak:   window.__rms ? +(window.__rms.peak).toFixed(4) : null,
      n:      window.__rms ? window.__rms.n : 0,
      err:    window.__rms ? window.__rms.err : null
    }));

    /* ---------- ④ 对照组：裸 oscillator（排除页面逻辑） ---------- */
    rawPeak = await page.evaluate(async () => {
      if(!SND.ctx) return null;
      const ctx = SND.ctx;
      const an = ctx.createAnalyser(); an.fftSize = 2048;
      const buf = new Float32Array(an.fftSize);
      const peak = () => {
        an.getFloatTimeDomainData(buf);
        let m = 0; for(let i = 0; i < buf.length; i++){ const v = Math.abs(buf[i]); if(v > m) m = v; }
        return m;
      };
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 440; g.gain.value = 0.3;
      o.connect(g); g.connect(an); o.start();
      let pk = 0; const t0 = performance.now();
      while(performance.now() - t0 < 500){ pk = Math.max(pk, peak()); await new Promise(r => setTimeout(r, 20)); }
      o.stop(); an.disconnect();
      return +pk.toFixed(4);
    });
    show("③ 页面 tone() / ④ 对照组裸 oscillator", { pageTone, rawOscPeak: rawPeak });

    await page.evaluate(() => { if(window.__anTimer) clearInterval(window.__anTimer); });
  } else {
    console.log("\n!! #btnSndTest 不可见（两级门禁没过），跳过 ③④ 音频实测");
  }

  console.log("\n=== 页面报错 ===");
  if(errs.length) errs.slice(0, 12).forEach(e => console.log("  " + e));
  else console.log("（无）");

  /* ---------- 结论 ---------- */
  console.log("\n=== 结论 ===");
  const tone = pageTone ? pageTone.peak : null, osc = rawPeak;

  if(before.playBody === "HIDDEN"){
    console.log("  ✗ 第一级门禁：演奏页被闸门锁住 —— 曲库下拉都点不到，「开始演奏」更不可能。");
    if(gateFix && gateFix.after && gateFix.after.playBody === "shown"){
      console.log("    已确证根因：calibrated=0。掀开后 playBody 立刻可见。");
      console.log("    → 去第 3 步跑一次完整采样并点「保存校准结果」。");
      console.log("      （详见 host/README.md「演奏没声音？先看这一节」）");
    }
    console.log("    ※ 这跟声音无关：板子和音频链路都可能是好的。");
  } else {
    console.log("  ✓ 第一级门禁过了（playBody 可见）。");
  }

  if(before.playBody !== "HIDDEN" && loaded && loaded.midiPanel === "HIDDEN"){
    console.log("  ✗ 第二级门禁：载了曲但 midiPanel 还是没出来 —— 可能曲谱解析失败，");
    console.log("    看页面上的 #midiMsg / #planMsg 提示。");
  } else if(before.playBody !== "HIDDEN" && loaded){
    console.log("  ✓ 第二级门禁过了（载曲后 midiPanel 可见）。");
  }

  if(tone === null){
    if(before.playBody !== "HIDDEN")
      console.log("  !! 测不到页面信号（音频按钮点不到）—— 先解决上面的门禁问题。");
  } else if(tone > 0.01 && (osc === null || osc > 0.01)){
    console.log("  ✓ 音频链路正常：页面的 tone() 真的产生了信号（峰值 " + tone + "）。");
    if(osc !== null) console.log("  ✓ 对照组（裸 oscillator）同样有信号（峰值 " + osc + "）。");
    console.log("    → 听不到声音的话，是**输出设备 / 系统**那边的事，不是页面。");
  } else if(tone <= 0.01 && osc !== null && osc > 0.01){
    console.log("  ✗ 页面 tone() 不出信号，但裸 oscillator 有 —— **页面侧的锅**。");
    console.log("    查 sndOn 勾选 / sndVol 音量 / plan 是否为空（上面 ② 都有读数）。");
  } else if(osc !== null && osc <= 0.01){
    console.log("  ✗ 连裸 oscillator 都没信号 —— 系统 / 浏览器的音频输出有问题，页面无辜。");
  }

  await browser.close();
})().catch(e => { console.error("脚本异常:", e && e.message); process.exit(1); });
