/* 钢琴手套调试台 · 端到端自测
   第 0~7 节：页面逻辑，串口由页面内置假固件顶替（?sim=1），不需要硬件。
   第 8 节：**真** bridge.py 进程 + 假手套（TCP 当串口），验"自动选口自动连接"这条路。 */
const { chromium } = require("playwright-core");
const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const sleep = ms => new Promise(r => setTimeout(r, ms));
const PYTHON = process.env.PYTHON || (process.platform === "win32"
  ? "C:\\Users\\admin\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe"
  : "python3");

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

  /* ⚠️ 必须带 ?sim=1。
     调试台**没有**「模拟模式」这个入口了 —— 用户拿到的版本只有串口一条路。
     但自动化自测不能没有硬件就跑不动，所以页面留了一个只有 URL 能打开的开关：
     ?sim=1 时串口由页面内置的假固件顶替。第 8 节会反过来验证
     「不带 ?sim=1 时，页面上根本没有模拟模式」。
     下面这一大段的断言跑的是**协议/几何/播放逻辑**，跟串口走哪条路无关。 */
  await page.goto(`http://127.0.0.1:${PORT}/web_piano_glove.html?sim=1`, { waitUntil: "load" });
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

  /* 音高对应模式：音域窄的曲子也要把**参与演奏的槽位**用满。
     这条是**回归测试** —— 曾经 hi 兜底到 72、want 用 floor(ratio*6)，
     《小星星》的 C D E F G A 只占满 4 根手指（E/F 挤在食指、小指全程闲着）。
     ★ 分母从 6 改成 PLAY_SLOTS.length：拇指侧摆不参与演奏，
       "6 个音 = 6 根手指"这个说法本身已经不成立了（现在是 6 个音 / 5 指）。 */
  const star = await page.evaluate(() => {
    const sel = document.querySelector("#songLib");
    sel.value = "0";
    sel.dispatchEvent(new Event("change"));
    return new Promise(res => setTimeout(() => {
      document.querySelector("#selMap").value = "pitch";
      analyze();
      const map = {};
      S.plan.events.filter(e => e.on).forEach(e => { map[e.note] = e.slot; });
      res({ used: S.plan.used, map, play: PLAY_SLOTS.slice(), latch: LATCH_SLOT });
    }, 300));
  });
  check("音高对应：窄音域的曲子用满全部参与演奏的手指（" + star.play.length + " 根）",
    star.play.every(s => star.used[s] > 0) &&
    star.used.filter(v => v > 0).length === star.play.length,
    JSON.stringify(star.used) + " play=" + JSON.stringify(star.play));
  check("侧摆槽位拿不到任何音符（它不参与演奏）",
    star.latch >= 0 ? star.used[star.latch] === 0 : true,
    "侧摆槽位 " + star.latch + " 分到 " + (star.used[star.latch] || 0) + " 个音");
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
  /* ⚠️ 采样要**按 data-slot 取**，不能按下标取：
     侧摆那一行也在 deplist 里（显示的是"使能位"，不是深度），
     按下标取会把它当成一根手指，深度恒 0 → 断言平白变红（已经踩过一次）。 */
  const playIdx = await page.evaluate(() => PLAY_SLOTS.slice());
  let barPeak = new Array(playIdx.length).fill(0);
  for(let i = 0; i < 14; i++){
    const cur = await page.$$eval("#p-play .dep", els => els.map(e => {
      const bar = e.querySelector(".bar i");
      return { slot: +e.dataset.slot, w: bar ? (parseFloat(bar.style.width) || 0) : 0 };
    }));
    const bySlot = {}; cur.forEach(o => { bySlot[o.slot] = o.w; });
    barPeak = barPeak.map((v, k) => Math.max(v, bySlot[playIdx[k]] || 0));
    await page.waitForTimeout(80);
  }
  check("手指深度条有变化", barPeak.some(v => v > 0), barPeak.map(v => v + "%").join(" "));
  /* 幅度要**有动态**，但两端都有人管：
     - 上限必须是满行程：力度 1.0 的音要按到底。曾经这里写过
       Math.max(0.35, e.vel)，力度 0.7 的音只按到 70%，用户的感觉是
       "幅度怎么这么小，要用我校准的最大幅度来啊"。
     - 下限要留底：力度 0.2 的音若只按 20%，手指几乎不动、看着像没反应。
     所以断言拆成"至少到过 100%" + "从不低于 40%"，而不是"每根都是 100%"
     —— 后者在「跟随力度」默认打开后就自相矛盾了。 */
  check("深度落在合理区间（不超过校准行程，也不低于 40% 底限）",
    barPeak.every(v => v >= 40 && v <= 100.5), barPeak.map(v => v + "%").join(" "));
  /* ⚠️ 不要断言"每根手指都按到 100%"：那要求曲子里有 vel=1.0 的音，
     而取样的这首力度统一是 90/127 —— 断言本身就成了错的（踩过一次）。
     "强音按到底"这条性质由下面 ampOf(1) === 1 直接保证。
     这里改验更有信息量的事：**深度条上的值必须等于力度映射算出来的值**，
     证明深度真的由力度决定，而不是各手指拍脑袋给个固定数。 */
  /* ⚠️ 不要拿"采样峰值"去比"最大力度的映射值"：无头浏览器里 rAF 只有 ~8fps，
     采样必然覆盖不全，最强的那个音经常没被采到 —— 那条断言会平白无故地红
     （实测 84% vs 计算 88%，就是这么来的）。
     改成**值域包含**：采样到的深度必须全部落在「本曲力度映射」的取值范围内。

     ★ 期望值必须**在这里独立算一遍**，绝不能调页面的 `ampOf`。
     第一版就是调了 `ampOf` —— 结果把 ampOf 改成恒 1 时，
     实测深度和"期望区间"会**一起**变成 100%，自洽了，断言照样绿
     （变异测试当场照出来：这条是假绿，抓到变异的是另一条断言）。
     期望值由被测代码算出来就不叫断言，叫自证。 */
  const ampRange = await page.evaluate(() => {
    const vels = S.plan.events.filter(e => e.on).map(e => e.vel);
    const dp = fingerDepth();
    const want = v => 0.45 + 0.55 * Math.max(0, Math.min(1, v));   // 独立写一遍
    return { lo: Math.round(want(Math.min(...vels)) * dp * 100),
             hi: Math.round(want(Math.max(...vels)) * dp * 100),
             minVel: Math.min(...vels), maxVel: Math.max(...vels) };
  });
  check("采样深度全部落在「力度 → 深度」的值域内（深度真的由力度算出来）",
    barPeak.every(v => v >= ampRange.lo - 2 && v <= ampRange.hi + 2),
    `实测 ${barPeak.join("% ")}% ｜ 理论区间 ${ampRange.lo}~${ampRange.hi}%` +
    `（力度 ${ampRange.minVel.toFixed(3)}~${ampRange.maxVel.toFixed(3)}）`);

  /* 映射两端直接测**页面真正调用的那个函数**（ampOf），不靠采样 DOM 猜 ——
     采样只能看出峰值，看不出"不同力度确实按得不一样深"。 */
  const ampMap = await page.evaluate(() => {
    const el = $("#followVel");
    const was = el.checked;
    el.checked = true;
    const on = { lo: ampOf(0), mid: ampOf(0.5), hi: ampOf(1) };
    el.checked = false;
    const off = { lo: ampOf(0), hi: ampOf(1) };
    el.checked = was;
    return { on, off };
  });
  check("力度映射：强音 = 满行程、弱音 = 45% 底限、中间单调",
    ampMap.on.hi === 1 && Math.abs(ampMap.on.lo - 0.45) < 1e-9 &&
    ampMap.on.mid > ampMap.on.lo && ampMap.on.mid < ampMap.on.hi,
    JSON.stringify(ampMap.on));
  check("取消「跟随力度」后每个音都走满行程",
    ampMap.off.lo === 1 && ampMap.off.hi === 1, JSON.stringify(ampMap.off));
  check("演奏页默认：幅度 100% + 跟随力度（用户要的「幅度要有区别」）",
    (await page.inputValue("#fDepth")) === "100" && (await page.isChecked("#followVel")),
    "depth=" + (await page.inputValue("#fDepth")) + " followVel=" + (await page.isChecked("#followVel")));

  /* ★★ 时序：物理约束必须写在**真实时间**域 —— 这是本轮修的核心 ★★
     用户报「最快的革命练习曲每个键都是抖动一下、根本没按下去」。
     根因：按住时长原来按**曲谱**毫秒算（clamp(n.d*0.8, 55, 200)），
     200% 速度下 60ms 的按住只剩 30ms 真实时间，而舵机走完一次行程要 ~90ms
     —— 还没按到底就被叫回来了。
     所以这里断言的是**与速度无关的性质**：不管速度调到多少，
     每个音的真实按住时长都不短于行程时间，同一根手指两次按下之间
     都留得下「按住 + 松开」一个完整周期。 */
  const timeChk = await page.evaluate(async () => {
    const out = [];
    for(const sp of [50, 100, 200, 250]){
      $("#speed").value = String(sp);
      analyze();
      await new Promise(r => setTimeout(r, 40));
      const st  = strokeMs();
      const ons = S.plan.events.filter(e => e.on);
      const bySlot = Array.from({ length: 6 }, () => []);
      ons.forEach(e => bySlot[e.slot].push(e.t));
      const k = curSpeed();
      let minGap = Infinity;
      bySlot.forEach(l => {
        for(let i = 1; i < l.length; i++) minGap = Math.min(minGap, (l[i] - l[i - 1]) / k);
      });
      const holds = ons.map(e => e.holdReal);
      out.push({
        sp, stroke: st,
        short: ons.filter(e => e.holdReal < st - 0.5).length,
        minHold: holds.length ? Math.min(...holds) : null,
        maxHold: holds.length ? Math.max(...holds) : null,
        minGap: minGap === Infinity ? null : minGap,
        dropped: (S.plan.droppedNotes || []).length
      });
    }
    $("#speed").value = "100";
    $("#speedLabel").textContent = "100%";
    analyze();
    return out;
  });
  check("任何速度下都没有「按不到底」的音（真实按住时长 ≥ 行程时间）",
    timeChk.every(t => t.short === 0),
    timeChk.map(t => t.sp + "%→" + t.short + "个").join(" "));
  /* 「按压时间长度也要加上啊，不是每个音都是短平快的」——
     按住时长要跟着音符时值走。上面那条只保证了下限，
     这条保证**长短真的有区别**，而不是所有音都被夹成同一个值。 */
  check("按住时长跟随音符时值（长音按得久、短音按得短）",
    timeChk.some(t => t.maxHold > t.minHold * 1.5),
    timeChk.map(t => t.sp + "%:" + Math.round(t.minHold) + "~" + Math.round(t.maxHold) + "ms").join(" "));
  check("同一根手指两次按下之间留得下「按住 + 松开」一个完整周期",
    timeChk.every(t => t.minGap === null || t.minGap >= t.stroke * 2 - 1),
    timeChk.map(t => t.sp + "%:" + (t.minGap === null ? "—" : Math.round(t.minGap) + "ms")).join(" "));

  /* 行程时间是个真旋钮：调大它，同一根手指被占得久，丢音必须变多。
     如果调了没反应，说明这个参数根本没接进 plan。 */
  const strokeSweep = await page.evaluate(async () => {
    const el = $("#fStroke");
    const set = async v => {
      el.value = String(v);
      el.dispatchEvent(new Event("input"));
      await new Promise(r => setTimeout(r, 60));
      return { stroke: strokeMs(), dropped: (S.plan.droppedNotes || []).length };
    };
    const a = await set(60), b = await set(240);
    await set(90);
    return { a, b };
  });
  check("「手指行程时间」真的接进了规划（调大 → 丢音变多）",
    strokeSweep.b.dropped > strokeSweep.a.dropped && strokeSweep.b.stroke === 240,
    `60ms→丢${strokeSweep.a.dropped}  240ms→丢${strokeSweep.b.dropped}`);

  check("「手套按不了的音」数量直接写在界面上，不用猜",
    /\d/.test(await page.textContent("#dropStat")), await page.textContent("#dropStat"));
  check("「按不了的音也用声音补齐」默认打开",
    await page.isChecked("#sndAll"));

  /* ★ 用户说「我点开了那个按钮还是没啥变化」。
     真正的答案是：那首曲子本来一个音都没丢，开关当然没变化 ——
     而界面上原来完全看不出丢了几个。
     所以这里两头都验：①丢音数会显示出来；②开关真的改声音，
     而不是只改一个勾。用革命练习曲（L5，必然丢音）跑两小段来对比。 */
  const sndAllChk = await page.evaluate(async () => {
    const sel = document.querySelector("#songLib");
    sel.value = String(SONG_LIB.findIndex(s => s.slug === "revolutionary"));
    sel.dispatchEvent(new Event("change"));
    await new Promise(r => setTimeout(r, 600));

    const st = document.querySelector("#fStroke");
    const setStroke = async v => {
      st.value = String(v); st.dispatchEvent(new Event("input"));
      await new Promise(r => setTimeout(r, 100));
    };
    await setStroke(150);                     // 把行程调大，保证一定丢音

    document.querySelector('#tabbar button[data-p="play"]').click();
    await new Promise(r => setTimeout(r, 150));

    const statText = document.querySelector("#dropStat").textContent;
    const run = async all => {
      document.querySelector("#sndAll").checked = all;
      document.querySelector("#loop").checked = false;
      document.querySelector("#btnPlay").click();
      await new Promise(r => setTimeout(r, 1500));
      const fired = S.sndFired || 0;
      document.querySelector("#btnStop").click();
      await new Promise(r => setTimeout(r, 150));
      return fired;
    };
    const on  = await run(true);
    const off = await run(false);
    const dropped = (S.plan.droppedNotes || []).length;
    await setStroke(90);
    return { dropped, statText, on, off };
  });
  check("丢音数写在界面上（用户能看出这个开关有没有用）",
    sndAllChk.dropped > 0 && /按不了/.test(sndAllChk.statText),
    sndAllChk.statText);
  check("「补齐按不了的音」真的多出声（不是只改一个勾）",
    sndAllChk.on > sndAllChk.off,
    `丢音 ${sndAllChk.dropped} 个；开着起音 ${sndAllChk.on} 次，关掉 ${sndAllChk.off} 次`);

  /* ★ 声音时长必须是**真实毫秒**，不能是曲谱毫秒。
     原来传的是 e.durMs（曲谱），200% 速度下每个音都拖成两倍长、糊成一片 ——
     这就是用户说的"音乐对不上"的听觉来源（节奏在，但听不清在弹哪个音）。
     做法：把 tone 换成记录器跑一小段，看它收到的时长和 plan 里的
     holdReal 是否一致。速度不是 100% 时两者必然不等，所以这条能咬人。 */
  const sndDur = await page.evaluate(async () => {
    $("#speed").value = "200";
    $("#speedLabel").textContent = "200%";
    analyze();
    await new Promise(r => setTimeout(r, 60));
    const orig = tone;
    const seen = [];
    tone = (note, durMs) => { seen.push(durMs); };
    document.querySelector("#loop").checked = false;
    document.querySelector("#btnPlay").click();
    await new Promise(r => setTimeout(r, 1200));
    document.querySelector("#btnStop").click();
    tone = orig;
    document.querySelector("#sndAll").checked = true;   // 恢复默认，别污染后面的用例
    await new Promise(r => setTimeout(r, 120));
    const ons = S.plan.events.filter(e => e.on);
    return { got: seen.slice(0, 8), want: ons.slice(0, 8).map(e => e.holdReal),
             score: ons.slice(0, 8).map(e => e.durMs), n: seen.length };
  });
  check("声音时长用的是真实毫秒（不是曲谱毫秒，否则快曲会糊成一片）",
    sndDur.n > 0 && sndDur.got.every((v, i) => Math.abs(v - sndDur.want[i]) < 0.01),
    `收到 ${JSON.stringify(sndDur.got.slice(0, 3))} / 期望 ${JSON.stringify(sndDur.want.slice(0, 3))}` +
    `（曲谱时长是 ${JSON.stringify(sndDur.score.slice(0, 3))}）`);
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

  /* 图例只列**参与演奏**的手指，并明确写出侧摆不参与 ——
     图里没有它的轨，列出来会让人以为"怎么少了一条"。 */
  const legInfo = await page.evaluate(() => ({
    text: (document.querySelector("#rollLegend") || {}).textContent.replace(/\s+/g, " "),
    play: PLAY_SLOTS.map(s => SLOTS[s]),
    latch: LATCH_SLOT >= 0 ? SLOTS[LATCH_SLOT] : null
  }));
  check("图例列全参与演奏的手指 + 丢音",
    legInfo.play.every(s => legInfo.text.includes(s)) &&
    legInfo.text.includes("丢掉的音"), legInfo.text.slice(0, 90));
  check("图例点明侧摆不参与演奏",
    !legInfo.latch || legInfo.text.includes(legInfo.latch + "（侧摆）不参与演奏"),
    legInfo.text.slice(-40));

  const usedSlots = await page.evaluate(() =>
    (S.plan.used || []).map((v, i) => v > 0 ? i : -1).filter(i => i >= 0));
  check("用到的每根手指都画出了块",
    usedSlots.length >= 5 && usedSlots.every(i => st0.counts[i] > 0),
    "槽位 " + JSON.stringify(usedSlots) + " 像素 " + JSON.stringify(st0.counts));
  check("侧摆那一行的颜色一个像素都没有（整场不动）",
    !(await page.evaluate(() => S.plan.used[LATCH_SLOT] || 0)) &&
    (!st0.counts[await page.evaluate(() => LATCH_SLOT)]),
    "latch 像素 " + st0.counts[await page.evaluate(() => LATCH_SLOT)]);

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
    let onsSent = 0, onsRung = 0;
    for(let i = 0; i < S.cursor; i++) if(S.plan.events[i].on) onsSent++;
    for(let i = 0; i < S.sndCursor; i++) if(S.plan.events[i].on) onsRung++;
    return {head: ROLL.head, head0: window.__head0, snd: S.sndFired, onsSent, onsRung,
            sndCursor: S.sndCursor, cursor: S.cursor, lead: S.sndLead,
            attack: S.sndAttack, stroke: S.plan.stroke,
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
  /* 声音由**自己的游标**驱动 —— 音画对齐要把声音提前提交（见页面的 audioLeadMs），
     所以它对应的是「声音游标越过的按下数」，不是动作游标的。
     原先这里比的是动作游标：在小星星这种稀疏曲子上恰好相等、侥幸为真，
     换一首密集的曲子就会红 —— 属于隐性假绿，不是真过。 */
  check("起音数 == 声音游标越过的「按下」数（声音只有一个来源）",
    live.snd === live.onsRung, "起音 " + live.snd + " / 声音游标按下 " + live.onsRung);
  /* 声音游标与动作游标的**先后**由「起音点 ÷ 声卡延迟」决定：
     起音点（行程一半）把声音往后推、声卡延迟把它往前拉，谁大就谁说了算。
     所以不能死写「声音游标一定不落后」—— 本机声卡延迟 60ms > 行程一半 45ms 时成立，
     换一块只报 30ms 的声卡就不成立，那种断言属于把本机参数焊进测试里。 */
  const aheadSign = live.lead - live.stroke * live.attack;
  check("声音游标与动作游标的先后 == 「起音点 vs 声卡延迟」算出来的方向",
    aheadSign >= 0 ? live.sndCursor >= live.cursor : live.sndCursor <= live.cursor,
    "起音点 " + Math.round(live.stroke * live.attack) + "ms vs 声卡 " + live.lead
      + "ms（" + (aheadSign >= 0 ? "净提前" : "净推后") + "）→ 声音游标 "
      + live.sndCursor + " / 动作游标 " + live.cursor);
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

  /* ★ 起音点 + 音画对齐（用户两轮反馈的回归）——
     第一轮：「舵机按下去要过一会声音才响」→ 声音要**提前提交**抵消声卡固定延迟。
     第二轮：「应该在按下行程的一半就发出声音，跟弹钢琴一样」
           → 出声时刻不是"手指一动"，而是"手指走到行程的一半"。

     合起来就一条式子（真实毫秒）：
         提交时刻 = 按下时刻 + 行程 × 起音点 − 声卡延迟
     这里**逐个音**验证这条式子真的被算进去了 —— 小星星音符间隔 3.3 秒，
     补偿窗口里根本没有第二个音，那种"数一数有没有提前"的写法怎么写都是绿的。
     改用密集曲子（革命练习曲，真实间隔 188ms）保证样本够。
     关掉「补齐按不了的音」：丢音补齐也走 tone，会把样本顺序搅乱。 */
  const align = await page.evaluate(async () => {
    const idx = SONG_LIB.findIndex(s => s.slug === "revolutionary");
    const sel = document.querySelector("#songLib");
    sel.value = String(idx);
    sel.dispatchEvent(new Event("change"));
    await new Promise(r => setTimeout(r, 600));
    if(S.info.armed !== "1"){ await T.send("ARM", 3000); await refreshInfo(); }

    /* ★ 把「手指行程时间」拉到 200ms 再测：这样 行程×起音点 = 100ms，
       远大于一帧的量化误差（16.7ms），"起音点有没有被算进去"才测得出来。
       用默认 90ms 时预期提前量是 −40ms，和"完全没减行程"只差 45ms，
       被帧量化吃掉一半就滑进容差里 —— 又是一个假绿。测完还原。 */
    const stEl = document.querySelector("#fStroke");
    stEl.value = "200"; stEl.dispatchEvent(new Event("input"));
    await new Promise(r => setTimeout(r, 400));

    const allEl = document.querySelector("#sndAll");
    const wasAll = allEl.checked;
    allEl.checked = false;
    document.querySelector("#sndOn").checked = true;
    /* 起音点用默认的一半 —— 显式写一次，免得上一个用例把 localStorage 改了，
       这里量到的提前量就跟着漂（断言是按默认值算的预期） */
    const atkEl = document.querySelector("#avAttack");
    atkEl.value = "50"; atkEl.dispatchEvent(new Event("input"));

    const rec = [];
    const orig = window.tone;
    window.tone = function(){
      if(S.playing) rec.push(performance.now() - S.t0);   // 提交时刻（真实毫秒，从 t0 起算）
      return orig.apply(this, arguments);
    };
    document.querySelector("#btnPlay").click();
    await new Promise(r => setTimeout(r, 4500));
    document.querySelector("#btnStop").click();
    await new Promise(r => setTimeout(r, 200));
    window.tone = orig;

    /* ★ 所有要断言的数据必须在这里**一次读干净**，不能等还原行程之后再读。
       踩过的坑：先还原行程（那会触发 analyze() 重算 plan），再返回 S.plan.stroke ——
       读到的是还原后那份（90），于是预期提前量算成 15ms 而不是 −40ms；
       更糟的是 S.plan.events 也被换成了"按 90ms 算、丢音更少"的新列表，
       和刚才实际演奏时那批 `on` 事件**下标全错位**，
       量出来的"提前量"中位数成了 −1322ms 这种鬼数字。
       教训：被测状态要在**受干扰之前**快照出来，别让"还原现场"的动作污染观测。 */
    const k = curSpeed();
    const ons = S.plan.events.filter(e => e.on).map(e => e.t);
    const snap = { stroke: S.plan.stroke, attack: S.sndAttack, lead: S.sndLead };

    allEl.checked = wasAll;
    stEl.value = "90"; stEl.dispatchEvent(new Event("input"));   // 还原行程，别影响后面的断言
    await new Promise(r => setTimeout(r, 200));

    /* 第 i 次 tone 调用 = 第 i 个 on 事件（声音游标按事件顺序推进，同一个来源） */
    const early = [];
    for(let i = 0; i < Math.min(rec.length, ons.length); i++){
      early.push(ons[i] / k - rec[i]);                    // 正数 = 提交时刻早于「手指开始动」
    }
    early.sort((a, b) => a - b);
    /* 理论提交时刻 = 声卡延迟 − 行程×起音点（**净提前量**，正 = 早于"手指开始动"提交）。
       注意方向别想当然：行程一半 100ms 比声卡延迟 60ms 大，所以这一项是 **−40ms**
       —— 意思是"手指都走了一半（100ms）声音才该响，可声卡只欠 60ms，
       于是提交时刻反而要落在按下之后 40ms"。
       提交只可能比理论时刻**晚**（rAF 一帧的量化误差），不可能更早。 */
    return {
      n: early.length, lead: snap.lead, stroke: snap.stroke, attack: snap.attack,
      target: snap.lead - snap.stroke * snap.attack,
      med: early.length ? early[Math.floor(early.length / 2)] : null,
      lo: early.length ? early[0] : null,
      hi: early.length ? early[early.length - 1] : null
    };
  });
  /* 先把"这个用例有分辨力"当前提断言掉：行程×起音点必须够大，
     否则预期提前量跟"完全不减行程"差不了几毫秒，变异也测不出来。 */
  check("起音点有分辨力：行程 × 起音点 要远大于一帧的量化误差（否则这个用例测不出东西）",
    align.stroke * align.attack >= 60,
    "行程 " + align.stroke + "ms × 起音点 " + Math.round(align.attack * 100)
      + "% = " + Math.round(align.stroke * align.attack) + "ms");
  /* ★ 这条断言是**单边**的，故意的：声音只可能比理论时刻**晚**（rAF 一帧的量化误差，
     0~16.7ms），不可能在算出来的时刻之前提交。所以上界卡死在理论值 +2ms，
     下界给足 30ms 让帧抖动过去。
     单边窗口比"±25ms 对称容差"咬得紧得多：对称容差下"起音点被忽略"只差 20ms，
     会整个滑进容差里 —— 又是一次假绿。 */
  check("起音点：声音落在「手指走到行程一半」时（提交时刻 = 声卡延迟 − 行程×起音点，逐个音验过）",
    align.n >= 5 && align.med <= align.target + 2 && align.med >= align.target - 30,
    "实测提交时刻 中位 " + Math.round(align.med) + "ms（正数=早于手指开始动，负数=晚于），应为 "
      + Math.round(align.target) + "ms ＝ 声卡 " + align.lead + " − 行程 " + align.stroke + "×"
      + Math.round(align.attack * 100) + "%；样本 " + align.n
      + " 个音，范围 " + Math.round(align.lo) + "~" + Math.round(align.hi) + "ms");

  /* 起音点控件：默认一半、改得动、存得住、读数跟着行程换 —— 四件事缺一，
     "声音位置不对"时用户就没法自救（这正是第一轮的教训：自动算的一定要留手动口子）。 */
  const atkUi = await page.evaluate(() => {
    const el = document.querySelector("#avAttack");
    const def = el.value;
    const atkLb = document.querySelector("#avAttackLabel").textContent;
    const net0 = document.querySelector("#avNet").textContent;
    el.value = "0"; el.dispatchEvent(new Event("input"));
    const zeroLb = document.querySelector("#avAttackLabel").textContent;
    el.value = "90"; el.dispatchEvent(new Event("input"));
    const maxLb = document.querySelector("#avAttackLabel").textContent;
    /* ⚠️ 必须**分别**读两次：踩过的坑是先设 90、再还原 50，然后才读 localStorage ——
       读到的是还原后的 50，而期望却写的 90，断言就没意义了。 */
    const stored90 = localStorage.getItem("pg_attack_pct");
    el.value = "50"; el.dispatchEvent(new Event("input"));      // 还原，别影响后面的断言
    const stored50 = localStorage.getItem("pg_attack_pct");
    return {def, atkLb, net0, zeroLb, maxLb, stored90, stored50};
  });
  check("起音点控件默认落在行程一半，且读数把毫秒算出来",
    atkUi.def === "50" && /行程 50%/.test(atkUi.atkLb) && /＝ \d+ms/.test(atkUi.atkLb),
    JSON.stringify(atkUi.atkLb));
  check("起音点两头都拉得动（0% = 手指一动就响，90% = 快按到底才响）",
    /行程 0%/.test(atkUi.zeroLb) && /行程 90%/.test(atkUi.maxLb),
    atkUi.zeroLb + " / " + atkUi.maxLb);
  check("起音点的选择真的写进了浏览器（改 90 存 90，改回 50 存 50）",
    atkUi.stored90 === "90" && atkUi.stored50 === "50",
    "设 90 时存 " + atkUi.stored90 + "，设回 50 时存 " + atkUi.stored50);
  check("「声音落点」那行把三个数都摊开（落点 / 声卡 / 提交提前量）",
    /落点/.test(atkUi.net0) && /声卡/.test(atkUi.net0) && /提交时刻/.test(atkUi.net0),
    atkUi.net0.replace(/\s+/g, " ").slice(0, 120));

  /* 控件：实测值要显示出来、微调要存得住 —— 两者缺一，「自动补的不合适」时用户就没法自救 */
  const avUi = await page.evaluate(() => {
    const el = document.querySelector("#avLead");
    const before = document.querySelector("#avLeadLabel").textContent;
    el.value = "25"; el.dispatchEvent(new Event("input"));
    const after = document.querySelector("#avLeadLabel").textContent;
    const stored = localStorage.getItem("pg_align_offset");
    el.value = "0"; el.dispatchEvent(new Event("input"));      // 还原，别影响后面的断言
    return {before, after, stored};
  });
  check("音画对齐控件把实测延迟显示出来", /实测 \d+ms/.test(avUi.before), avUi.before);
  check("音画对齐的微调会存进浏览器（下次打开还在）",
    avUi.stored === "25" && /\+25/.test(avUi.after), JSON.stringify(avUi));
  await shot("08c-align");

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

  /* ---------- 5c. 演奏速度分级 & 音频自检 ---------- */
  /* 「越高级越快」不能只是文案，得是**可断言的数字**：
     曲库每首自带建议速度（L1 90% → L5 200%），选曲即套用。
     L5 特意超过手套的物理上限，用来看它怎么主动丢音、保住节奏。 */
  const pickSong = async (k) => {
    await page.$eval("#songLib", (el, v) => {
      el.value = String(v); el.dispatchEvent(new Event("change"));
    }, k);
    await page.waitForTimeout(800);
    return { speed: await page.inputValue("#speed"), hint: await txt("#speedHint") };
  };
  const nSongs = await page.$$eval("#songLib option", o => o.length);

  const s1 = await pickSong(0);                    // L1 小星星
  check("选 L1 自动套用该级速度 90%", s1.speed === "90", s1.speed);
  check("速度提示给出了按压频率", s1.hint.includes("次按压"), s1.hint);

  const s5 = await pickSong(nSongs - 1);           // L5 革命练习曲
  check("选 L5 自动套用该级速度 200%（越高级越快）", s5.speed === "200", s5.speed);
  check("L5 的速度下明确提示超出手套上限、会丢音",
    s5.hint.includes("倍") && s5.hint.includes("丢"), s5.hint);

  /* 滑块上限必须够高，否则"达到极限"这个诉求根本表达不出来（150% 那版压不到顶） */
  const maxAttr = await page.getAttribute("#speed", "max");
  check("速度滑块上限 ≥ 200%（能压到极限）", parseInt(maxAttr, 10) >= 200, maxAttr);
  await click("#btnMaxSpeed");
  check("「拉满」把速度顶到滑块上限", (await page.inputValue("#speed")) === maxAttr,
    await page.inputValue("#speed"));

  /* L1 与 L5 在各自建议速度下的**实际按压频率**必须真的递增 ——
     这是"越高级越快"的硬证据，看标签是看不出来的。 */
  /* 注：别叫 hzOf —— 上面 4B 测速那段已经用掉这个名字了（同一作用域） */
  const pressHzOf = h => { const m = /约\s*([\d.]+)\s*次按压/.exec(h); return m ? parseFloat(m[1]) : -1; };
  const l1hz = pressHzOf(s1.hint), l5hz = pressHzOf(s5.hint);
  check("L5 的实际按压频率高于 L1（越高级越快）", l5hz > l1hz && l1hz > 0,
    "L1=" + l1hz + " Hz  L5=" + l5hz + " Hz");

  /* 音频：试听按钮必须真的把音起出来。
     这条是**用户报「演奏没声音」之后加的回归** —— 页面得能自证在发声，
     下次再遇到"没声音"，一眼就能区分是页面问题还是输出环境问题。 */
  await page.evaluate(() => { S.sndFired = 0; });
  await click("#btnSndTest");
  await page.waitForTimeout(700);
  const snd = await page.evaluate(() => ({
    fired: S.sndFired || 0,
    state: SND.ctx ? SND.ctx.state : "no-ctx",
    badge: (document.querySelector("#sndState") || {}).textContent || ""
  }));
  check("「试听」真的起音且 AudioContext 在跑",
    snd.fired > 0 && snd.state === "running", JSON.stringify(snd));
  check("音频状态在界面上可见（不让用户猜）", snd.badge.length > 0, snd.badge);

  /* 演奏入口必须在**第一个 await 之前**解锁音频 ——
     否则 await 一过用户手势就失效，resume() 被拒，表现就是"手指在动、没有声音"。
     ⚠️ 这里有个假绿陷阱：headless Chromium 里 AudioContext 一建出来就是 running，
     所以「读 state 看是不是 running」永远成立、什么都测不到。必须**数调用次数**。 */
  const unlocked = await page.evaluate(() => {
    S.playing = false;
    let n = 0;
    const real = unlockAudio;
    window.unlockAudio = function(){ n++; return real.apply(null, arguments); };
    document.querySelector("#btnPlay").click();       // 走真实入口
    window.unlockAudio = real;
    return { n, state: SND.ctx ? SND.ctx.state : "no-ctx" };
  });
  await page.waitForTimeout(400);
  check("点「开始演奏」确实解锁了音频（不是拖到 rAF 里才建）",
    unlocked.n === 1 && unlocked.state === "running", JSON.stringify(unlocked));
  await click("#btnStop");

  await pickSong(0);                               // 还原到最低级，别把后面的用例带偏
  await shot("11-speed-levels");

  /* 丢音灰影。注意：**正常素材一根手指都不丢**（test.mid 是 85 音符 / 6 秒，
     均摊到 5 根手指完全够用，dropped=0），所以这里分两步：
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

  /* ============ 5f. 拇指两轴：角色 + 侧摆使能位 ============
     用户的原始描述：「按下关节才是控制侧摆的，侧摆才是按下的」——
     即"哪根舵机负责按压"和标签是反的，而且**侧摆不参与演奏**，
     它只负责开始前把拇指摆到能压到琴键的位置。
     这一节把这条规则钉死，并且保证它对调之后不会串味。 */
  console.log("\n=== 5f. 拇指两轴：角色 + 侧摆使能位 ===");

  const role0 = await page.evaluate(() => ({
    slots: SLOTS.slice(), play: PLAY_SLOTS.slice(), latch: LATCH_SLOT,
    chip: document.querySelector("#cFingers").textContent,
    chipTitle: document.querySelector("#cFingers").title
  }));
  check("默认：1 号=拇指按压（参与演奏）、2 号=拇指侧摆（不参与）",
    role0.slots[0] === "拇指按压" && role0.slots[1] === "拇指侧摆" && role0.latch === 1,
    JSON.stringify(role0.slots) + " latch=" + role0.latch);
  check("参与演奏的槽位 = 拇指按压 + 四指（共 5 根）",
    JSON.stringify(role0.play) === JSON.stringify([0,2,3,4,5]), JSON.stringify(role0.play));
  check("顶栏写明参与演奏的手指数，且注明侧摆不演奏",
    role0.chip.includes("5") && role0.chipTitle.includes("拇指侧摆"), role0.chip);

  /* 第 4 步那个「现在：1 号 = …，2 号 = …」的白框**一开始就该有内容** ——
     用户不该为了看"我这只手上哪根是按压"先去点一次「两根轴对调」。
     踩过：refreshRoleUI() 只在 btnSwapThumb.onclick 里调过、启动时漏了，
     症状就是那个框空着（截图里才看出来），而功能本身全对、断言也全绿。 */
  const roleNow0 = (await page.textContent("#roleNow") || "").trim();
  check("「现在：1 号 = …，2 号 = …」一开始就有内容（不用先点对调）",
    roleNow0.includes("1 号 = " + role0.slots[0]) && roleNow0.includes("2 号 = " + role0.slots[1]),
    roleNow0);

  /* 3C：使能位的取值范围必须来自校准区间 */
  const latchUi = await page.evaluate(() => {
    const r = latchRange();
    if(!r) return { range: null };
    setLatchSlider(30);
    const p = latchPctToPos(30);
    return { range: r, pos: p, inRange: p >= r.lo && p <= r.hi, pct: latchPosToPct(p) };
  });
  check("使能位滑块的范围 = 该校准区间，且取值落在区间内",
    !!latchUi.range && latchUi.range.hi > latchUi.range.lo && latchUi.inRange,
    JSON.stringify(latchUi));

  await click('#tabbar button[data-p="cal"]');
  await page.waitForTimeout(250);
  check("3C 使能位卡片在校准后可见", await page.isVisible("#latchBody"));
  await page.evaluate(() => setLatchSlider(30));
  await click("#btnLatchSave");
  await page.waitForTimeout(250);
  const savedLatch = await page.evaluate(() => ({
    pos: latchPos(), auto: latchAutoOn(), raw: localStorage.getItem("pg_latch_pos"),
    row: document.querySelector("#latchRow").textContent
  }));
  check("「记住这个位置」真的存下来了",
    savedLatch.pos === latchUi.pos && savedLatch.auto === true,
    JSON.stringify(savedLatch));
  check("存的是「槽位:位置」，不是光一个位置（对调角色后不会串到另一根轴上）",
    String(savedLatch.raw).split(":").length === 2 && +String(savedLatch.raw).split(":")[0] === 1,
    savedLatch.raw);
  check("演奏页那一行显示使能位，并写明不参与演奏",
    savedLatch.row.includes("使能位") && savedLatch.row.includes("不参与演奏"),
    savedLatch.row.slice(0, 90));

  /* 演奏时：侧摆**只发一条**命令（摆到使能位），整场不再动；
     暂停/结束后送回松开位。 */
  await click('#tabbar button[data-p="play"]');
  await page.waitForTimeout(250);
  const latchPlay = await page.evaluate(async () => {
    const seen = [];
    const orig = T.mock.handle.bind(T.mock);
    T.mock.handle = c => { seen.push(String(c)); return orig(c); };
    const wait = ms => new Promise(r => setTimeout(r, ms));
    const sel = document.querySelector("#songLib");
    sel.value = "0"; sel.dispatchEvent(new Event("change"));
    await wait(400);
    document.querySelector("#loop").checked = false;
    const latchId = slotIdOf(LATCH_SLOT);
    const want    = latchPos();
    const standby = parseInt((S.slots[LATCH_SLOT] || {}).standby, 10);
    const touch   = new RegExp("^MOVE " + latchId + "\\b");
    const n0 = seen.length;
    document.querySelector("#btnPlay").click();
    await wait(900);
    const during  = seen.slice(n0).filter(c => touch.test(c));
    const firedAll = seen.length - n0;
    const n1 = seen.length;
    document.querySelector("#btnPlay").click();      // 再点一次 = 暂停
    await wait(700);
    const after = seen.slice(n1).filter(c => touch.test(c));
    T.mock.handle = orig;
    return { latchId, want, standby, during, after, firedAll };
  });
  check("演奏开始时侧摆恰好发一条命令，且是使能位",
    latchPlay.during.length === 1 && latchPlay.during[0] === "MOVE " + latchPlay.latchId + " " + latchPlay.want + " 0 0 ARM",
    JSON.stringify(latchPlay.during));
  check("演奏过程中侧摆不再被碰（它不是一根会按琴键的手指）",
    latchPlay.firedAll > 4 && latchPlay.during.length === 1,
    "共发 " + latchPlay.firedAll + " 条，侧摆占 " + latchPlay.during.length);
  check("暂停后侧摆回到松开位",
    latchPlay.after.some(c => c.startsWith("MOVE " + latchPlay.latchId + " " + latchPlay.standby)),
    JSON.stringify(latchPlay.after) + " standby=" + latchPlay.standby);

  /* 角色对调：只换角色，校准不作废，参与演奏的仍是 5 根 */
  const swap = await page.evaluate(async () => {
    const wait = ms => new Promise(r => setTimeout(r, ms));
    const snap = () => ({ slots: SLOTS.slice(), play: PLAY_SLOTS.slice(), latch: LATCH_SLOT,
                          cal: S.info.calibrated, latchPos: latchPos() });
    const before = snap();
    document.querySelector("#btnSwapThumb").click();
    await wait(600);
    const after = snap();
    document.querySelector("#btnSwapThumb").click();
    await wait(600);
    return { before, after, back: snap() };
  });
  check("对调后：1 号变侧摆、2 号变按压，参与演奏的仍是 5 根",
    swap.after.slots[0] === "拇指侧摆" && swap.after.slots[1] === "拇指按压" &&
    JSON.stringify(swap.after.play) === JSON.stringify([1,2,3,4,5]),
    JSON.stringify(swap.after.slots) + " " + JSON.stringify(swap.after.play));
  check("对调角色不清校准（校准按槽位存，与角色无关）",
    swap.after.cal === "1", "cal=" + swap.after.cal);
  check("对调后使能位不会串到另一根轴上（存的是槽位:位置）",
    swap.after.latchPos === null && swap.before.latchPos !== null,
    "前 " + swap.before.latchPos + " → 后 " + swap.after.latchPos);
  check("再对调一次回到默认安排，使能位也回来",
    swap.back.slots[0] === "拇指按压" && swap.back.latch === 1 &&
    JSON.stringify(swap.back.play) === JSON.stringify([0,2,3,4,5]) &&
    swap.back.latchPos === swap.before.latchPos,
    JSON.stringify(swap.back));

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

  /* ---------- 8. 本地串口桥：真进程 + 假手套 ----------
     这一节和上面几节完全不同：串口**不在页面里**了，在 bridge.py 进程里。
     假的东西只有"对面那块板子"（fake_glove.py 用 TCP 说手套协议，
     pyserial 用 socket:// 接上去）。bridge.py、HTTP、收发线程全是真的。

     要证明的正是用户抱怨的那件事：
       「侧边栏/内嵌浏览器用不了串口」→ 现在串口压根不经过浏览器，只发 HTTP；
       「不需要模拟模式，自动选推荐串口自动连接」→ 页面打开就该自己连上，
         一次点击都不需要。 */
  console.log("\n=== 8. 本地串口桥（真 bridge.py + 假手套） ===");
  const BRIDGE_PORT = 8139, FAKE_PORT = 9702;
  const fake = spawn(PYTHON, ["-u", path.join(__dirname, "fake_glove.py"), String(FAKE_PORT)],
                     { stdio: "ignore" });
  await sleep(700);
  const bridge = spawn(PYTHON, ["-u", path.join(ROOT, "bridge.py"),
                                "--port", String(BRIDGE_PORT),
                                "--url", `socket://127.0.0.1:${FAKE_PORT}`],
                       { cwd: ROOT, stdio: "ignore" });
  const brErrors = [];
  try{
    const bp = await browser.newPage({ viewport: { width: 430, height: 900 }, deviceScaleFactor: 2 });
    bp.on("pageerror", e => brErrors.push("pageerror: " + e.message));
    bp.on("console", m => { if(m.type() === "error") brErrors.push("console.error: " + m.text()); });

    // 不带 ?sim=1 —— 用户看到的就是这个
    await bp.goto(`http://127.0.0.1:${BRIDGE_PORT}/web_piano_glove.html`, { waitUntil: "load" });

    // 「自动连接」的硬证据：全程不点任何按钮，等页面自己连上
    // ⚠️ 不能写 window.T —— 页面里 T 是顶层 const，只活在全局**词法**作用域里，
    //    压根没挂到 window 上（window.T === undefined，这条断言会永远绿不了、
    //    也永远红得莫名其妙）。要用 typeof 直接探那个词法绑定。
    let autoOk = true;
    try{
      await bp.waitForFunction(() => typeof T !== "undefined" && T.connected,
                               null, { timeout: 15000 });
    }catch(e){ autoOk = false; }
    check("打开页面后**不用点任何按钮**就自动连上了串口", autoOk,
      autoOk ? "" : await bp.textContent("#connMsg"));

    const st = await bp.evaluate(() => ({ mode: T.mode, port: T.portName, connected: T.connected,
                                          sim: SIM_ENABLED, box: $("#scanBox").className }));
    check("走的是本地桥，不是浏览器直连/模拟", st.mode === "bridge", st.mode);
    check("页面上没有 ?sim=1，模拟固件是关的", st.sim === false, st.sim);
    check("界面亮出「已连接」状态块", st.connected && st.box.includes("ok"), st.box);
    check("顶栏连接方式写「本地桥」", (await bp.textContent("#cMode")).includes("本地桥"),
      await bp.textContent("#cMode"));
    check("顶栏显示端口名", (await bp.textContent("#cConn")).includes("已连接"),
      await bp.textContent("#cConn"));

    /* 模拟模式必须从界面上彻底消失 —— 这是用户的明确要求。
       注意不能只查文案：得查 DOM 里那两个入口按钮真的不存在了。
       查正文要用 innerText，**不能用 textContent** —— textContent 会把
       <script>/<style> 里的文本也算进去，于是源码注释里那几处"模拟模式"
       会让这条断言永远红（第一次写就是这么错的）。 */
    check("界面上没有「模拟模式」入口按钮",
      (await bp.$("#mSim")) === null && (await bp.$("#mReal")) === null);
    const visibleText = await bp.$eval("body", e => e.innerText);
    check("屏幕上不再出现「模拟模式」字样",
      !/模拟模式/.test(visibleText) && !/模拟(固件|固件顶替)/.test(visibleText),
      (visibleText.match(/模拟[^\s]{0,4}/) || [""])[0]);
    check("连接页没有「选模式」这一步，只有自动连接面板",
      await bp.isVisible("#scanBox") && await bp.isVisible("#btnConn"));
    check("没有串口选择框（口由桥自己挑）",
      (await bp.$("#portSelect")) === null && (await bp.$("#baud")) === null);

    // 桥模式下 send / fire 真的走到 HTTP 上去了
    /* ⚠️ 发送必须包一层 try。没连上时 T.send 会抛，而这里抛出去会**穿过整个
       第 8 节**直到顶层 catch —— 后面上百条断言一条都不跑，日志里只剩最前面
       几条 FAIL。做变异测试时后果尤其坏：变异明明咬中了后面某条断言，
       脚本却因为"提前崩了"报「没咬住」，看起来像假绿，其实是真绿。
       所以：连不上就让它在这里红，别让它崩。 */
    const echo = await bp.evaluate(() => {
      try{ return T.send("ECHO 桥模式", 3000); }
      catch(e){ return ["（发不出去：" + String(e.message || e).slice(0, 50) + "）"]; }
    });
    check("桥模式下 send 真的从串口拿回了回复",
      echo.some(l => l.includes("OK ECHO") && l.includes("桥模式")), echo.join(" | "));
    const timing = await bp.evaluate(() => T.last);
    check("桥模式下也有往返延迟数据（测速/演奏靠它）",
      timing && typeof timing.first === "number", JSON.stringify(timing));

    /* ★ 命令聚合：演奏时一帧能产生几十条 MOVE，必须合并成一批再发。
       这是「延迟严重、声音比动作早」的根因修复 —— 逐条 HTTP POST 会被
       浏览器对同一 origin 的并发上限（6 条）排成长队：声音是 Web Audio
       当场同步响的，早就听到了，动作却还在 HTTP 队列里等。
       直接对队列施压：连甩 60 条，看它们被合并成几批。 */
    const seqBefore = await bp.evaluate(() => T.seq);
    const agg = await bp.evaluate(async () => {
      T.fireStats = {batches:0, cmds:0, maxBatch:0};
      for(let i = 0; i < 60; i++) T.fire("ECHO q" + i);
      await new Promise(r => setTimeout(r, 250));      // 等节拍把队列排空
      return {stats: T.fireStats, pending: T._q.length};
    });
    check("60 条命令被合并成远少于 60 批（批量发送生效）",
      agg.stats.cmds === 60 && agg.stats.batches > 0 && agg.stats.batches <= 6,
      `60 条 → ${agg.stats.batches} 批，单批最多 ${agg.stats.maxBatch} 条`);
    check("队列最终被排空，不会越攒越多", agg.pending === 0, agg.pending);

    /* 「回 OK」什么都不证明 —— 得数桥那边真的收到了 60 条回复行。
       否则页面自己把队列清了、命令全丢在本地，上面那条断言照样绿。 */
    let gotQ = 0;
    for(let i = 0; i < 10 && gotQ < 60; i++){
      await bp.waitForTimeout(300);
      gotQ = await bp.evaluate(async (since) => {
        const r = await fetch("/api/lines?since=" + since + "&wait=0", {cache:"no-store"});
        const j = await r.json();
        return (j.lines || []).filter(it => /OK ECHO q\d/.test(it.line)).length;
      }, seqBefore);
    }
    check("桥侧真的收到了全部 60 条（不是只在页面里合并了）", gotQ >= 60, "收到 " + gotQ + " 条");

    // 板子信息、闸门：说明整条链路是通的，不只是"连上了"
    await bp.waitForTimeout(400);
    check("桥模式下自动读出了板子信息",
      (await bp.textContent("#infoKv")).includes("PIANO_GLOVE_2"),
      (await bp.textContent("#infoKv")).slice(0, 50));
    /* ⚠️ 闸门判断前必须先切到那一页：#assignBody 在 #p-assign 里，
       而当前停在连接页 —— isVisible() 对非活动页永远返回 false。 */
    await bp.click('#tabbar button[data-p="assign"]');
    await bp.waitForTimeout(200);
    check("桥模式下后续页面的闸门被打开",
      await bp.isVisible("#assignBody") && !(await bp.isVisible("#assignGate")));
    await bp.click('#tabbar button[data-p="connect"]');
    await bp.waitForTimeout(150);

    /* 「断开」不能被自动重连当场撤销 —— 这是本节唯一一条会真去点按钮的用例，
       它照出的 bug 是：断开后自动重连循环立刻又给连回去了，按钮等于没用。 */
    await bp.click("#btnBridgeDown");
    await bp.waitForTimeout(2500);                    // 跨过好几轮自动重连
    const afterDown = await bp.evaluate(async () => {
      const r = await fetch("/api/status", { cache: "no-store" });
      const j = await r.json();
      return { pageConn: T.connected, bridgeConn: j.connected, paused: j.paused };
    });
    check("点了「断开」之后不会立刻自己连回来",
      !afterDown.pageConn && afterDown.bridgeConn === false && afterDown.paused === true,
      JSON.stringify(afterDown));

    await bp.click("#btnConn");
    await bp.waitForFunction(() => window.T && T.connected, null, { timeout: 12000 }).catch(() => {});
    const back = await bp.evaluate(async () => {
      const j = await (await fetch("/api/status", { cache: "no-store" })).json();
      return { pageConn: T.connected, bridgeConn: j.connected, paused: j.paused };
    });
    check("点「重新扫描并连接」能恢复（自动重连开关被重新打开）",
      back.pageConn && back.bridgeConn && back.paused === false, JSON.stringify(back));

    check("桥这一段没有 JS 报错", brErrors.length === 0, brErrors.slice(0, 3).join(" ; "));
    await bp.close();

    /* ------------------------------------------------------------------
       ★ 跨来源打开页面 —— 用户实际踩到的那个坑。

       页面原来只会朝**自己的来源**问 /api/status（写死的相对路径），于是：
         · 被别的本地服务器托管（内置浏览器预览）→ 问到别人家，404；
         · 直接双击 .html（file:// 来源）→ 相对路径被解析成
           file:///C:/api/status，控制台报 CORS 被拦。
       两种症状是同一句「没找到本地串口服务」，可桥明明在跑 —— 用户截图就是这个。

       现在页面按候选清单朝**绝对地址**问（见 bridgeBases()），桥也回了 CORS 头。
       这里两种来源各开一页验一遍。

       ⚠️ 必须用 ?bridge= 把地址钉死在本节的桥（8139）上，**不能靠默认清单**：
          默认清单里有 8123，而用户自己的桥多半就开在那儿 —— 一旦扫到它，
          测试就会去连真板子、真拧舵机。测试永远不许碰真硬件。
       ------------------------------------------------------------------ */
    const crossErr = [], fileErr = [];
    const cross = await browser.newPage({ viewport: { width: 430, height: 900 } });
    cross.on("pageerror", e => crossErr.push("pageerror: " + e.message));
    const CROSS_URL = `http://127.0.0.1:${PORT}/web_piano_glove.html` +
                      `?bridge=http://127.0.0.1:${BRIDGE_PORT}`;
    await cross.goto(CROSS_URL, { waitUntil: "load" });
    let crossOk = true;
    try{
      await cross.waitForFunction(() => typeof T !== "undefined" && T.connected,
                                  null, { timeout: 15000 });
    }catch(e){ crossOk = false; }
    check("页面被别的本地服务器托管（跨来源）时，照样自己找到桥并连上", crossOk,
      crossOk ? "" : await cross.textContent("#connMsg"));

    const crossSt = await cross.evaluate(() => ({ base: T.base, mode: T.mode }));
    check("走的是绝对地址，不是相对路径（相对路径正是坏掉的写法）",
      crossSt.base === `http://127.0.0.1:${BRIDGE_PORT}` && crossSt.mode === "bridge",
      JSON.stringify(crossSt));
    check("跨来源时不再报「没找到本地串口服务」",
      !/没找到本地串口服务/.test(await cross.textContent("#scanTitle")),
      await cross.textContent("#scanTitle"));

    /* POST 是跨来源里最难的一步：带 Content-Type: application/json 会先发
       OPTIONS 预检，桥不答或答得不对，整条请求就被浏览器掐掉（页面看着像连上了，
       命令却一条到不了）。所以必须让桥侧真的回一行回来才算数。
       发送包一层 try —— 没连上时 T.send 会抛，别让它把整个套件带崩：
       崩了的话变异测试只会看到「跑挂了」，认不出是哪条断言咬住的。 */
    const safeSend = async (pg, cmd) => {
      try{ return await pg.evaluate(c => T.send(c, 3000), cmd); }
      catch(e){ return ["（发不出去：" + String(e.message || e).slice(0, 60) + "）"]; }
    };
    const crossEcho = await safeSend(cross, "ECHO 跨来源");
    check("跨来源页面的命令真的走通了（POST 预检 + 响应都通）",
      crossEcho.some(l => l.includes("OK ECHO") && l.includes("跨来源")),
      crossEcho.join(" | "));

    /* file:// 是最常见的打开方式（双击），也是相对路径坏得最彻底的那种 */
    const FILE_URL = "file:///" + path.join(ROOT, "web_piano_glove.html").replace(/\\/g, "/") +
                     `?bridge=http://127.0.0.1:${BRIDGE_PORT}`;
    const filePg = await browser.newPage({ viewport: { width: 430, height: 900 } });
    filePg.on("pageerror", e => fileErr.push("pageerror: " + e.message));
    await filePg.goto(FILE_URL, { waitUntil: "load" });
    let fileOk = true;
    try{
      await filePg.waitForFunction(() => typeof T !== "undefined" && T.connected,
                                   null, { timeout: 15000 });
    }catch(e){ fileOk = false; }
    check("直接双击 .html 打开（file:// 来源）也能连上桥", fileOk,
      fileOk ? "" : await filePg.textContent("#connMsg"));
    const fileEcho = await safeSend(filePg, "ECHO 双击");
    check("file:// 来源下的命令也真的走通了",
      fileEcho.some(l => l.includes("OK ECHO") && l.includes("双击")), fileEcho.join(" | "));

    /* 候选清单本身也钉一下 —— 上面两条都靠 ?bridge= 抄了近路，
       得证明「没给地址时」它真的会去扫本机那几个端口。 */
    const bases = await cross.evaluate(() => T.bridgeBases());
    check("候选清单 = 同源 + 本机 8123~8130 的两种写法",
      bases[0] === `http://127.0.0.1:${BRIDGE_PORT}` && bases.includes("") &&
      bases.includes("http://127.0.0.1:8123") && bases.includes("http://localhost:8130"),
      bases.length + " 个：" + bases.slice(0, 3).join(" ") + " …");

    check("跨来源 / file:// 两页都没有 JS 报错",
      crossErr.length === 0 && fileErr.length === 0,
      crossErr.concat(fileErr).slice(0, 2).join(" ; "));
    await cross.close(); await filePg.close();
  }finally{
    try{ bridge.kill(); }catch(e){}
    try{ fake.kill(); }catch(e){}
    await sleep(200);
  }

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
