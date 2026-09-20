/* 演奏时序诊断：把「用户说的抖动」变成数字。
 *
 * 为什么要单独写这个：用户反馈「革命练习曲最快时每个键都抖一下、根本没按下去」。
 * 拍脑袋改参数是不负责任的 —— 先量出「同一根手指两次按下之间到底隔多久」，
 * 再和「舵机走完一次行程需要多久」比，才知道差在哪、差多少。
 *
 * 用法：
 *   node diag_timing.js                          默认连 127.0.0.1:8123，跑几首代表曲
 *   node diag_timing.js revolutionary moonlight 只跑指定 slug
 *   URL=http://127.0.0.1:9000 node diag_timing.js
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

/* 在页面里把 S.plan 的时序摊开算。
   注意 loadMidiFile 是异步的，选曲后必须等一下再读 S.plan，
   否则读到的是上一首的数据。 */
const PROBE = async (job) => {
  const { slug, stroke } = job;
  const idx = SONG_LIB.findIndex(s => s.slug === slug);
  if(idx < 0) return { error: "曲库里没有 " + slug };

  if(stroke){
    const el = document.querySelector("#fStroke");
    el.value = String(stroke);
    el.dispatchEvent(new Event("input"));
  }

  const sel = document.querySelector("#songLib");
  sel.value = String(idx);
  sel.dispatchEvent(new Event("change"));
  await new Promise(r => setTimeout(r, 450));
  if(!S.plan) return { error: "等不到 plan" };

  const p = S.plan;
  const sp = curSpeed();
  const k  = sp;

  const onsBySlot = Array.from({ length: 6 }, () => []);
  p.events.forEach(e => { if(e.on) onsBySlot[e.slot].push(e); });

  /* 同一根手指：相邻两次「按下」之间隔多久（真实时间 = 曲谱 / 速度） */
  const rep = [];
  onsBySlot.forEach(list => {
    for(let i = 1; i < list.length; i++) rep.push(list[i].t - list[i - 1].t);
  });
  rep.sort((a, b) => a - b);
  const q = (arr, f) => arr.length ? arr[Math.min(arr.length - 1, Math.floor(arr.length * f))] : null;

  /* 按住时长：曲谱域和真实域都要看 —— 事件按曲谱排，物理按真实算 */
  const onEv = p.events.filter(e => e.on);
  const holdsScore = onEv.map(e => e.durMs).sort((a, b) => a - b);
  const holdsReal  = onEv.map(e => e.holdReal).sort((a, b) => a - b);

  /* 动作档位分布：真实时间下每根手指各按了多少次、平均隔多久 */
  const perSlot = onsBySlot.map((l, s) => {
    let span = 0;
    for(let i = 1; i < l.length; i++) span += l[i].t - l[i - 1].t;
    return { slot: s, n: l.length, avgGapReal: l.length > 1 ? span / (l.length - 1) / k : null };
  });

  return {
    slug, title: SONG_LIB[idx].title, level: SONG_LIB[idx].level, speed: sp,
    stroke: p.stroke,
    notes: (S.notes || []).length,
    events: p.events.length,
    dropped: (p.droppedNotes || []).length,
    peakRate: p.peakRate,
    repeatReal: {
      min: rep.length ? rep[0] / k : null,
      p05: rep.length ? q(rep, 0.05) / k : null,
      median: rep.length ? q(rep, 0.5) / k : null
    },
    holdReal: { min: holdsReal[0], median: q(holdsReal, 0.5), max: holdsReal[holdsReal.length - 1] },
    holdScore: { min: holdsScore[0], median: q(holdsScore, 0.5), max: holdsScore[holdsScore.length - 1] },
    perSlot,
    /* 「按不到底」的音有多少个：真实按住时长 < 行程时间，舵机根本走不完 */
    tooShort: holdsReal.filter(h => h < p.stroke - 0.5).length
  };
};

(async () => {
  const browser = await chromium.launch({ executablePath: findChrome(), args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 950 } });
  const errs = [];
  page.on("pageerror", e => errs.push(String(e)));

  await page.goto(BASE + "/web_piano_glove.html?sim=1", { waitUntil: "load" });
  await page.waitForTimeout(500);

  const slugs = process.argv.slice(2);
  const list = slugs.length ? slugs
    : ["twinkle", "jingle-bells", "fur-elise", "canon", "moonlight", "revolutionary"];

  console.log("=== 演奏时序诊断（真实浏览器，模拟固件）===");
  for(const slug of list){
    const r = await page.evaluate(PROBE, { slug });
    if(r.error){ console.log("\n[" + slug + "] " + r.error); continue; }

    console.log("\n──── " + r.title + "（" + slug + "，L" + r.level +
                "，速度 " + Math.round(r.speed * 100) + "%）────");
    console.log("  音符 " + r.notes + " 个 → 事件 " + r.events + " 条；手套按不了 " + r.dropped + " 个");
    console.log("  行程时间设定 " + r.stroke + "ms；按住比行程还短的音：" + r.tooShort + " 个" +
                (r.tooShort ? "  ← 这些会「抖一下」" : "  ✓"));
    console.log("  按住时长 真实 " + Math.round(r.holdReal.min) + "~" + Math.round(r.holdReal.max) +
                "ms（中位 " + Math.round(r.holdReal.median) + "ms）" +
                " ｜ 曲谱 " + Math.round(r.holdScore.min) + "~" + Math.round(r.holdScore.max) + "ms");
    console.log("  同手指相邻按下 真实：最小 " + Math.round(r.repeatReal.min) +
                "ms / p05 " + Math.round(r.repeatReal.p05) +
                "ms / 中位 " + Math.round(r.repeatReal.median) + "ms");
    console.log("  各手指： " + r.perSlot.map(s =>
      "槽" + s.slot + "=" + s.n + "次" + (s.avgGapReal ? "(均隔" + Math.round(s.avgGapReal) + "ms)" : "")
    ).join("  "));
  }

  /* 行程时间扫描：告诉用户这个旋钮该拧到哪 */
  console.log("\n=== 行程时间扫描（革命练习曲 @ 当前速度）===");
  console.log("  行程    丢音    按键不到底的音");
  for(const s of [50, 70, 90, 120, 160, 200]){
    const r = await page.evaluate(PROBE, { slug: "revolutionary", stroke: s });
    if(r.error){ console.log("  " + r.error); break; }
    console.log("  " + String(s).padStart(4) + "ms  " + String(r.dropped).padStart(4) +
                "     " + String(r.tooShort).padStart(4));
  }

  console.log("\n=== JS 错误 ===");
  if(errs.length) errs.forEach(e => console.log("  " + e)); else console.log("  无");
  await browser.close();
})().catch(e => { console.error("诊断脚本本身出错：" + e.message); process.exit(1); });
