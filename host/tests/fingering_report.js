/* 导出 10 首分级样本的「自动指法表」→ host/samples/FINGERING.md
 *
 * 用法：
 *     node host/tests/fingering_report.js
 *
 * 为什么必须用浏览器跑：
 *     指法是上位机的 buildPlan() 现算的，不是曲子里带的。
 *     如果这里另写一套分配算法来出报告，那报告写一套、演奏时执行另一套，
 *     两边迟早对不上 —— 而且没人会发现。
 *     所以本脚本驱动真实 Chromium 打开调试台，点**页面上的曲库下拉**加载每首曲子，
 *     直接读页面里的 S.plan（就是演奏时用的那个对象）。
 *     代价是慢（要起浏览器），收益是「报告里的指法」和「手套实际执行的指法」
 *     在定义上就是同一份数据。
 *
 * 页面用 file:// 直接打开 —— 曲库是内嵌 base64 的，不需要起 http 服务。
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const PAGE = path.join(ROOT, "web_piano_glove.html");
const OUTM = path.join(ROOT, "samples", "FINGERING.md");
const EXE  = process.env.CHROME_PATH || defaultChrome();

function defaultChrome(){
  const roots = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "ms-playwright"),
    process.env.HOME && path.join(process.env.HOME, ".cache", "ms-playwright"),
  ].filter(Boolean);
  for(const r of roots){
    if(!fs.existsSync(r)) continue;
    for(const d of fs.readdirSync(r).filter(x => x.startsWith("chromium-"))){
      for(const c of [path.join(r, d, "chrome-win64", "chrome.exe"),
                      path.join(r, d, "chrome-linux", "chrome"),
                      path.join(r, d, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium")]){
        if(fs.existsSync(c)) return c;
      }
    }
  }
  throw new Error("找不到 Chromium，请设置 CHROME_PATH 环境变量");
}

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const noteName = n => NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 1);

const pct = (a, b) => b ? (a / b * 100).toFixed(1) + "%" : "—";
const secs = ms => (ms / 1000).toFixed(2) + "s";

/* 把「丢音率」翻译成一句人话。算法已经把接不住的音主动丢了，
   所以丢音率高不代表坏 —— 代表这首曲子对手套来说被简化了。 */
