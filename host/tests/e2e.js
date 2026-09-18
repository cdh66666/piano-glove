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
