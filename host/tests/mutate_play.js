/* 变异测试：确认本轮新加的断言**真的会咬人**，而不是永远绿。
 *
 * 为什么必须做这一步：一条断言如果不管代码怎么改都是绿的，那它不是测试，
 * 是装饰。做法是人为把代码改坏（一次只改一处），跑完整 e2e，
 * 看**指定的那条断言**是否变红。没红就说明它没测到东西。
 * 一次只注入一处 —— 多个变异同时上会互相掩盖（踩过）。
 *
 * ⚠️ 两个文件都是 CRLF，而下面的模式串一律用 LF 写 —— 读进来先归一，
 *    写回去再恢复，否则 find() 永远找不到（踩过）。
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const HOST = path.join(__dirname, "..");
const LOG  = path.join(__dirname, "_mut_e2e.log");

const MUTANTS = [
  { name: "命令不聚合（退回逐条立即发）",
    file: "web_piano_glove.html",
    find: "const FIRE_TICK_MS = 40;",
    repl: "const FIRE_TICK_MS = 0;",
    expect: "合并成远少于 60 批" },

  { name: "按住时长丢掉「不得短于行程」的下界",
    file: "web_piano_glove.html",
    find: "const holdReal = Math.max(stroke, Math.min(dReal * 0.9, MAX_HOLD_MS));",
    repl: "const holdReal = Math.min(dReal * 0.9, MAX_HOLD_MS);",
    expect: "按不到底" },

  { name: "槽位占用不算「松开也要时间」",
    file: "web_piano_glove.html",
    find: "busyUntil[slot] = n.t + (holdReal + stroke) * k;",
    repl: "busyUntil[slot] = n.t + holdReal * k;",
    expect: "完整周期" },

  { name: "幅度不跟力度（恒满行程）",
    file: "web_piano_glove.html",
    find: "  return 0.45 + 0.55 * Math.max(0, Math.min(1, vel || 0));",
    repl: "  return 1;",
    /* ⚠️ expect 必须是断言名里**真实存在**的片段。曾经写成"深度真的跟着力度走"，
       而断言名是"深度真的由力度算出来" —— 结果变异明明被抓住了（FAIL 就在输出里），
       脚本却报"没红"，白跑一轮。改断言文案时记得同步这里。 */
    expect: "深度真的由力度算出来" },

  { name: "「手指行程时间」这个旋钮不接进规划",
    file: "web_piano_glove.html",
    find: "  const v = el ? parseInt(el.value, 10) : NaN;",
    repl: "  const v = 90; void el;",
    expect: "行程时间」真的接进了规划" },

  { name: "声音时长退回曲谱毫秒（快曲会糊）",
    file: "web_piano_glove.html",
    find: "      if(e.on) tone(e.note, e.holdReal, e.vel);",
    repl: "      if(e.on) tone(e.note, e.durMs, e.vel);",
    expect: "声音时长用的是真实毫秒" },

  { name: "「补齐按不了的音」开关失效",
    file: "web_piano_glove.html",
    find: '    if($("#sndAll").checked && S.plan.droppedNotes){',
    repl: '    if(false && S.plan.droppedNotes){',
    expect: "补齐按不了的音」真的多出声" },

  /* ---- 拇指两轴：侧摆只使能、不演奏（2026-09-20 加） ---- */
  { name: "侧摆也被算成一根能按琴键的手指",
    file: "web_piano_glove.html",
    find: '  PLAY_SLOTS = [0,1,2,3,4,5].filter(s => ROLES[s] !== "latch");',
    repl: '  PLAY_SLOTS = [0,1,2,3,4,5];',
    expect: "侧摆槽位拿不到任何音符" },

  { name: "演奏前不把侧摆摆到使能位",
    file: "web_piano_glove.html",
    find: "  await latchEngage(true);",
    repl: "  await latchEngage(false);",
    expect: "演奏开始时侧摆恰好发一条命令" },

  { name: "使能位不核对槽位（对调角色后会串到另一根轴上）",
    file: "web_piano_glove.html",
    find: '    if(parseInt(raw[0], 10) !== LATCH_SLOT) return null;',
    repl: '    if(false) return null;',
    expect: "对调后使能位不会串到另一根轴上" },

  /* ---- 音画对齐：声音要提前提交，抵消声卡的固定延迟（2026-09-20 加） ---- */
  { name: "声音不提前提交（音画对齐补偿失效）",
    file: "web_piano_glove.html",
    find: "    const leadScore = Math.min(S.sndLead * speed, t);",
    repl: "    const leadScore = 0; void S.sndLead;",
    /* 注意这条期望的是**新加的**那条逐个音比对的断言。
       不能指望「起音数 == 声音游标按下数」去咬它 —— 补偿没了，那个等式照样成立。 */
    expect: "音画对齐：声音确实提前提交了" },

  /* ---- 跨来源找桥（2026-09-20 加）----
     用户实际踩的坑：页面被别的本地服务器托管、或直接双击 .html 打开时，
     相对路径 /api/status 打不到桥上，页面报「没找到本地串口服务」，
     可桥明明在跑（用户截图就是这个）。
     变异退回到「只朝本页来源找桥」= 原来的代码。

     ⚠️ 这一处**必须只砍非本页来源的候选**，同源那条要留着。
     第一版写的是「把整个候选循环置空」，结果同源也连不上了 ——
     第 8 节前面几条先红、`T.send` 抛异常穿过整节、脚本在跑到本条断言之前就崩了，
     于是显示「没咬住」。那不是假绿，是**变异点太粗 + 测试会崩**两件事叠在一起。
     砍成下面这样：同源照常连上，只有跨来源 / file:// 会掉。 */
  { name: "只朝本页来源找桥（跨来源 / file:// 就不认了）",
    file: "web_piano_glove.html",
    find: '    const q = new URLSearchParams(location.search).get("bridge");\n' +
          '    if(q) add(String(q).replace(/\\/+$/, ""));                    // 手工指定优先\n' +
          '    if(location.protocol === "http:" || location.protocol === "https:") add("");  // file:// 下同源没意义\n' +
          '    for(const h of ["127.0.0.1", "localhost"]){\n' +
          '      for(let p = 8123; p <= 8130; p++) add("http://" + h + ":" + p);\n' +
          '    }',
    repl: '    add("");',
    expect: "页面被别的本地服务器托管（跨来源）时" },
];

