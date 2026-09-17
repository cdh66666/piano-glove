/* 交叉验证：网页端解析器 vs Python 独立参考实现，逐音符比对 */
const { chromium } = require("playwright-core");
const http = require("http"), fs = require("fs"), path = require("path");
const ROOT = path.resolve(__dirname, "..");
const HERE = __dirname;
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

const PORT = 8141;
const server = http.createServer((req,res)=>{
  let p = decodeURIComponent(req.url.split("?")[0]); if(p==="/") p="/web_piano_glove.html";
  const f = path.join(ROOT,p);
  if(!fs.existsSync(f)){ res.writeHead(204); return res.end(); }
  res.writeHead(200,{"Content-Type":"text/html; charset=utf-8"});
  fs.createReadStream(f).pipe(res);
});
(async()=>{
  await new Promise(r=>server.listen(PORT,"127.0.0.1",r));
  const b = await chromium.launch({ executablePath: EXE, headless:true });
  const pg = await b.newPage();
  pg.on("pageerror", e => console.log("PAGEERROR:", e.message));
  await pg.goto(`http://127.0.0.1:${PORT}/web_piano_glove.html`);
  await pg.waitForTimeout(300);

  const buf = fs.readFileSync(path.join(HERE, "test.mid"));
  const got = await pg.evaluate((b64)=>{
    const raw = atob(b64); const u = new Uint8Array(raw.length);
    for(let i=0;i<raw.length;i++) u[i] = raw.charCodeAt(i);
    const m = window.parseMidi(u.buffer);
    return { truncated:m.truncated, notes:m.notes.map(n=>({t:Math.round(n.t), d:Math.round(n.d),
             note:n.note, vel:n.vel, ch:n.ch, tr:n.track})) };
  }, buf.toString("base64"));

  const ref = JSON.parse(fs.readFileSync(path.join(HERE,"ref.json"),"utf8"));
  const js  = got.notes.slice().sort((a,c)=> a.t-c.t || a.note-c.note);
  const py  = ref.slice().sort((a,c)=> a.t-c.t || a.note-c.note);

  console.log("\n网页端解析:", js.length, "个音符 | truncated =", got.truncated);
  console.log("Python 参考:", py.length, "个音符");

  let bad = 0;
  if(js.length !== py.length){
    console.log("  !! 音符数量不一致"); bad++;
  }
  const n = Math.min(js.length, py.length);
  for(let i=0;i<n;i++){
    const a = js[i], e = py[i];
    if(a.note!==e.note || Math.abs(a.t-e.t)>1 || Math.abs(a.d-e.d)>1 || a.vel!==e.vel){
      if(bad < 6) console.log(`  !! #${i} 网页(${a.note}@${a.t}ms d${a.d} v${a.vel}) vs 参考(${e.note}@${e.t}ms d${e.d} v${e.vel})`);
      bad++;
    }
  }
  // 时间单调性
  let mono = true;
  for(let i=1;i<js.length;i++) if(js[i].t < js[i-1].t) mono = false;

  console.log("\n逐音符差异:", bad);
  console.log("时间单调递增:", mono);
  console.log("首音符:", JSON.stringify(js[0]));
  console.log("末音符:", JSON.stringify(js[js.length-1]));
  console.log(bad===0 && mono && !got.truncated ? "\n交叉验证通过 ✔" : "\n交叉验证失败 ✘");
  await b.close(); server.close();
  process.exit(bad===0 && mono && !got.truncated ? 0 : 1);
})();