function verdict(rate){
  if(rate <= 0.001) return "完整演奏";
  if(rate <= 0.05) return "基本完整（偶尔掉一两个音）";
  if(rate <= 0.20) return "轻微简化";
  if(rate <= 0.45) return "明显简化（保节奏）";
  return "大幅简化（当作压力测试看）";
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, headless: true });
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));

  await page.goto("file:///" + PAGE.replace(/\\/g, "/"), { waitUntil: "load" });
  await page.waitForTimeout(400);

  const lib = await page.evaluate(() => SONG_LIB.map((s, i) => ({
    i, slug: s.slug, title: s.title, level: s.level, levelName: s.levelName,
    bpm: s.bpm, timesig: s.timesig, notes: s.notes, seconds: s.seconds,
    tests: s.tests, desc: s.desc,
  })));
  const slots = await page.evaluate(() => SLOTS);
  const gloveHz = await page.evaluate(() => GLOVE_MAX_PRESS_HZ);
  const speedMax = await page.evaluate(() => parseInt($("#speed").max, 10));
  console.log("曲库 " + lib.length + " 首：" + lib.map(s => s.slug).join(", "));

  const rows = [];
  for(const song of lib){
    // 走真实的曲库下拉，顺便验证下拉本身能加载
    await page.$eval("#songLib", (el, i) => {
      el.value = String(i);
      el.dispatchEvent(new Event("change"));
    }, song.i);
    await page.waitForTimeout(250);

    const loaded = await page.evaluate(() => (S.midi && S.midi.name) || "");
    if(loaded.indexOf(song.slug) !== 0) throw new Error(
      "曲库第 " + song.i + " 项（" + song.slug + "）没加载成功，当前是 " + loaded);

    const modes = {};
    for(const mode of ["rr", "pitch"]){
      modes[mode] = await page.evaluate(m => {
        $("#selMap").value = m;
        analyze();
        const p = S.plan;
        const ons = p.events.filter(e => e.on);
        return {
          ons: ons.length, dropped: p.dropped, used: p.used, peak: p.peakRate,
          total: ons.length + p.dropped,
          parsed: S.midi.notes.length,
          // 前 20 个音的分配明细（时间会被量化成 0.1s，够看节奏）
          head: ons.slice(0, 20).map(e => ({ t: Math.round(e.t), slot: e.slot, note: e.note })),
          // 音高 → 槽位 的固定映射（音高对应模式下同一音高必落同一手指）
          map: ons.reduce((acc, e) => {
            (acc[e.note] = acc[e.note] || {})[e.slot] = 1;
            return acc;
          }, {}),
        };
      }, mode);
    }
    /* 该曲在「本级建议速度」下实际要发多少命令。
       "越高级越快"必须是数字，不能只是文案 —— 所以这里读的是页面自己
       算出来的那一行提示（同一份 peakRate、同一个速度值），不是另算一套。 */
    const speedInfo = await page.evaluate(() => {
      $("#selMap").value = "rr";
      analyze();
      return {
        pct:  parseInt($("#speed").value, 10),
        max:  parseInt($("#speed").max, 10),
        hint: ($("#speedHint").textContent || "").replace(/\s+/g, " ").trim(),
      };
    });
    const mHz = /约\s*([\d.]+)\s*次按压/.exec(speedInfo.hint);
    speedInfo.pressHz = mHz ? parseFloat(mHz[1]) : 0;

    rows.push({ song, modes, speedInfo });
    console.log("  " + song.slug.padEnd(14) +
      " 音 " + String(song.notes).padStart(3) +
      " | 轮流丢 " + String(modes.rr.dropped).padStart(3) +
      " | 音高丢 " + String(modes.pitch.dropped).padStart(3) +
      " | 峰值 " + String(Math.max(modes.rr.peak, modes.pitch.peak)).padStart(3) + " 条/秒" +
      " | L" + song.level + " " + speedInfo.pct + "% → " + speedInfo.pressHz + " 次按压/秒");
  }

  /* ───────── 生成 Markdown ───────── */
  const L = [];
  const stamp = new Date().toISOString().slice(0, 10);

  L.push("# 自动指法表 · 10 首分级样本");
  L.push("");
  L.push("> **这些曲子的 MIDI 里没有任何指法信息。** 文件里只有「曲名 / 速度 / 拍号 / 音符」，");
  L.push("> 下面这些指法全部是上位机的分配算法在读入时**现场算出来的**——");
  L.push("> 同一首曲子换个分配方式就是另一套指法，曲子本身不用改。");
  L.push(">");
  L.push("> 本文件由 `host/tests/fingering_report.js` 自动导出（" + stamp + "），");
  L.push("> 它驱动真实浏览器跑**页面里那一份** `buildPlan()`，不是另写算法重算的，");
  L.push("> 所以这里写的指法与实际演奏时手套执行的指法**必然是同一份数据**。");
  L.push("> 重新生成：`node host/tests/fingering_report.js`");
  L.push("");
  L.push("## 六根手指");
  L.push("");
  L.push("| 槽位 | 手指 | 角色 |");
  L.push("| --- | --- | --- |");
  const roles = ["拇指侧向按压", "拇指下压", "食指", "中指", "无名指", "小指"];
  slots.forEach((s, i) => L.push("| " + i + " | " + s + " | " + roles[i] + " |"));
  L.push("");
  L.push("> 槽位（slot）是软件里的编号，和舵机 ID 是两回事，映射关系见调试台第 2 页。");
  L.push("");
  L.push("## 两种分配方式");
  L.push("");
  L.push("| 值 | 名字 | 怎么选手指 |");
  L.push("| --- | --- | --- |");
  L.push("| `rr` | 轮流分配（默认） | 谁的活儿先干完谁接下一个音。节奏最完整、手指动得最匀，但同一音高可能换手指 |");
  L.push("| `pitch` | 音高对应 | 低音偏拇指侧、高音偏小指侧。**一个音固定一根手指**，更像真手型 |");
  L.push("");

  L.push("## 总览");
  L.push("");
  L.push("| 级别 | 曲名 | 音符 | 轮流分配 | 音高对应 | 峰值命令 | 结论 |");
  L.push("| --- | --- | ---: | ---: | ---: | ---: | --- |");
  for(const { song, modes } of rows){
    const r = modes.rr, p = modes.pitch;
    const rate = Math.max(r.dropped / r.total, p.dropped / p.total);
    L.push("| L" + song.level + " " + song.levelName + " | " + song.title +
      " | " + song.notes +
      " | 丢 " + r.dropped + "（" + pct(r.dropped, r.total) + "）" +
      " | 丢 " + p.dropped + "（" + pct(p.dropped, p.total) + "）" +
      " | " + Math.max(r.peak, p.peak) + " 条/秒" +
      " | " + verdict(rate) + " |");
  }
  L.push("");
  L.push("**怎么读这张表**：算法只给了手套 6 个自由度，音比手多时它会**主动丢音保节奏**，");
  L.push("绝不会卡住不动。所以「丢音」不是故障，是设计好的降级 —— L1~L3 应当零丢音，");
  L.push("L4 应当极少丢音，L5 就是故意让它丢，用来看固件在超载下会不会被压死。");
  L.push("");

  /* ── 演奏速度分级 ──
     用户要的是「越高级越快、最高级压到极限」。这里就是那张要对账的表：
     级别 → 建议速度 → **实际按压频率**（而不是曲子的原始 BPM）。
     为什么强调"实际按压频率"：不同曲子本身的音符密度差十几倍，
     同一个速度百分比对它们完全不是一回事，只有按压频率能横向比。 */
  L.push("## 演奏速度分级");
  L.push("");
  L.push("曲库每首自带**本级建议速度**，选中即自动套用 —— 级别越高跑得越快。");
  L.push("下表读的是**当前速度下实际要发的动作数**，而不是曲子的原始 BPM：");
  L.push("");
  L.push("| 级别 | 曲名 | 建议速度 | 峰值命令 | 实际按压频率 | 手套上限 " + gloveHz + " 次/秒 |");
  L.push("| --- | --- | ---: | ---: | ---: | --- |");
  for(const { song, modes, speedInfo } of rows){
    const peak = Math.round(Math.max(modes.rr.peak, modes.pitch.peak) * speedInfo.pct / 100);
    const hz   = speedInfo.pressHz;
    const over = hz / gloveHz;
    const rel  = over <= 1
      ? "跟得上"
      : over.toFixed(1) + " 倍（约 " + Math.max(1, Math.round(100 / over)) + "% 的动作发得出）";
    L.push("| L" + song.level + " " + song.levelName + " | " + song.title +
      " | " + speedInfo.pct + "%" +
      " | " + peak + " 条/秒" +
      " | " + hz.toFixed(1) + " 次/秒" +
      " | " + rel + " |");
  }
  L.push("");
  L.push("**怎么读**：一次「按压」= 按下 + 松开 = **两条** `MOVE` 命令；");
  L.push("手套满行程的物理上限是实测的 " + gloveHz + " 次按压/秒（见 docs/design-notes.md 的速度基准）。");
  L.push("L5 的建议速度（200%）是**故意**越过这条线的 —— 它的意义不是「弹得好听」，");
  L.push("而是压力测试：看固件接不住时会不会卡死。正确表现是**主动丢音、保住节奏**。");
  L.push("");
  L.push("⚠️ **「越高级越快」是按倍率说的，不是按绝对频率。** 上面那一列实际频率还受");
  L.push("曲子本身密度影响：卡农每音两拍、24 个音铺满 35 秒，即使给它 L4 的 170%，");
  L.push("绝对频率也只有 1.5 次/秒，比《小星星》的 2 次/秒还低 —— 那是谱子决定的，不是分级没生效。");
  L.push("要比不同级别谁快，看**建议速度**那一列；想看手套被榨到多狠，看**实际按压频率**那一列。");
  L.push("");
  L.push("速度滑块可以手动拖，上限 " + speedMax + "%；旁边的「⚡ 拉满」一键压到顶。");
  L.push("滑块下面那行提示会实时算出「当前速度相当于手套上限的几倍」，");
  L.push("所以「极限在哪」是个看得见的数字，不用凭感觉。");
  L.push("");

  for(const { song, modes } of rows){
    const r = modes.rr, p = modes.pitch;
    L.push("---");
    L.push("");
    L.push("## L" + song.level + " " + song.levelName + " · " + song.title);
    L.push("");
    L.push("- " + song.bpm + " BPM　" + song.timesig[0] + "/" + song.timesig[1] +
      "　" + song.notes + " 个音　" + song.seconds.toFixed(1) + " 秒");
    L.push("- **测试点**：" + song.tests);
    L.push("- " + song.desc);
    L.push("");

    L.push("| 分配方式 | 已分配 | 丢音 | 峰值命令 | 六根手指各动了多少次 |");
    L.push("| --- | ---: | ---: | ---: | --- |");
    for(const [k, label] of [["rr", "轮流分配"], ["pitch", "音高对应"]]){
      const m = modes[k];
      const load = m.used.map((u, i) => slots[i] + " " + u).join(" · ");
      L.push("| " + label + " | " + m.ons + "/" + m.total + " | " + m.dropped +
        "（" + pct(m.dropped, m.total) + "） | " + m.peak + " 条/秒 | " + load + " |");
    }
    L.push("");

    // 音高 → 手指 的固定映射（只有音高对应模式才是固定映射）
    const map = p.map;
    const keys = Object.keys(map).map(Number).sort((a, b) => a - b);
    if(keys.length && keys.length <= 24){
      L.push("**音 → 手指**（音高对应模式，同一音高必落同一根手指）：");
      L.push("");
      L.push("| " + keys.map(k => noteName(k)).join(" | ") + " |");
      L.push("|" + keys.map(() => " --- ").join("|") + "|");
      L.push("| " + keys.map(k => slots[Object.keys(map[k])[0]]).join(" | ") + " |");
      L.push("");
    }else if(keys.length){
      L.push("**音 → 手指**：音域跨 " + keys.length + " 个半音（" +
        noteName(keys[0]) + "~" + noteName(keys[keys.length - 1]) +
        "），6 根手指要覆盖整段音域，一个音高会按邻近关系落到不同手指。");
      L.push("");
    }

    L.push("**开头 20 个音**（轮流分配 / 音高对应）：");
    L.push("");
    L.push("| # | 时间 | 音 | 轮流分配 | 音高对应 |");
    L.push("| ---: | ---: | --- | --- | --- |");
    r.head.forEach((e, i) => {
      const q = p.head[i];
      L.push("| " + (i + 1) + " | " + secs(e.t) + " | " + noteName(e.note) +
        " (" + e.note + ") | " + slots[e.slot] +
        " | " + (q ? slots[q.slot] : "—") + " |");
    });
    L.push("");
  }

  L.push("---");
  L.push("");
  L.push("**自检**：本文件导出时逐首确认了「曲库下拉能加载」，且全程无 JS 报错" +
    (errors.length ? "（✘ 实际有 " + errors.length + " 条报错）" : "（0 条）") + "。");
  L.push("");

  fs.writeFileSync(OUTM, L.join("\n"), "utf8");
  console.log("\n已写入 " + OUTM + "（" + L.length + " 行）");
  if(errors.length){
    console.log("✘ 页面有 JS 报错：" + errors.join(" | "));
    await browser.close();
    process.exit(1);
  }
  await browser.close();
})().catch(e => { console.error("失败：" + e.message); process.exit(1); });