/* 只跑名字里含某个片段的变异 —— 改完一处断言后不必把 12 个都重跑一遍：
     node mutate_play.js 幅度 */
const ONLY = process.argv[2] || "";

/* 行尾保真：读进来归一成 LF 便于匹配，写回时**按原文件自己的风格**恢复。
   不能无脑转 CRLF —— 万一哪天仓库行尾变成 LF，那一次变异就会把整个文件
   的行尾全改掉，git diff 炸成整文件重写，真正的改动全被埋掉。 */
function load(p){
  const raw = fs.readFileSync(p, "utf8");
  const crlf = raw.includes("\r\n");
  return { path: p, crlf, text: crlf ? raw.replace(/\r\n/g, "\n") : raw };
}
function save(o, text){
  fs.writeFileSync(o.path, o.crlf ? text.replace(/\n/g, "\r\n") : text, "utf8");
}

/* ★ 崩溃自愈：这个脚本会把**正在开发的源码**临时改坏。
   如果它自己被杀掉（超时、Ctrl-C、外层 timeout），finally 来不及执行，
   源码就带着变异留在磁盘上 —— 下一轮会报"变异点找不到"，而且更糟的是
   你可能带着一处假改动继续开发/提交（真踩过：holdReal 的下界被留成 Math.min）。
   所以：开跑前先把原来那份存成 .mutbak，跑完删掉；下次启动看到 .mutbak
   就说明上一轮没善终，先把它还原回去再干活。 */
function backupPath(p){ return p + ".mutbak"; }
function healLeftovers(files){
  for(const p of files){
    const b = backupPath(p);
    if(fs.existsSync(b)){
      fs.copyFileSync(b, p);
      fs.unlinkSync(b);
      console.log("!! 发现上一轮残留的变异备份，已把源码还原：" + path.basename(p));
    }
  }
}
/* ★ 还原一律以**磁盘上的备份**为准，不用内存里那份 f.text。
   踩过的坑：内存还原 + 外层 SIGTERM 之后我手动 cp 回来，下一轮又被 kill，
   源码就带着第 7 处变异（`if(false && S.plan.droppedNotes)`）继续往下开发，
   一路改文案、一路没人发现，最后是 e2e 的「补齐按不了的音」断言把它抓出来的。
   教训：内存里的字符串和磁盘上的文件是两回事，还原就 copyFileSync，字节级。
   返回是否真的还原过（没备份=本来就没改，也算成功）。 */
function restoreFromBackup(p){
  const b = backupPath(p);
  if(!fs.existsSync(b)) return false;
  fs.copyFileSync(b, p);
  fs.unlinkSync(b);
  return true;
}

/* ★ 开跑前 / 收尾后都验一遍：每一处「本该在」的片段是否都还在。
   残留变异的表现是「变异点找不到」+「源码静默带毒」，光靠 heal 挡不住
   （备份本身也可能就是脏的）。这里直接把磁盘读回来核对，宁可当场停 ——
   带着一处假改动跑完 181 项、还绿着提交，才是真正的灾难。 */
