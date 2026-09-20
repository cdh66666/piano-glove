/* 音频输出延迟诊断：量「从代码决定发声 → 真正听到」这段固定延迟有多长。
 *
 * 为什么要单独写这个：用户反馈「舵机按下去，声音要过一会才响，
 * 没有那种声音是从手指按下触发的感觉」。这不是时序漂移（不是越拖越慢），
 * 而是音频链本身的**固定**延迟 —— WebAudio 的 ctx.currentTime 到真正出声，
 * 中间还要过 baseLatency（渲染送出）+ outputLatency（设备缓冲）。
 * 舵机命令几乎不等，于是听觉整体落在视觉后面，差多少就是这个数。
 *
 * 页面的补偿逻辑在 audioLeadMs()，它读的正是这两个值。
 * 换了声卡 / 插上蓝牙耳机之后想知道"现在该补多少"，跑这个。
 *
 * 用法：
 *   node diag_audio.js             无头跑（数值仍然准，只是没有真实输出设备）
 *   HEADED=1 node diag_audio.js    开真窗口 —— 有真实声卡时才完全作数
 *   URL=http://127.0.0.1:9000 node diag_audio.js
 */
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const BASE = process.env.URL || "http://127.0.0.1:8123";

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

const PROBE = async () => {
  const ctx = audioCtx();
  if(!ctx) return { error: "这个浏览器没有 Web Audio" };
  try{ if(ctx.state === "suspended") await ctx.resume(); }catch(e){}
  /* 跑一次试听，确保这条链路真的被启用过（和用户点「试听一下」等价） */
  try{ sndTest(); }catch(e){}
  await new Promise(r => setTimeout(r, 900));
  try{ if(ctx.state === "suspended") await ctx.resume(); }catch(e){}
  await new Promise(r => setTimeout(r, 300));

  /* 音频钟 vs 墙钟采样：看两者是否同速（不同速说明时钟有问题，另说） */
  const pairs = [];
  for(let i = 0; i < 16; i++){
    pairs.push({ w: performance.now() / 1000, c: ctx.currentTime });
    await new Promise(r => setTimeout(r, 45));
  }
  const A = pairs[0], B = pairs[pairs.length - 1];
  const wallSpan = B.w - A.w, ctxSpan = B.c - A.c;

  return {
    state: ctx.state,
    sampleRate: ctx.sampleRate,
    baseLatency: ctx.baseLatency || 0,
    outputLatency: ctx.outputLatency === undefined ? null : ctx.outputLatency,
    latencyHint: ctx.latencyHint,
    rateRatio: wallSpan ? ctxSpan / wallSpan : null,
    /* 页面实际会补多少（含 tone() 里那 10ms 调度提前量 + 用户微调） */
    pageLead: audioLeadMs(),
    toneLead: TONE_LEAD_MS,
    liveOsc: SND.live.length
  };
};

(async () => {
  const headed = !!process.env.HEADED;
  const browser = await chromium.launch({
    executablePath: findChrome(),
    headless: !headed,
    args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required"]
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 950 } });
  await page.goto(BASE + "/web_piano_glove.html?sim=1", { waitUntil: "load" });
  await page.waitForTimeout(700);
  const r = await page.evaluate(PROBE);

  console.log("=== 音频输出延迟诊断" + (headed ? "（有头，真实声卡）" : "（无头）") + " ===");
  if(r.error){
    console.log("  " + r.error);
  }else{
    const ms = v => (v * 1000).toFixed(1) + " ms";
    console.log("  AudioContext 状态 : " + r.state + "　采样率 " + r.sampleRate + "Hz");
    console.log("  latencyHint       : " + r.latencyHint);
    console.log("  baseLatency       : " + ms(r.baseLatency) + "　（渲染 → 送出）");
    console.log("  outputLatency     : " + (r.outputLatency === null ? "（这个内核不报）"
                                    : ms(r.outputLatency) + "　（设备缓冲）"));
    console.log("  音频钟/墙钟 速率比: " + (r.rateRatio === null ? "—" : r.rateRatio.toFixed(4))
                + (r.rateRatio === null || Math.abs(r.rateRatio - 1) < 0.05 ? "" : "  ← 时钟不同速，另查"));
    console.log("  ─────────────────────────────────────────");
    console.log("  从代码决定发声 → 耳朵听到 ≈ " + (r.pageLead) + " ms");
    console.log("     （页面就按这个数把声音提前提交，见页面 audioLeadMs()）");
    console.log("     其中 tone() 自带的调度提前量 " + r.toneLead + " ms");
    console.log("  残留振荡器        : " + r.liveOsc + "（应接近 0，说明 onended 在清理）");
    console.log("  ─────────────────────────────────────────");
    console.log("  如果耳朵听到的比动作还晚，就在页面上把「音画对齐」往右调；");
    console.log("  觉得声音抢在动作前头了，就往左调。");
  }
  await browser.close();
})().catch(e => { console.error("诊断脚本本身出错：" + e.message); process.exit(1); });
