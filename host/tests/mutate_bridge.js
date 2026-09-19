/* 变异测试：把「串口桥」这几条新断言反过来验一遍。
   做法是往页面里**人为注入退化**，跑 e2e，看预期的那几条是否变红，然后还原。
   一条断言如果注入退化之后还是绿的，那它就是在自欺欺人。

   跑法： node tests/mutate_bridge.js
*/
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const HTML = path.join(__dirname, "..", "web_piano_glove.html");

const MUTANTS = [
  {
    name: "退化成「必须手点一下才连」",
    find: `    if(st.connected){
      await onBridgeUp(st);
    }else{`,
    repl: `    if(false){
      await onBridgeUp(st);
    }else if(st.connected){
      /* 变异：不自动接管，等用户点按钮 */
    }else{`,
    expect: ["打开页面后**不用点任何按钮**就自动连上了串口", "走的是本地桥"]
  },
  {
    name: "把「模拟模式」按钮加回界面",
    find: `    <div class="scanbox" id="scanBox">`,
    repl: `    <button id="mSim" class="primary">模拟模式</button>
    <div class="scanbox" id="scanBox">`,
    expect: ["界面上没有「模拟模式」入口按钮", "屏幕上不再出现「模拟模式」字样"]
  },
  {
    name: "把「断开」写成断完又自己连回来",
    find: `                if not self.connected and not self.paused:
                    self.open(self.url)`,
    repl: `                if not self.connected:
                    self.open(self.url)`,
    file: "bridge.py",
    expect: ["点了「断开」之后不会立刻自己连回来"]
  }
];

const orig = {};
function backup(rel){
  const p = path.join(__dirname, "..", rel);
  if(!(p in orig)) orig[p] = fs.readFileSync(p, "utf8");
  return p;
}
/* ⚠️ 这两个源码文件都是 CRLF 行尾，而模式串是照 LF 手写的 ——
   直接 includes() 永远 false，脚本会误报「变异点找不到（源码变了？）」。
   第一次就是这么被坑的：三条变异里两条根本没注入，却看起来像"源码变了"。 */
function toEol(text, crlf){
  return crlf ? text.split("\n").join("\r\n") : text.split("\r\n").join("\n");
}

/* 万一中途崩了，也要把源码还原回去 —— 绝不能把变异留在工作区里 */
process.on("exit", () => { for(const [p, s] of Object.entries(orig)) {
  try{ fs.writeFileSync(p, s, "utf8"); }catch(e){}
}});

let bad = 0;
for(const m of MUTANTS){
  const rel = m.file || "web_piano_glove.html";
  const p = backup(rel);
  let src = orig[p];
  const crlf = src.includes("\r\n");
  const find = toEol(m.find, crlf), repl = toEol(m.repl, crlf);
  if(!src.includes(find)){
    console.log("\n!! 变异点找不到（源码变了？）：" + m.name);
    bad++;
    continue;
  }
  fs.writeFileSync(p, src.replace(find, repl), "utf8");
  console.log("\n===== 变异：" + m.name + " =====");

  const r = spawnSync(process.execPath, [path.join(__dirname, "e2e.js")], {
    cwd: path.join(__dirname, ".."),
    encoding: "utf8",
    env: { ...process.env, NODE_PATH: process.env.NODE_PATH || "" }
  });
  const out = (r.stdout || "") + (r.stderr || "");
  fs.writeFileSync(p, orig[p], "utf8");        // 立刻还原
  delete orig[p];

  const lines = out.split("\n");
  for(const name of m.expect){
    const line = lines.find(l => l.includes(name) && (l.includes("PASS") || l.includes("FAIL")));
    const red = !!line && line.includes("FAIL");
    console.log((red ? "  抓到 ✔" : "  没抓到 ✘") + "  " + name +
                (line ? "   [" + line.trim().slice(0, 60) + "]" : "   [这条断言根本没跑到]"));
    if(!red) bad++;
  }
  const tail = lines.filter(l => l.includes("全部通过") || l.includes("失败 ")).pop();
  console.log("  e2e 小结：" + (tail || "(没跑到结尾)").trim());
}

console.log("\n" + (bad === 0
  ? "变异测试通过 ✔  每条注入的退化都被对应的断言抓住了"
  : "有 " + bad + " 处没抓到 ✘  说明对应断言是假的"));
process.exit(bad === 0 ? 0 : 1);
