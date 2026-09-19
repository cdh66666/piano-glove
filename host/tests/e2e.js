/* 钢琴手套调试台 · 端到端自测（模拟固件，无需硬件） */
const { chromium } = require("playwright-core");
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT  = path.join(__dirname, "shots");
const EXE  = process.env.CHROME_PATH || defaultChrome();

function defaultChrome(){
  const roots = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "ms-playwright"),
    process.env.HOME && path.join(process.env.HOME, ".cache", "ms-playwright"),
    "/root/.cache/ms-playwright"
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

const PORT = 8137;

fs.mkdirSync(OUT, { recursive: true });
const MIME = { ".html":"text/html; charset=utf-8", ".js":"text/javascript", ".css":"text/css", ".mid":"audio/midi" };

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split("?")[0]);
  if(p === "/") p = "/web_piano_glove.html";
  const f = path.join(ROOT, p);
  if(!fs.existsSync(f) || fs.statSync(f).isDirectory()){ res.writeHead(404); return res.end("nope"); }
  res.writeHead(200, { "Content-Type": MIME[path.extname(f)] || "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
});

const errors = [];
const logs = [];
let failures = 0;
let checks = 0;
function check(name, cond, extra){
  const tag = cond ? "  PASS" : "  FAIL";
  checks++;
  if(!cond) failures++;
  console.log(tag + "  " + name + (extra !== undefined ? "   [" + extra + "]" : ""));
}

/* 扫出 MIDI 文件里所有 meta 事件类型。用来**机器验证**「样本不含指法信息」——
   这件事不能靠人眼看：指法在 MIDI 里最常见的藏身处是 Text（0x01）和歌词（0x05），
   人打开播放器根本看不出来，但解析器读得到。
   只允许：0x03 曲名 / 0x51 速度 / 0x58 拍号 / 0x2F 结束。 */
const META_ALLOWED = [0x03, 0x51, 0x58, 0x2f];
function metaKinds(buf){
  const kinds = new Set();
  let p = 14;                                   // 跳过 MThd
  while(p + 8 <= buf.length && buf.toString("latin1", p, p + 4) === "MTrk"){
    const size = buf.readUInt32BE(p + 4);
    const end = Math.min(p + 8 + size, buf.length);
    p += 8;
    let running = null;
    const readVlq = () => { let v = 0, b; do { b = buf[p++]; v = (v << 7) | (b & 0x7f); } while(b & 0x80); return v; };
    while(p < end){
      readVlq();                                // delta
      let st = buf[p];
      if(st & 0x80){ p++; running = st; } else st = running;
      if(st === 0xff){
        kinds.add(buf[p++]);
        /* ⚠️ 这里必须拆成两步，不能写 `p += readVlq()`。
           JS 的 `+=` 会先取 p 的旧值，再求右边：readVlq 内部已经把 p 推进了
           「长度字段自身占的字节数」，但返回值只是长度值，于是 p 少前进 1~2 字节。
           每读一个 meta 就错位一点，最后把 EndOfTrack 的 0x2F 读成了数据字节
           （现象：扫出 meta 0x00、却扫不到 0x2F）。短文件错位后可能碰巧再对上，
           长的就露馅 —— 这类 bug 靠肉眼是看不出来的。 */
        const len = readVlq();
        p += len;
      }else if(st === 0xf0 || st === 0xf7){
        const len = readVlq();
        p += len;
      }else if(st === 0xc0 || st === 0xd0) p += 1;
      else p += 2;
    }
    p = end;
  }
  return [...kinds];
}

