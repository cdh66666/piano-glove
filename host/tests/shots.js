/* 关键页面视觉抽查（视口截图，非整页） */
const { chromium } = require("playwright-core");
const http = require("http"), fs = require("fs"), path = require("path");
const ROOT = path.resolve(__dirname, "..");
const OUT  = path.join(__dirname, "shots");
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

const PORT = 8143;
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
  const pg = await b.newPage({ viewport:{width:430,height:860}, deviceScaleFactor:2 });
  pg.on("pageerror", e=>console.log("PAGEERROR:", e.message));
/* ?sim=1：调试台已经**没有**模拟模式入口了，串口默认走本机 bridge。
   这些脚本跑在没有桥的环境里（静态服务器 / file://），必须用这个自测后门
   让页面内置的假固件顶替串口，否则连接页会停在一个红色的"找不到串口服务"上。 */
  await pg.goto(`http://127.0.0.1:${PORT}/web_piano_glove.html?sim=1`);
  await pg.waitForTimeout(300);
  const shot = n => pg.screenshot({ path: path.join(OUT, n + ".png") });   // 视口截图

  await pg.click("#btnConn"); await pg.waitForTimeout(600);
  await pg.click("#btnProfile"); await pg.waitForTimeout(400);
  await pg.click('#tabbar button[data-p="assign"]'); await pg.waitForTimeout(200);
  await shot("v1-assign");

  // 快速跑完编号
  for(let i=0;i<6;i++){
    if(i>0){ await pg.click("#btnSimUnplug"); await pg.click("#btnDetect"); await pg.waitForTimeout(900);
             await pg.click("#btnSimPlug"); }
    await pg.click("#btnDetect"); await pg.waitForTimeout(900);
    await pg.click("#btnAssignNext"); await pg.waitForTimeout(1500);
  }
  await shot("v2-assign-done");

  await pg.click('#tabbar button[data-p="cal"]'); await pg.waitForTimeout(200);
  await pg.click("#btnSimBus"); await pg.click("#btnStatusAll"); await pg.waitForTimeout(700);
  await shot("v3-cal");

  await pg.fill("#calSecs","5");
  await pg.click("#btnCalStart"); await pg.waitForTimeout(7000);
  await pg.click("#btnCalSave"); await pg.waitForTimeout(800);
  await shot("v4-cal-done");

  /* 第 3C 步：拇指侧摆的「使能位」。这张卡片只有在**校准完成**之后
     才会从"先完成第 3 步"变成可操作，所以必须拍在校准之后、试动作之前。
     顺手把滑块拖到 35% 再点「记住这个位置」——拍下来的就是用户真看到的样子，
     而不是一张空壳卡片。 */
  await pg.evaluate(() => {
    const el = document.querySelector("#latchPct");
    if(el){ el.value = "35"; el.dispatchEvent(new Event("input")); }
  });
  await pg.waitForTimeout(300);
  await pg.click("#btnLatchSave"); await pg.waitForTimeout(300);
  await pg.evaluate(() => document.querySelector("#latchBody").scrollIntoView({ block: "start" }));
  await pg.waitForTimeout(250);
  await shot("v4b-latch-pos");
  console.log("3C 使能位卡片:", await pg.textContent("#latchRow"));

  await pg.click('#tabbar button[data-p="test"]'); await pg.waitForTimeout(300);
  await pg.click("#btnArm"); await pg.waitForTimeout(500);
  await shot("v5-test");

  /* 第 4 步的「两根轴对调」确认框 —— 拇指那两根轴谁按谁摆全靠它定，
     下面的槽位表也多了「名称 / 角色」两列。 */
  await pg.evaluate(() => {
    const el = document.querySelector("#roleBox"); if(el) el.scrollIntoView({ block: "start" });
  });
  await pg.waitForTimeout(250);
  await shot("v5b-role");

  await pg.click('#tabbar button[data-p="play"]'); await pg.waitForTimeout(300);
  await pg.setInputFiles("#file", path.join(HERE,"test.mid"));
  await pg.waitForTimeout(800);
  await shot("v6-midi");

  await pg.click("#btnPlay");
  await pg.waitForTimeout(260);          // 抓正在按下的瞬间
  await shot("v7-playing-a");
  await pg.waitForTimeout(1500);
  await shot("v7-playing-b");

  /* 演奏页里侧摆那一行 —— 它显示的是「使能位」而不是深度，且必须写明不参与演奏。
     这块文案是用户最容易被误导的地方（以前这里会让拇指侧摆也跟着按琴键）。 */
  await pg.evaluate(() => {
    const el = document.querySelector("#latchRow"); if(el) el.scrollIntoView({ block: "center" });
  });
  await pg.waitForTimeout(200);
  await shot("v7c-latch-row");
  await pg.click("#btnStop");

  // 窄屏手机尺寸检查
  const m = await b.newPage({ viewport:{width:360,height:740}, deviceScaleFactor:2 });
  await m.goto(`http://127.0.0.1:${PORT}/web_piano_glove.html?sim=1`);
  await m.waitForTimeout(400);
  await m.screenshot({ path: path.join(OUT,"v8-mobile-connect.png") });
  const hScroll = await m.evaluate(()=> document.documentElement.scrollWidth > window.innerWidth + 1);
  console.log("360px 窄屏出现横向滚动:", hScroll);

  await b.close(); server.close();
  console.log("视觉抽查完成");
})();