function verifyClean(){
  const dirty = [];
  for(const m of MUTANTS){
    const o = load(path.join(HOST, m.file));
    if(!o.text.includes(m.find)) dirty.push(m.name + "  ← " + m.file
      + " 里找不到「" + m.find.trim().slice(0, 46) + "…」");
  }
  if(dirty.length){
    console.log("\n!! 源码不干净，先修好再跑（下面这些变异点本该存在却不在）：");
    for(const d of dirty) console.log("   ✗ " + d);
    console.log("   提示：git diff host/web_piano_glove.html 看有没有 if(false && / void el; 之类残留。");
    process.exit(2);
  }
  console.log("源码自检通过：" + MUTANTS.length + " 处变异点全部处于「正常」状态。");
}

function runE2E(){
  const fd = fs.openSync(LOG, "w");
  spawnSync(process.execPath, ["tests/e2e.js"], {
    cwd: HOST,
    env: Object.assign({}, process.env, {
      NODE_PATH: "C:/Users/admin/.workbuddy/binaries/node/workspace/node_modules"
    }),
    stdio: ["ignore", fd, fd]
  });
  fs.closeSync(fd);
  return fs.readFileSync(LOG, "utf8");
}

(function main(){
  let bad = 0;
  const run = ONLY ? MUTANTS.filter(m => m.name.includes(ONLY)) : MUTANTS;
  console.log("=== 变异测试：每条断言都必须咬人 ===" +
              (ONLY ? "（只跑含「" + ONLY + "」的 " + run.length + " 处）" : ""));
  healLeftovers([...new Set(MUTANTS.map(m => path.join(HOST, m.file)))]);
  verifyClean();
  /* ★ 被外层超时 / Ctrl-C 打断时也要还原。
     光靠 finally 挡不住 SIGTERM —— 默认行为是直接终止进程，finally 根本跑不到。
     真踩过两次：一次是 holdReal 的下界被留成 Math.min、一次是
     `if(false && …)` 静默关掉了「补齐按不了的音」开关，都在工作区里躺了一整轮
     才被 e2e 抓出来。所以信号也挂上还原。
     （Windows 上未捕获的 TerminateProcess 仍旧挡不住，那种情况靠启动时的
       healLeftovers + verifyClean 兜底。） */
  const files = [...new Set(MUTANTS.map(m => path.join(HOST, m.file)))];
  const bail = sig => { healLeftovers(files); console.log("\n!! 收到 " + sig + "，已还原源码后退出"); process.exit(130); };
  for(const sig of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"]) process.on(sig, () => bail(sig));
  for(const m of run){
    const f = load(path.join(HOST, m.file));
    if(!f.text.includes(m.find)){
      console.log("\n!! 变异点找不到（源码变了？）：" + m.name);
      bad++;
      continue;
    }
    fs.writeFileSync(backupPath(f.path), f.crlf ? f.text.replace(/\n/g, "\r\n") : f.text, "utf8");
    save(f, f.text.replace(m.find, m.repl));
    let out = "";
    try{
      out = runE2E();
    }catch(e){
      out = "跑挂了：" + e.message;
    }finally{
      restoreFromBackup(f.path);            // 以磁盘备份为准，字节级还原
    }
    const fails = out.split("\n").filter(l => l.includes("FAIL"));
    const hit = fails.some(l => l.includes(m.expect));
    console.log("\n" + (hit ? "✓ 红了" : "✗ 没红 ← 这条断言是假绿") + "  " + m.name);
    console.log("    期望变红的断言：" + m.expect);
    if(!hit){
      bad++;
      /* 多列几条，并且**明确说是不是只列了前几条** —— 只给 3 条时很容易误判成
         "这条断言根本没跑"（本轮就误判过一次：其实是变异点太粗，
         前面的断言先红、脚本中途崩了，期望那条压根没执行到）。 */
      console.log("    实际 FAIL（共 " + fails.length + " 条，下面是最多 8 条）：" +
                  (fails.length ? "\n      " + fails.slice(0, 8).join("\n      ") : "（一条都没红）"));
      if(!/全部通过|测试脚本崩溃/.test(out))
        console.log("    ⚠️ e2e 好像没跑到结尾 —— 检查是不是中途崩了（期望的断言可能压根没执行）。");
    }
  }
  try{ fs.unlinkSync(LOG); }catch(e){}
  verifyClean();                            // 收尾再验一次：确认没留毒
  console.log("\n" + (bad ? "有 " + bad + " 处没咬住 ✘" : "全部咬住 ✔"));
  process.exit(bad ? 1 : 0);
})();