(async () => {
  await new Promise(r => server.listen(PORT, "127.0.0.1", r));
  const browser = await chromium.launch({ executablePath: EXE, headless: true });
  const page = await browser.newPage({ viewport: { width: 430, height: 900 }, deviceScaleFactor: 2 });

  page.on("pageerror", e => errors.push("pageerror: " + e.message));
  page.on("console", m => { logs.push(m.type() + ": " + m.text());
    if(m.type() === "error") errors.push("console.error: " + m.text()); });

  await page.goto(`http://127.0.0.1:${PORT}/web_piano_glove.html`, { waitUntil: "load" });
  await page.waitForTimeout(400);

  const txt = s => page.textContent(s);
  const click = async s => { await page.click(s); };
  const shot = n => page.screenshot({ path: path.join(OUT, n + ".png"), fullPage: true });

  /* ---------- 0. 初始 ---------- */
  console.log("\n=== 0. 初始加载 ===");
  check("页面标题正确", (await page.title()).includes("钢琴手套"));
  check("6 个页面节点存在", (await page.$$(".page")).length === 6, (await page.$$(".page")).length);
  check("底部导航 6 个按钮", (await page.$$("#tabbar button")).length === 6);
  check("默认停在连接页", await page.isVisible("#p-connect.active"));
  await click('#tabbar button[data-p="assign"]');
  await page.waitForTimeout(150);
  check("未连接时后续页面被闸门挡住", await page.isVisible("#assignGate") && !(await page.isVisible("#assignBody")));
  await click('#tabbar button[data-p="connect"]');
  await page.waitForTimeout(150);
  check("顶栏显示未连接", (await txt("#cConn")).includes("未连接"));
  await shot("01-connect");

  /* ---------- 1. 连接 ---------- */
  console.log("\n=== 1. 连接（模拟模式） ===");
  await click("#btnConn");
  await page.waitForTimeout(700);
  check("连接成功提示", (await txt("#connMsg")).includes("已连接"), await txt("#connMsg"));
  check("顶栏变为已连接", (await txt("#cConn")).includes("已连接"));
  await click('#tabbar button[data-p="assign"]');
  await page.waitForTimeout(150);
  check("闸门打开（编号页可见）", await page.isVisible("#assignBody") && !(await page.isVisible("#assignGate")));
  await click('#tabbar button[data-p="connect"]');
  await page.waitForTimeout(150);
  check("INFO 已读取", (await txt("#infoKv")).includes("PIANO_GLOVE_2"), (await txt("#infoKv")).slice(0, 60));
  check("初始档位是 SC09（与真板一致）", (await txt("#infoKv")).includes("SC09"));
  await click("#btnProfile");
  await page.waitForTimeout(500);
  check("切档后为 STS3032", (await txt("#infoKv")).includes("STS3032"));
  await shot("02-connected");

  /* ---------- 2. 编号 6 轮 ---------- */
  console.log("\n=== 2. 舵机编号（6 轮） ===");
  await click('#tabbar button[data-p="assign"]');
  await page.waitForTimeout(200);
  check("切到编号页", await page.isVisible("#p-assign.active"));

  const assignRound = async (round, first) => {
    if(!first){                                   // 先确认总线已空
      await click("#btnSimUnplug");
      await click("#btnDetect");  await page.waitForTimeout(900);
      const m = await txt("#assignMsg");
      if(!m.includes("总线是空的")) console.log("    轮次" + round + " 拔下确认异常: " + m);
      await click("#btnSimPlug");
    }
    await click("#btnDetect");   await page.waitForTimeout(900);
    const before = await txt("#assignMsg");
    const ready = await page.isEnabled("#btnAssignNext");
    check("第 " + round + " 轮检测到舵机并可改号", ready, before.slice(0, 46));
    await click("#btnAssignNext"); await page.waitForTimeout(1500);
    const after = await txt("#assignMsg");
    check("第 " + round + " 轮编号成功", after.includes("✔"), after.slice(0, 56));
  };
  for(let i = 0; i < 6; i++) await assignRound(i + 1, i === 0);

  const dots = await page.$$eval("#assignDots .dot", els => els.map(e => e.className));
  check("6 个进度点全部 done", dots.filter(c => c.includes("done")).length === 6, dots.join("|"));
  check("编号完成后按钮禁用", await page.isDisabled("#btnDetect"));
  check("顶栏显示 1/6 徽标已清空", (await txt("#bAssign")) === "", "badge=" + (await txt("#bAssign")));

  /* ★ 关键回归：编号跑完之后，槽位 -> 舵机 ID 的映射必须是 1..6。
     这一条曾经是假的：
       - cur===target 时上位机一个字节都不发（映射没写）；
       - 改号时固件走 remapId(old,new)，把**已编好的槽位**一起改了。
     因为每轮插上的出厂舵机号都是 1，第 2 轮就把槽位 0 一起改成 2，
     6 轮跑完得到 [2,2,3,4,5,6] —— 界面照样显示"编号全部完成"，
     但实机上 1 号舵机永远不动、槽位 0/1 抢同一块。
     所以这里不看界面文案，直接查固件里的真实映射。 */
  const slotIds = await page.evaluate(async () => {
    const lines = await T.send("STATUS_ALL", 5000);
    return lines.filter(l => l.startsWith("SLOT "))
                .map(l => +(l.match(/ id=(\d+)/) || [0, 0])[1]);
  });
  check("编号后槽位映射 = 1..6", slotIds.join(",") === "1,2,3,4,5,6", "[" + slotIds.join(",") + "]");
  await shot("03-assign-done");

  // 回归：死循环修复 —— 编完号不拔，再检测应给出明确「请拔下来」而不是反复刷
  await click("#btnResetWiz"); await page.waitForTimeout(200);
  await click("#btnDetect");  await page.waitForTimeout(900);
  const again = await txt("#assignMsg");
  check("重置后能重新检测（不卡死）", again.length > 0, again.slice(0, 40));

  /* ---------- 3. 校准 ---------- */
  console.log("\n=== 3. 校准 ===");
  await click('#tabbar button[data-p="cal"]');
  await page.waitForTimeout(200);
  check("切到校准页", await page.isVisible("#p-cal.active"));
  check("模拟模式显示「接回总线」按钮", await page.isVisible("#btnSimBus"));
  await click("#btnSimBus");
  await click("#btnStatusAll"); await page.waitForTimeout(700);
  check("6 个舵机全部在线", (await txt("#statusMsg")).includes("全部在线"), await txt("#statusMsg"));
  await shot("04-cal-slots");

  await page.fill("#calSecs", "5");
  await click("#btnCalStart");
  await page.waitForTimeout(1000);
  check("校准已启动(无 ERR)", !(await txt("#calMsg")).includes("失败"), await txt("#calMsg"));
  // 校准前 ARM 应被拒绝
  await click('#tabbar button[data-p="test"]');
  await page.waitForTimeout(200);
  check("未校准时试动作页被挡住", await page.isVisible("#testGate"));
  await click('#tabbar button[data-p="cal"]');
  await page.waitForTimeout(6500);
  check("采样结束提示保存", (await txt("#calMsg")).includes("采样结束"), await txt("#calMsg"));
  check("保存按钮已启用", await page.isEnabled("#btnCalSave"));
  await click("#btnCalSave"); await page.waitForTimeout(900);
  check("校准保存成功", (await txt("#calMsg")).includes("校准已保存"), await txt("#calMsg"));
  check("顶栏显示已校准", (await txt("#cCal")).includes("已校准"), await txt("#cCal"));
  await shot("05-cal-done");

  /* 回归：静止位必须落在「松开端」。
     曾经 autoFinish() 把 standby 写成 (min+max)/2 量程中点 ——
     于是 pressPos 只从"中点"走到"按下端"，按下幅度正好只有校准行程的一半，
     用户看到的就是"怎么幅度这么小，要用我校准的最大幅度来啊"。
     这里同样不看界面文案，直接读固件的校准表来判。 */
  const calTbl = await page.evaluate(async () => {
    const lines = await T.send("CAL STATUS", 5000);
    return lines.filter(l => l.startsWith("CAL slot")).map(l => {
      const m = {}; l.replace(/(\w+)=(\S+)/g, (_, k, v) => (m[k] = v));
      return {slot: +m.slot, min: +m.min, standby: +m.standby, max: +m.max, press: m.press};
    });
  });
  const relEnd = c => (c.press === "min") ? c.max : c.min;    // 松开端
  const hitEnd = c => (c.press === "min") ? c.min : c.max;    // 按下端
  check("静止位落在松开端（不是量程中点）",
    calTbl.length === 6 && calTbl.every(c => Math.abs(c.standby - relEnd(c)) <= Math.abs(c.max - c.min) / 4),
    calTbl.map(c => c.slot + ":" + c.standby + "→" + relEnd(c)).join(" "));
  check("按压行程 ≈ 整个校准量程",
    calTbl.length === 6 && calTbl.every(c => {
      const span = Math.abs(c.max - c.min);
      return span === 0 || Math.abs(hitEnd(c) - c.standby) >= span * 0.75;
    }),
    calTbl.map(c => c.slot + ":" + Math.abs(hitEnd(c) - c.standby) + "/" + Math.abs(c.max - c.min)).join(" "));

  // CAL ALIGN：校准本来就对的时候，应当一个槽位都不改（fixed_mask=0x00）
  const alignLine = await page.evaluate(async () => {
    const r = await T.send("CAL ALIGN", 5000);
    return (r || []).find(l => l.startsWith("OK CAL ALIGN")) || "";
  });
  check("CAL ALIGN 可用且无需改动", /fixed_mask=0x0+\b/.test(alignLine), alignLine || "(无回复)");

  /* ---------- 4. 试动作 ---------- */
  console.log("\n=== 4. 试动作 ===");
  await click('#tabbar button[data-p="test"]');
  await page.waitForTimeout(300);
  check("校准后试动作页开放", await page.isVisible("#testBody"));
  await click("#btnArm"); await page.waitForTimeout(600);
  check("ARM 成功", (await txt("#armMsg")).includes("已使能"), await txt("#armMsg"));
  check("顶栏显示已使能", (await txt("#cArm")).includes("已使能"));
  await click('#testBody2 button[data-press="0"]');
  await page.waitForTimeout(900);
  check("单指测试按钮恢复可用", await page.isEnabled('#testBody2 button[data-press="0"]'));
  await shot("06-test");

  /* 回归：MOVE 越界必须被拒。
     界面上的「测动作往返」曾经硬编码 `MOVE 1 200`，而那块舵机校准出来的区间
     可能是 [2091, 2600] —— 200 远在界外，舵机一路顶过去顶死在那儿，
     用户的原话是"转到不该转到的地方卡住"。
     现在 MOVE 会先查该槽位的校准区间。 */
  const guard = await page.evaluate(async () => {
    const st = await T.send("STATUS_ALL", 5000);
    const m = {};
    (st.find(l => l.startsWith("SLOT slot=0")) || "").replace(/(\w+)=(\S+)/g, (_, k, v) => (m[k] = v));
    const id = +m.id;
    const lo = Math.min(+m.min, +m.max), hi = Math.max(+m.min, +m.max);
    // 挑一个一定落在区间外的位置
    const outPos = (lo >= 500) ? (lo - 500) : Math.min(4095, hi + 500);
    const bad  = await T.send("MOVE " + id + " " + outPos, 4000);
    const good = await T.send("MOVE " + id + " " + Math.round((lo + hi) / 2), 4000);
    return {id, lo, hi, outPos, bad: bad.join(" | "), good: good.join(" | ")};
  });
  check("MOVE 越界被拒绝（目标在区间外）", /out_of_cal_range/.test(guard.bad),
    "id=" + guard.id + " pos=" + guard.outPos + " 区间=" + guard.lo + ".." + guard.hi + " → " + guard.bad.slice(0, 70));
  check("MOVE 区间内放行", /OK MOVE/.test(guard.good), guard.good.slice(0, 70));

  /* ---------- 4B. 响应延迟实测 ---------- */
  console.log("\n=== 4B. 响应延迟实测 ===");
  check("延迟卡闸门已开", await page.isVisible("#latBody"));
  await click("#btnLatPing");
  await page.waitForTimeout(3500);
  check("PING 测出结果表", await page.isVisible("#latResult"));
  check("PING 结果出现 1 块", (await page.$$("#latList .latitem")).length === 1, (await page.$$("#latList .latitem")).length);
  check("结果里给出延迟与上限", /\d+ ms/.test(await txt("#latList")) && (await txt("#latList")).includes("条/秒"), (await txt("#latList")).replace(/\s+/g, " ").slice(0, 70));
  check("结论点明是模拟模式（数字不可信）", (await txt("#latVerdict")).includes("模拟模式"), (await txt("#latVerdict")).slice(0, 40));

  await click("#btnLatMove");
  await page.waitForTimeout(3500);
  check("动作往返测试追加一块", (await page.$$("#latList .latitem")).length === 2, (await page.$$("#latList .latitem")).length);
  // 回归：② 绝不能再发 MOVE。它必须走 PRESS/RELEASE ——
  // 固件按校准表算出两个端点，天然不会越界；而硬编码 MOVE 1 200 会让舵机顶死。
  const latTxt = await txt("#latList");
  check("动作往返走的是 PRESS/RELEASE（不是 MOVE）",
    /PRESS\/RELEASE/.test(latTxt) && !/MOVE/.test(latTxt), latTxt.replace(/\s+/g, " ").slice(0, 70));

  await click("#btnLatBurst");
  await page.waitForTimeout(4500);
  check("压测追加一块", (await page.$$("#latList .latitem")).length === 3, (await page.$$("#latList .latitem")).length);
  check("压测后串口仍存活", (await txt("#latList")).includes("PING 通"), (await txt("#latList")).replace(/\s+/g, " ").slice(-70));
  check("按钮测完都恢复可用",
    (await page.isEnabled("#btnLatPing")) && (await page.isEnabled("#btnLatMove")) && (await page.isEnabled("#btnLatBurst")));
  const latW = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  check("延迟结果不撑破页面（无横向溢出）", latW[0] <= latW[1] + 1, latW.join(" / "));
  await shot("06b-latency");

  /* ---------- 4C. 速度实测 ---------- */
  console.log("\n=== 4C. 速度实测 ===");
  check("测速卡闸门已开", await page.isVisible("#rtBody"));
  check("6 个槽位按钮默认全选",
    (await page.$$eval("#rtDots .dot", e => e.filter(x => x.className.includes("cur")).length)) === 6);
  check("默认提示已选 6 根", (await txt("#rtPick")).includes("已选 6"), await txt("#rtPick"));

  // 取消一根 -> 计数要跟着变
  await click("#rtDots .dot:nth-child(3)");
  await page.waitForTimeout(120);
  check("取消一根后变 5 根", (await txt("#rtPick")).includes("5 根"), await txt("#rtPick"));
  // 全不选 -> 按钮禁用（防止发出空掩码）
  await click("#rtNone");
  await page.waitForTimeout(120);
  check("全不选时开始按钮禁用", await page.isDisabled("#btnRate"));
  await click("#rtAll");
  await page.waitForTimeout(120);
  check("全选后可再次开始", await page.isEnabled("#btnRate"));

  // 掩码必须以 0x 十六进制发出：十进制 63 会被固件当成非法槽位
  const rateCmd = await page.evaluate(() => {
    const s = [];
    const old = T.send.bind(T);
    T.send = (cmd, t) => { s.push(cmd); return old(cmd, t); };
    return new Promise(res => {
      $("#btnRate").click();
      setTimeout(() => { T.send = old; res(s.find(c => c.startsWith("RATE ")) || ""); }, 200);
    });
  });
  check("RATE 掩码发成 0x 十六进制", /^RATE 0x3F /.test(rateCmd), rateCmd || "(没发出去)");

  await page.waitForTimeout(3500);
  check("速度实测出了结果块", await page.isVisible("#rtResult"));
  const rtTxt = await txt("#rtResult");
  check("结果含完整行程耗时", /ms/.test(rtTxt) && rtTxt.includes("一趟完整行程"), rtTxt.replace(/\s+/g, " ").slice(0, 70));
  check("结果含实测 Hz", /Hz/.test(rtTxt), rtTxt.replace(/\s+/g, " ").slice(0, 70));
  check("给了能不能达到目标的结论",
    /达到 6 Hz|过了 4 Hz|连 4 Hz 都不到|等满 800 ms/.test(rtTxt), rtTxt.replace(/\s+/g, " ").slice(-90));

  // 行程调小 -> 测出来应该更快（模拟固件的物理模型）
  const hzOf = t => parseFloat((t.match(/([\d.]+) Hz/) || [0, 0])[1]);
  const hz100 = hzOf(rtTxt);
  await page.$eval("#rtDepth", e => { e.value = "40"; e.dispatchEvent(new Event("input")); });
  await page.waitForTimeout(150);
  check("行程标签跟着变", (await txt("#rtDepthL")) === "40%", await txt("#rtDepthL"));
  await click("#btnRate");
  await page.waitForTimeout(3500);
  const hz40 = hzOf(await txt("#rtResult"));
  check("行程减半后实测频率变高", hz40 > hz100, hz100 + " Hz -> " + hz40 + " Hz");

  check("测完按钮恢复可用", await page.isEnabled("#btnRate") && await page.isDisabled("#btnRateStop"));
  await shot("06c-rate");

  /* ---------- 5. 演奏 ---------- */
  console.log("\n=== 5. MIDI 演奏 ===");
  await click('#tabbar button[data-p="play"]');
  await page.waitForTimeout(300);
  check("校准后演奏页开放", await page.isVisible("#playBody"));

  /* ---------- 5a. 曲库：10 首分级样本 ----------
     三个承诺必须机器验证，不能靠"生成的时候看过一眼"：
       ① 样本里**没有指法信息**（指法由 buildPlan 现算）；
       ② 网页内嵌的曲库与磁盘上的 .mid 是同一份字节；
       ③ 曲库清单和 samples/ 目录不会各说各话。 */
  console.log("\n=== 5a. 曲库（10 首分级样本）===");

  const lib = await page.evaluate(() => SONG_LIB.map(s =>
    ({ slug: s.slug, level: s.level, notes: s.notes, b64: s.b64 })));
  check("曲库 10 首", lib.length === 10, lib.length + " 首");

  const sampleDir = path.join(ROOT, "samples");
  const cat = JSON.parse(fs.readFileSync(path.join(sampleDir, "catalog.json"), "utf8"));
  const onDisk = fs.readdirSync(sampleDir)
    .filter(f => f.endsWith(".mid") && f !== "two-tigers.mid")
    .map(f => f.replace(/\.mid$/, "")).sort();
  check("曲库清单与 samples/ 目录一一对应",
    JSON.stringify(lib.map(s => s.slug).sort()) === JSON.stringify(onDisk),
    "网页 " + lib.length + " 首 / 磁盘 " + onDisk.length + " 首");

  const lvCount = {};
  lib.forEach(s => { lvCount[s.level] = (lvCount[s.level] || 0) + 1; });
  check("L1~L5 每级正好两首",
    [1, 2, 3, 4, 5].every(l => lvCount[l] === 2), JSON.stringify(lvCount));

  let sameBytes = 0;
  const metaBad = [];
  for(const s of lib){
    const disk = fs.readFileSync(path.join(sampleDir, s.slug + ".mid"));
    if(Buffer.from(s.b64, "base64").equals(disk)) sameBytes++;
    const bad = metaKinds(disk).filter(k => !META_ALLOWED.includes(k));
    if(bad.length) metaBad.push(s.slug + ":0x" + bad.map(x => x.toString(16)).join(","));
  }
  check("内嵌曲库与磁盘 .mid 逐字节一致", sameBytes === lib.length,
    sameBytes + "/" + lib.length);
  check("样本不含任何指法 meta（只允许 曲名/速度/拍号/结束）",
    metaBad.length === 0, metaBad.length ? metaBad.join(" ") : "10/10 干净");

  // 逐首从下拉加载，确认解析出的音符数和 catalog 对得上
  const loaded = [];
  for(let i = 0; i < lib.length; i++){
    await page.$eval("#songLib", (el, k) => {
      el.value = String(k); el.dispatchEvent(new Event("change"));
    }, i);
    await page.waitForTimeout(180);
    loaded.push(await page.evaluate(() => ({
      name: (S.midi && S.midi.name) || "", got: S.midi ? S.midi.notes.length : -1 })));
  }
  const miss = loaded.filter((r, i) => r.name !== lib[i].slug + ".mid").map(r => r.name || "(空)");
  check("10 首都能从曲库下拉加载", miss.length === 0, miss.length ? miss.join(",") : "全部命中");
  const mismatch = loaded.filter((r, i) => r.got !== cat.songs[i].notes);
  check("解析出的音符数与 catalog.json 一致", mismatch.length === 0,
    mismatch.length ? mismatch.map((r, i) => r.got).join(",") : "10/10 一致");

  /* 音高对应模式：音域窄的曲子也要把 6 个槽位用满。
     这条是**回归测试** —— 曾经 hi 兜底到 72、want 用 floor(ratio*6)，
     《小星星》的 C D E F G A 只占满 4 根手指（E/F 挤在食指、小指全程闲着），
     而这首曲子当初被选进来的理由恰恰是「6 个音 = 6 根手指」。 */
  const star = await page.evaluate(() => {
    const sel = document.querySelector("#songLib");
    sel.value = "0";
    sel.dispatchEvent(new Event("change"));
    return new Promise(res => setTimeout(() => {
      document.querySelector("#selMap").value = "pitch";
      analyze();
      const map = {};
      S.plan.events.filter(e => e.on).forEach(e => { map[e.note] = e.slot; });
      res({ used: S.plan.used, map });
    }, 300));
  });
  check("音高对应：6 个音的曲子用满 6 根手指",
    star.used.length === 6 && star.used.every(v => v > 0), JSON.stringify(star.used));
  const pitches = Object.keys(star.map).map(Number).sort((a, b) => a - b);
  check("音高对应：音越高、手指越靠小指侧",
    pitches.every((n, i) => i === 0 || star.map[n] >= star.map[pitches[i - 1]]),
    JSON.stringify(star.map));
  await page.evaluate(() => { document.querySelector("#selMap").value = "rr"; analyze(); });

  // 内置示例：《两只老虎》—— 不选文件也应该能一键加载
  await click("#btnSample");
  await page.waitForTimeout(700);
  check("内置示例可以一键加载", (await txt("#midiMsg")).includes("两只老虎"), (await txt("#midiMsg")).slice(0, 80));
  const sampleStat = await txt("#midiStat");
  /* 用 includes("32") 太松：时长 16.0s / 峰值 32/s 都可能凑出 "32"。
     必须咬住"音符 32"这个统计卡本身。 */
  check("示例解析出 32 个音符", /音符\s*32|32\s*个音符/.test(await txt("#midiMsg") + " " + sampleStat),
    sampleStat.replace(/\s+/g, " ").slice(0, 90));
  check("示例不再报「文件有损坏」", !(await txt("#midiMsg")).includes("损坏"),
    (await txt("#midiMsg")).replace(/\s+/g, " ").slice(0, 90));
  await shot("07a-sample");

  await page.setInputFiles("#file", path.join(__dirname, "test.mid"));
  await page.waitForTimeout(800);
  check("MIDI 读取成功", (await txt("#midiMsg")).includes("已读取"), await txt("#midiMsg"));
  check("分析面板出现", await page.isVisible("#midiPanel"));

  const stat = await txt("#midiStat");
  check("统计卡有 6 项", (await page.$$("#midiStat div")).length === 6, (await page.$$("#midiStat div")).length);
  const plan1 = await txt("#planMsg");
  check("给出命令速率评估", plan1.includes("条命令/秒"), plan1.slice(0, 60));
  check("提示丢音数量", plan1.includes("丢") || plan1.includes("个音"));

  const trackOpts = await page.$$eval("#selTrack option", o => o.map(x => x.textContent));
  check("轨道/通道选项已生成", trackOpts.length >= 2, trackOpts.length + " 项");
  await shot("07-midi-loaded");

  // 切换分配方式 + 重新分析
  await page.selectOption("#selMap", "pitch");
  await page.waitForTimeout(400);
  const plan2 = await txt("#planMsg");
  check("音高对应模式可重新分析", plan2.includes("条命令/秒"));
  await page.selectOption("#selMap", "rr");
  await page.waitForTimeout(300);

  // 播放
  await click("#btnPlay");
  await page.waitForTimeout(1500);
  check("演奏已开始", (await txt("#btnPlay")).includes("暂停"), await txt("#btnPlay"));
  const t = await txt("#playTime");
  check("进度在推进", !t.startsWith("0.0s"), t);
  const rate = await txt("#playRate");
  check("显示实际命令速率", rate.includes("实际") || rate === "—", rate);
  /* 深度条不能只瞬时读一次：无头浏览器里 rAF 只有 ~8fps，
     一个「按下 + 抬起」的对子有可能落在同一帧的追赶循环里，
     帧末渲染出来的就是全 0（实测撞到过：6 条全 0%）。
     所以在一段时间里连续采样，取每条的峰值。 */
  let barPeak = [0, 0, 0, 0, 0, 0];
  for(let i = 0; i < 14; i++){
    const cur = await page.$$eval("#p-play .dep .bar i", els => els.map(e => parseFloat(e.style.width) || 0));
    barPeak = barPeak.map((v, k) => Math.max(v, cur[k] || 0));
    await page.waitForTimeout(80);
  }
  check("手指深度条有变化", barPeak.some(v => v > 0), barPeak.map(v => v + "%").join(" "));
  // 回归：默认「按压幅度 100% + 不跟随力度」时，每个音都要跑满校准行程。
  // 曾经这里只有 Math.max(0.35, e.vel)：力度 0.7 的音就只按到 70%，
  // 用户的感觉同样是"幅度怎么这么小，要用我校准的最大幅度来啊"。
  check("演奏默认用满行程（深度 100%）", barPeak.every(v => v >= 99), barPeak.map(v => v + "%").join(" "));
  check("演奏页默认：幅度 100% + 不跟随力度",
    (await page.inputValue("#fDepth")) === "100" && !(await page.isChecked("#followVel")),
    "depth=" + (await page.inputValue("#fDepth")) + " followVel=" + (await page.isChecked("#followVel")));
  await shot("08-playing");

  await click("#btnStop");
  await page.waitForTimeout(500);
  check("停止后按钮复位", (await txt("#btnPlay")).includes("开始演奏"));

  /* ============ 5b. 音乐 ↔ 演奏动作 同轴显示 ============
     这块是「能听 + 能看 + 两边对齐」的合体，断言盯四件事：
     ① 分析完不按播放就该有总览；
     ② 声音和动作必须来自同一条事件流（起音数 == 已发出的「按下」数）；
     ③ 播放头得跟着时间走；
     ④ 停止要真的静音、关掉开关要一次都不响。 */
  console.log("\n=== 5b. 音乐 ↔ 动作 同轴显示 ===");

  const rollInfo = await page.evaluate(() => {
    const c = document.querySelector("#roll");
    return c ? {w: c.width, h: c.height} : null;
  });
  check("卷帘画布存在且尺寸够画", !!rollInfo && rollInfo.w >= 600 && rollInfo.h >= 300,
    JSON.stringify(rollInfo));

  /* ⚠️ 跟随模式只在「曲子比窗口长」时才验证得了：此刻 plan 还是 test.mid（6.5s，
     短于 8 秒窗口），窗口本来就无处可移。先换回内置样本（≈15.8s）再测。 */
  await click("#btnSample");
  await page.waitForTimeout(700);
  const planLen = await page.evaluate(() => S.plan.events[S.plan.events.length - 1].t);
  check("样本比 8 秒窗口长（跟随模式才有的可动）", planLen > 8000, Math.round(planLen) + "ms");

  /* ⚠️ 颜色统计**必须在不播放时采样**：播放时已播区域会压一层半透明蓝，
     会把底下的纯色染偏，严格匹配全部落空。 */
  const pxStat = () => page.evaluate(() => {
    const c = document.querySelector("#roll");
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    const hex = ["#1a6ef0","#7c4dff","#12a150","#b5730a","#e5484d","#0e9aa7"];
    const rgb = hex.map(h => [parseInt(h.slice(1,3),16), parseInt(h.slice(3,5),16), parseInt(h.slice(5,7),16)]);
    const near = (r,g,b,t) => Math.abs(r-t[0])<8 && Math.abs(g-t[1])<8 && Math.abs(b-t[2])<8;
    const counts = [0,0,0,0,0,0];
    let grey = 0, painted = 0;
    for(let i = 0; i < d.length; i += 4){
      if(d[i+3] === 0) continue;
      painted++;
      for(let k = 0; k < 6; k++) if(near(d[i], d[i+1], d[i+2], rgb[k])) counts[k]++;
      if(near(d[i], d[i+1], d[i+2], [215,221,229])) grey++;
    }
    return {counts, grey, painted};
  });

  const st0 = await pxStat();
  check("分析完就画出总览（不用等按播放）", st0.painted > 20000 && st0.counts.some(v => v > 0),
    JSON.stringify(st0));

  const legend = (await txt("#rollLegend")).replace(/\s+/g, " ");
  check("图例列全 6 根手指 + 丢音",
    ["拇指侧压","拇指下压","食指","中指","无名指","小指"].every(s => legend.includes(s)) &&
    legend.includes("丢掉的音"), legend.slice(0, 80));

  const usedSlots = await page.evaluate(() =>
    (S.plan.used || []).map((v, i) => v > 0 ? i : -1).filter(i => i >= 0));
  check("用到的每根手指都画出了块",
    usedSlots.length >= 5 && usedSlots.every(i => st0.counts[i] > 0),
    "槽位 " + JSON.stringify(usedSlots) + " 像素 " + JSON.stringify(st0.counts));

  /* 跟随模式：窗口应随播放头移动（静态层按 2 秒网格吸附，避免每帧重画） */
  const follow = await page.evaluate(() => {
    const sel = document.querySelector("#rollMode");
    sel.value = "follow"; sel.dispatchEvent(new Event("change"));
    refreshRoll(3000);
    const a = {t0: ROLL.t0, span: ROLL.span};
    refreshRoll(12000);
    const b = {t0: ROLL.t0, span: ROLL.span};
    sel.value = "all"; sel.dispatchEvent(new Event("change"));
    return {a, b};
  });
  check("跟随模式窗口会移动、且不超过 8 秒",
    follow.b.t0 !== follow.a.t0 && follow.a.span <= 8000 && follow.b.span <= 8000,
    JSON.stringify(follow));

  /* 播放一轮：同时看播放头、起音数、已发出的「按下」数 */
  await page.evaluate(() => { S.sndFired = 0; window.__head0 = ROLL.head; });
  await click("#btnPlay");
  await page.waitForTimeout(900);
  const live = await page.evaluate(() => {
    let onsSent = 0;
    for(let i = 0; i < S.cursor; i++) if(S.plan.events[i].on) onsSent++;
    return {head: ROLL.head, head0: window.__head0, snd: S.sndFired, onsSent,
            playing: S.playing, ctx: SND.ctx ? SND.ctx.state : "none"};
  });
  /* 直接在「播放中」调用 stopPlay 并**立刻**读节点数 —— 只有这样才能测到 silence()。
     晚读几百毫秒的话，短音符自己就 ended 出队了，把 silence() 删掉也测不出来（假绿）。 */
  const afterStop = await page.evaluate(() => {
    stopPlay(false);
    return {n: SND.live.length, head: ROLL.head};
  });
  await page.waitForTimeout(250);

  check("播放头随播放推进", live.head > live.head0 + 200,
    "head0=" + live.head0 + " head=" + Math.round(live.head));
  check("播放时确实起了音", live.snd > 0,
    "起音 " + live.snd + " 次（AudioContext=" + live.ctx + "）");
  check("起音数 == 已发出的「按下」数（同一条事件流）", live.snd === live.onsSent,
    "起音 " + live.snd + " / 按下 " + live.onsSent);
  check("停止后音频节点被清空", afterStop.n === 0, "剩余节点 " + afterStop.n);
  check("停止后播放头回到起点", afterStop.head === 0, "head=" + afterStop.head);

  /* 关掉声音开关后必须一次都不起音 —— 别让「静音」变成「没演奏」 */
  await page.uncheck("#sndOn");
  await page.evaluate(() => { S.sndFired = 0; S.fired = 0; });
  await click("#btnPlay");
  await page.waitForTimeout(700);
  const muted = await page.evaluate(() => ({snd: S.sndFired, fired: S.fired}));
  await click("#btnStop");
  await page.check("#sndOn");
  check("关掉「播放声音」后一次都不起音（但动作照发）",
    muted.snd === 0 && muted.fired > 0,
    "起音 " + muted.snd + " / 动作 " + muted.fired);
  await shot("08b-roll");

  /* 回归：演奏引擎必须按**真实映射**取舵机 id，不能假设「槽位 i 的 id 就是 i+1」。
     原先写的是 `MOVE (slot+1)`：对出厂的 [1,2,3,4,5,6] 碰巧成立，
     一旦用户动过编号，就会把 A 槽位的校准位置发给 B 号舵机 ——
     现在固件对 MOVE 有越界闸，那种情况会变成「静默不演奏」（比顶限位安全，但更难查）。
     故意把槽位 0 改成 id=7，看 slotIdOf 是不是跟着走。
     ⚠️ 不真改一下 id 就测不出东西：默认映射下 slotIdOf 与 slot+1 结果相同。 */
  const idRemap = await page.evaluate(async () => {
    await T.send("MAP 0 7", 3000);
    await refreshSlots(true);
    const got = slotIdOf(0);
    await T.send("MAP 0 1", 3000);        // 还原
    await refreshSlots(true);
    return {got, back: slotIdOf(0)};
  });
  check("演奏按真实映射取舵机 id（不假设 slot+1）",
    idRemap.got === 7 && idRemap.back === 1, JSON.stringify(idRemap));

  // 格式 0 文件也要能读
  await page.setInputFiles("#file", path.join(__dirname, "test_f0.mid"));
  await page.waitForTimeout(700);
  check("format 0 文件也能解析", (await txt("#midiMsg")).includes("已读取"), (await txt("#midiMsg")).slice(0, 70));

  // 坏文件要有友好报错
  const bad = path.join(OUT, "bad.mid");
  fs.writeFileSync(bad, Buffer.from("this is definitely not a midi file at all"));
  await page.setInputFiles("#file", bad);
  await page.waitForTimeout(600);
  check("非 MIDI 文件给出友好报错", (await txt("#midiMsg")).includes("读取失败"), (await txt("#midiMsg")).slice(0, 60));

  // 头部正确但内容损坏 —— 应当降级解析而不是崩掉
  const broken = path.join(OUT, "broken.mid");
  const good = fs.readFileSync(path.join(__dirname, "test.mid"));
  fs.writeFileSync(broken, Buffer.concat([good.subarray(0, 40), Buffer.alloc(60, 0xab)]));
  await page.setInputFiles("#file", broken);
  await page.waitForTimeout(800);
  const bm = await txt("#midiMsg");
  check("损坏文件不崩溃（降级或友好报错）",
    bm.includes("已读取") || bm.includes("读取失败"), bm.slice(0, 70));
  await page.setInputFiles("#file", path.join(__dirname, "test.mid"));
  await page.waitForTimeout(700);

  /* 丢音灰影。注意：**正常素材一根手指都不丢**（test.mid 是 85 音符 / 6 秒，
     均摊到 6 根手指完全够用，dropped=0），所以这里分两步：
     先人为注入一批丢音，验证「有丢音时会画灰影」；还原后再确认「没丢音时干净」。
     注入前后都要 refreshRoll，验完立刻把原 plan 放回去。 */
  const drop = await page.evaluate(() => {
    const bak = S.plan;
    const countGrey = () => {
      const c = document.querySelector("#roll");
      const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for(let i = 0; i < d.length; i += 4)
        if(d[i+3] && Math.abs(d[i]-215)<8 && Math.abs(d[i+1]-221)<8 && Math.abs(d[i+2]-229)<8) n++;
      return n;
    };
    const before = countGrey();
    S.plan = Object.assign({}, bak, {
      dropped: 3,
      droppedNotes: [{t:300,d:200,note:64}, {t:900,d:200,note:67}, {t:1500,d:200,note:72}]
    });
    refreshRoll(0);
    const injected = countGrey();
    S.plan = bak;
    refreshRoll(0);
    return {before, injected, after: countGrey(), restored: S.plan === bak,
            listed: (bak.droppedNotes || []).length, dropped: bak.dropped};
  });
  check("有丢音时图上画灰影（人为注入验证）",
    drop.before === 0 && drop.injected > 10 && drop.restored,
    JSON.stringify(drop));
  check("没有丢音时图上不留灰影", drop.after === 0 && drop.dropped === 0 && drop.listed === 0,
    "dropped=" + drop.dropped + " grey=" + drop.after);

  /* ---------- 6. 日志 ---------- */
  console.log("\n=== 6. 日志页 ===");
  await click('#tabbar button[data-p="log"]');
  await page.waitForTimeout(300);
  const logLen = await page.$eval("#log", e => e.innerText.length);
  check("日志已记录内容", logLen > 500, logLen + " 字符");
  check("快捷命令按钮存在", (await page.$$("#quick button")).length === 8);
  await page.fill("#rawCmd", "INFO");
  await click("#btnRaw");
  await page.waitForTimeout(500);
  await shot("09-log");

  /* ---------- 7. 页面切换稳定性 ---------- */
  console.log("\n=== 7. 反复切换页面 ===");
  for(let i = 0; i < 3; i++)
    for(const p of ["connect","assign","cal","test","play","log"]){
      await click(`#tabbar button[data-p="${p}"]`);
      await page.waitForTimeout(60);
    }
  check("反复切换后无异常", errors.length === 0, errors.slice(0,3).join(" ; "));

  /* ---------- 收尾 ---------- */
  console.log("\n=== JS 错误 ===");
  if(errors.length){ errors.forEach(e => console.log("  !! " + e)); }
  else console.log("  无 pageerror / console.error");

  await browser.close();
  server.close();
  console.log("\n截图目录: " + OUT);
  console.log(failures === 0
    ? "\n全部通过 ✔  共 " + checks + " 项"
    : "\n失败 " + failures + " / " + checks + " 项 ✘");
  process.exit(failures === 0 ? 0 : 1);
})().catch(e => { console.error("测试脚本崩溃:", e); process.exit(2); });
