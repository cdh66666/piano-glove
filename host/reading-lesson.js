/* 读谱小课（11-04 重做）：独立全屏窗口，在哪打开就在哪关掉，不跳页。
   每课：一张会动的图 + 一句话 + 能点能听 + 一道小题。不让手套动。 */
(function(){
'use strict';
const $=id=>document.getElementById(id);
// ---------- 声音 ----------
let ctx=null;
function audio(){try{ctx ||= new (window.AudioContext||window.webkitAudioContext)();ctx.resume?.();}catch{ctx=null;}return ctx;}
const NAMES=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
function midiOf(p){const m=/^([A-G])(#?)(\d)$/.exec(p);return m?NAMES.indexOf(m[1]+m[2])+12*(+m[3]+1):60;}
function tone(pitch,ms=600,when=0){
 const c=audio();if(!c)return;const t=c.currentTime+when/1000,f=440*2**((midiOf(pitch)-69)/12);
 const g=c.createGain();g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.32,t+.012);g.gain.exponentialRampToValueAtTime(.001,t+Math.max(.25,ms/1000)+.35);g.connect(c.destination);
 for(const [type,mul,vol] of [['triangle',1,1],['sine',2,.25]]){const o=c.createOscillator(),v=c.createGain();o.type=type;o.frequency.value=f*mul;v.gain.value=vol;o.connect(v);v.connect(g);o.start(t);o.stop(t+ms/1000+.4);}
}
function tick(when=0,strong=false){const c=audio();if(!c)return;const t=c.currentTime+when/1000,o=c.createOscillator(),g=c.createGain();o.frequency.value=strong?1500:1000;g.gain.setValueAtTime(.12,t);g.gain.exponentialRampToValueAtTime(.001,t+.05);o.connect(g);g.connect(c.destination);o.start(t);o.stop(t+.06);}
let timers=[];function later(fn,ms){timers.push(setTimeout(fn,ms));}
function stopAll(){for(const t of timers)clearTimeout(t);timers=[];document.querySelectorAll('#rl .on').forEach(e=>e.classList.remove('on'));}

// ---------- 琴键 ----------
const WHITE=['C','D','E','F','G','A','B'],SOL={C:'Do',D:'Re',E:'Mi',F:'Fa',G:'Sol',A:'La',B:'Si'};
function keyboard(from=4,octaves=2,labels=true){
 let w='',b='',x=0;
 for(let o=from;o<from+octaves;o++)for(const n of WHITE){
  const p=n+o,mid=p==='C4';
  w+=`<rect class="rl-white${mid?' rl-mid':''}" data-p="${p}" x="${x*40}" y="0" width="40" height="150" rx="4"/>`;
  if(labels)w+=`<text class="rl-klabel" x="${x*40+20}" y="128">${SOL[n]}</text>`+(mid?`<text class="rl-kmid" x="${x*40+20}" y="108">中央</text>`:'');
  if(!['E','B'].includes(n))b+=`<rect class="rl-black" data-p="${n}#${o}" x="${x*40+27}" y="0" width="26" height="92" rx="3"/>`;
  x++;
 }
 const p='C'+(from+octaves);w+=`<rect class="rl-white" data-p="${p}" x="${x*40}" y="0" width="40" height="150" rx="4"/>`+(labels?`<text class="rl-klabel" x="${x*40+20}" y="128">Do</text>`:'');x++;
 return `<svg class="rl-keys${octaves<2?' rl-keys-small':''}" viewBox="-2 -2 ${x*40+4} 154">${w}${b}</svg>`;
}
function lightKey(root,p,ms=500){const k=root.querySelector(`[data-p="${p}"]`);if(!k)return;k.classList.add('on');later(()=>k.classList.remove('on'),ms);}
function bindKeys(root,onPress){root.querySelectorAll('.rl-keys [data-p]').forEach(k=>k.onpointerdown=e=>{e.preventDefault();const p=k.dataset.p;tone(p,500);lightKey(root,p,350);onPress?.(p);});}

// ---------- 五线谱 ----------
const STEP=n=>{const m=/^([A-G])#?(\d)$/.exec(n);return WHITE.indexOf(m[1])+7*(+m[2])-(2+7*4);}; // E4 = 0（最下面一条线）
const LINE=12,BOTTOM=110;const yOf=p=>BOTTOM-STEP(p)*LINE/2;
function head(p,x,kind='q',cls=''){
 const y=yOf(p),s=STEP(p);let out='';
 for(let k=-2;k>=s;k-=2)out+=`<line class="rl-ledger" x1="${x-13}" x2="${x+13}" y1="${yOf('E4')+(-k)*LINE/2}" y2="${yOf('E4')+(-k)*LINE/2}"/>`;
 for(let k=10;k<=s;k+=2)out+=`<line class="rl-ledger" x1="${x-13}" x2="${x+13}" y1="${BOTTOM-k*LINE/2}" y2="${BOTTOM-k*LINE/2}"/>`;
 const open=kind==='w'||kind==='h',up=s<4,stem=kind==='w'?'':up?`<line class="rl-stem" x1="${x+7.5}" x2="${x+7.5}" y1="${y}" y2="${y-38}"/>`:`<line class="rl-stem" x1="${x-7.5}" x2="${x-7.5}" y1="${y}" y2="${y+38}"/>`;
 const flags={e:1,s:2}[kind]||0;let flag='';for(let i=0;i<flags;i++)flag+=up?`<path class="rl-flag" d="M${x+7.5} ${y-38+i*9} q12 8 6 22"/>`:`<path class="rl-flag" d="M${x-7.5} ${y+38-i*9} q12 -8 6 -22"/>`;
 const dot=cls.includes('dot')?`<circle class="rl-dot" cx="${x+15}" cy="${y-(s%2===0?LINE/2:0)}" r="2.6"/>`:'';
 return `<g class="rl-note ${cls}" data-p="${p}">${out}<ellipse class="rl-head${open?' open':''}" cx="${x}" cy="${y}" rx="8" ry="6" transform="rotate(-20 ${x} ${y})"/>${stem}${flag}${dot}</g>`;
}
function staff(width,inner){
 let lines='';for(let i=0;i<5;i++)lines+=`<line class="rl-line" x1="0" x2="${width}" y1="${BOTTOM-i*LINE}" y2="${BOTTOM-i*LINE}"/>`;
 return `<svg class="rl-staff" viewBox="-4 20 ${width+8} 130">${lines}<text class="rl-clef" x="2" y="${BOTTOM+9}">𝄞</text>${inner}</svg>`;
}

// ---------- 手 ----------
const FNAME=['拇指','食指','中指','无名指','小指'];
function hand(){
 const f=[[92,150,22,56,-42],[108,82,22,80,-6],[152,62,22,92,0],[196,76,22,84,6],[236,108,20,66,14]];
 return `<svg class="rl-hand" viewBox="20 30 260 230">${'<path class="rl-palm" d="M95 150 Q90 230 160 238 Q235 240 250 175 L252 150 Z"/>'}${f.map(([x,y,w,h,r],i)=>`<g class="rl-finger f${i+1}" data-f="${i+1}" transform="rotate(${r} ${x} ${y+h})"><rect x="${x-w/2}" y="${y}" width="${w}" height="${h+20}" rx="${w/2}"/><text x="${x}" y="${y+26}">${i+1}</text></g>`).join('')}</svg>`;
}

// ---------- 课 ----------
const LESSONS=[
 {title:'琴键',say:'白键 7 个一组：Do Re Mi Fa Sol La Si，然后又是 Do。点一点，听听越往右越高。',
  build(box){box.innerHTML=keyboard(4,2)+`<div class="rl-row"><button class="rl-play">▶ 听 Do 到 Do</button></div>`;bindKeys(box);
   box.querySelector('.rl-play').onclick=()=>{stopAll();['C4','D4','E4','F4','G4','A4','B4','C5'].forEach((p,i)=>later(()=>{tone(p,350);lightKey(box,p,330);},i*380));};},
  quiz:{ask:'找到「中央 Do」（左边那个标了“中央”的白键）',check:p=>p==='C4'}},
 {title:'五线谱上的音',say:'五条线从下往上数。音符越高，琴键越往右。中央 Do 在五线下面，要多画一小横线。',
  build(box){
   const ps=['C4','D4','E4','F4','G4','A4','B4','C5','D5','E5','F5','G5'];
   box.innerHTML=staff(560,ps.map((p,i)=>head(p,60+i*42,'q')).join(''))+keyboard(4,2,true);
   bindKeys(box,p=>{const n=box.querySelector(`.rl-note[data-p="${p}"]`);if(n){n.classList.add('on');later(()=>n.classList.remove('on'),400);}});
   box.querySelectorAll('.rl-note').forEach(n=>n.onpointerdown=()=>{const p=n.dataset.p;tone(p,500);lightKey(box,p,450);n.classList.add('on');later(()=>n.classList.remove('on'),450);});},
  quiz:{ask:'下面这个音，在琴键上是哪个？',pick:()=>['C4','E4','G4','A4','C5','D5','F5'][Math.floor(Math.random()*7)],
   show:p=>staff(120,head(p,70,'q','on')),check:(p,want)=>p===want}},
 {title:'手指编号',say:'谱上音符旁边的小数字 = 用哪根手指。1 拇指，2 食指，3 中指，4 无名指，5 小指。手套就是照这个数字动手指。',
  build(box){box.innerHTML=`<div class="rl-two">${hand()}<div>${staff(300,['C4','D4','E4','F4','G4'].map((p,i)=>head(p,60+i*55,'q')+`<text class="rl-fnum f${i+1}" x="${60+i*55}" y="44">${i+1}</text>`).join(''))}${keyboard(4,1,true)}</div></div><div class="rl-row"><button class="rl-play">▶ 1 2 3 4 5 弹一遍</button></div>`;
   const go=i=>{const p=['C4','D4','E4','F4','G4'][i];tone(p,420);lightKey(box,p,400);const f=box.querySelector(`.rl-finger[data-f="${i+1}"]`);f.classList.add('on');later(()=>f.classList.remove('on'),400);const n=box.querySelectorAll('.rl-note')[i];n.classList.add('on');later(()=>n.classList.remove('on'),400);};
   box.querySelectorAll('.rl-finger').forEach(f=>f.onpointerdown=()=>go(+f.dataset.f-1));
   box.querySelector('.rl-play').onclick=()=>{stopAll();for(let i=0;i<5;i++)later(()=>go(i),i*450);};},
  quiz:{ask:'谱上写「3」，用哪根手指？点手上的手指',fingers:true,check:f=>f===3}},
 {title:'音符长短',say:'一拍就是“哒”一下。黑头带杆 = 1 拍；空心带杆 = 2 拍；空心没杆 = 4 拍；带一条小尾巴 = 半拍；两条 = 四分之一拍。',
  build(box){
   const kinds=[['w',4,'全音符 4 拍'],['h',2,'二分音符 2 拍'],['q',1,'四分音符 1 拍'],['e',.5,'八分音符 半拍'],['s',.25,'十六分音符 ¼ 拍']];
   box.innerHTML=`<div class="rl-lengths">${kinds.map(([k,b,t],i)=>`<button class="rl-len" data-i="${i}">${staff(70,head('B4',40,k))}<span class="rl-bar">${Array.from({length:4},(_,j)=>`<i><b style="width:${Math.max(0,Math.min(1,b-j))*100}%"></b></i>`).join('')}</span><span>${t}</span></button>`).join('')}</div><p class="rl-hint">点一个，听它按多久（嘀 = 每一拍）</p>`;
   box.querySelectorAll('.rl-len').forEach(btn=>btn.onclick=()=>{stopAll();const [,b]=kinds[+btn.dataset.i],beat=550,repeat=b<1?Math.round(1/b):1;
    btn.classList.add('on');for(let j=0;j<4;j++)later(()=>tick(0,j===0),j*beat);
    for(let r=0;r<repeat;r++)later(()=>tone('B4',b*beat*.9),r*b*beat);later(()=>btn.classList.remove('on'),4*beat);});},
  quiz:{ask:'哪个按得最久？',choices:['四分音符','二分音符','全音符','八分音符'],check:c=>c==='全音符'}},
 {title:'休止和附点',say:'休止符 = 这一拍不弹，手放着等。音符右边的小圆点 = 再长一半：1 拍带点 = 1 拍半。',
  build(box){
   const seq=[['q','C4',1],['rest',null,1],['q','E4',1],['rest',null,1],['h','G4',3,'dot'],['q','E4',1]];
   let x=50,inner='',times=[],t=0;for(const [k,p,b,c] of seq){inner+=k==='rest'?`<path class="rl-rest" d="M${x-4} ${BOTTOM-38} l8 10 l-8 8 l8 10 q-10 -4 -6 6" />`:head(p,x,k,c||'');times.push([t,p,b,x]);t+=b;x+=k==='h'?90:60;}
   box.innerHTML=staff(x,inner+`<line class="rl-cursor" x1="0" x2="0" y1="38" y2="${BOTTOM+8}"/>`)+`<div class="rl-row"><button class="rl-play">▶ 听：哒 · 停 · 哒 · 停 · 哒——— · 哒</button></div>`;
   box.querySelector('.rl-play').onclick=()=>{stopAll();const beat=520,cur=box.querySelector('.rl-cursor');for(const [s,p,b,xx] of times)later(()=>{cur.setAttribute('x1',xx);cur.setAttribute('x2',xx);cur.classList.add('on');if(p)tone(p,b*beat*.9);},s*beat);for(let j=0;j<8;j++)later(()=>tick(0,j%4===0),j*beat);later(()=>cur.classList.remove('on'),8*beat);};},
  quiz:{ask:'2 拍的音带一个小圆点，按几拍？',choices:['2 拍','3 拍','4 拍','1 拍'],check:c=>c==='3 拍'}},
 {title:'看谱弹一小段',say:'把前面的合起来：看音高找键、看数字用手指、看形状数拍子。点播放，跟着亮光看一遍。',
  build(box){
   const tune=[['E4',3,'q'],['D4',2,'q'],['C4',1,'q'],['D4',2,'q'],['E4',3,'q'],['E4',3,'q'],['E4',3,'h'],['D4',2,'q'],['D4',2,'q'],['D4',2,'h'],['E4',3,'q'],['G4',5,'q'],['G4',5,'h']];
   let x=50,inner='';const pos=[];for(const [p,f,k] of tune){inner+=head(p,x,k)+`<text class="rl-fnum f${f}" x="${x}" y="44">${f}</text>`;pos.push(x);x+=k==='h'?66:44;}
   box.innerHTML=`<div class="rl-two">${hand()}<div>${staff(x,inner+`<line class="rl-cursor" x1="0" x2="0" y1="38" y2="${BOTTOM+8}"/>`)}${keyboard(4,1,true)}</div></div><div class="rl-row"><button class="rl-play">▶ 播放</button><label class="rl-slow"><input type="checkbox"> 慢一点</label></div>`;
   box.querySelector('.rl-play').onclick=()=>{stopAll();const beat=box.querySelector('.rl-slow input').checked?800:520,cur=box.querySelector('.rl-cursor');let t=0;
    tune.forEach(([p,f,k],i)=>{const b=k==='h'?2:1;later(()=>{tone(p,b*beat*.9);lightKey(box,p,b*beat*.8);cur.setAttribute('x1',pos[i]);cur.setAttribute('x2',pos[i]);cur.classList.add('on');const fg=box.querySelector(`.rl-finger[data-f="${f}"]`);fg.classList.add('on');later(()=>fg.classList.remove('on'),b*beat*.8);},t*beat);t+=b;});later(()=>cur.classList.remove('on'),t*beat);};},
  quiz:{ask:'最后那个空心带杆的音，按几拍？',choices:['1 拍','2 拍','4 拍'],check:c=>c==='2 拍'}}
];

// ---------- 窗口 ----------
let step=0,done=new Set(),want=null,back=null;
try{done=new Set(JSON.parse(localStorage.getItem('reading-lesson-done')||'[]'));}catch{}
function save(){try{localStorage.setItem('reading-lesson-done',JSON.stringify([...done]));}catch{}}
function build(){
 if($('rl'))return;
 const el=document.createElement('div');el.id='rl';el.hidden=true;el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');el.setAttribute('aria-label','读谱小课');
 el.innerHTML=`<div class="rl-card"><header><b>读谱小课</b><nav id="rl-tabs"></nav><button id="rl-close" type="button">关闭</button></header>
  <h2 id="rl-title"></h2><p id="rl-say"></p><div id="rl-stage"></div>
  <section id="rl-quiz"><b>小题</b><span id="rl-ask"></span><div id="rl-qbox"></div><span id="rl-result" role="status"></span></section>
  <footer><button id="rl-prev" type="button">← 上一课</button><button id="rl-next" type="button" class="rl-primary">下一课 →</button></footer></div>`;
 document.body.append(el);
 $('rl-close').onclick=close;$('rl-prev').onclick=()=>show(step-1);$('rl-next').onclick=()=>step<LESSONS.length-1?show(step+1):close();
 el.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();close();}});
 const css=document.createElement('style');css.textContent=CSS;document.head.append(css);
}
function show(i){
 stopAll();step=Math.max(0,Math.min(LESSONS.length-1,i));const L=LESSONS[step];
 $('rl-tabs').innerHTML=LESSONS.map((l,k)=>`<button type="button" class="${k===step?'cur':''}${done.has(k)?' done':''}" data-k="${k}">${done.has(k)?'✓ ':''}${k+1} ${l.title}</button>`).join('');
 $('rl-tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>show(+b.dataset.k));
 $('rl-title').textContent=(step+1)+' · '+L.title;$('rl-say').textContent=L.say;
 L.build($('rl-stage'));
 $('rl-prev').disabled=step===0;$('rl-next').textContent=step===LESSONS.length-1?'学完了':'下一课 →';
 quiz(L);
}
function quiz(L){
 const q=L.quiz,box=$('rl-qbox'),res=$('rl-result');res.textContent='';res.className='';$('rl-ask').textContent=q.ask;box.innerHTML='';
 const right=()=>{res.textContent='✓ 对了！';res.className='ok';done.add(step);save();$('rl-tabs').querySelector(`[data-k="${step}"]`)?.classList.add('done');};
 const wrong=()=>{res.textContent='再试试';res.className='no';};
 if(q.pick){want=q.pick();box.innerHTML=q.show(want)+keyboard(4,2,false);box.querySelector('.rl-note')?.addEventListener('pointerdown',()=>tone(want,500));bindKeys(box,p=>q.check(p,want)?(right(),later(()=>{if(!$('rl').hidden&&LESSONS[step]===L)quiz(L);},1200)):wrong());return;}
 if(q.choices){box.innerHTML=q.choices.map(c=>`<button type="button" class="rl-choice">${c}</button>`).join('');box.querySelectorAll('.rl-choice').forEach(b=>b.onclick=()=>q.check(b.textContent)?right():wrong());return;}
 if(q.fingers){const stage=$('rl-stage');stage.querySelectorAll('.rl-finger').forEach(f=>f.addEventListener('pointerdown',()=>q.check(+f.dataset.f)?right():wrong()));box.innerHTML='<span class="rl-hint">↑ 点上面手上的手指</span>';return;}
 // 琴键题：直接点上面的琴键
 box.innerHTML='<span class="rl-hint">↑ 点上面的琴键</span>';$('rl-stage').querySelectorAll('.rl-keys [data-p]').forEach(k=>k.addEventListener('pointerdown',()=>q.check(k.dataset.p)?right():wrong()));
}
function open(){build();back=document.activeElement;$('rl').hidden=false;document.body.classList.add('rl-open');show(step);$('rl-close').focus();}
function close(){stopAll();if(!$('rl'))return;$('rl').hidden=true;document.body.classList.remove('rl-open');back?.focus?.();}

const CSS=`
#rl{position:fixed;inset:0;z-index:300;background:#1d2733cc;display:grid;place-items:center;padding:14px}
#rl[hidden]{display:none}
#rl .rl-card{width:min(1100px,100%);max-height:100%;overflow:auto;background:#FFFBF2;border:3px solid #1d2733;border-radius:18px;box-shadow:0 10px 40px #0006;padding:14px 22px 16px;color:#1d2733;font-size:16px}
#rl header{display:flex;align-items:center;gap:12px;flex-wrap:wrap}#rl header>b{font-size:18px}
#rl-tabs{display:flex;gap:6px;flex-wrap:wrap;flex:1}
#rl-tabs button{border:2px solid #1d2733;background:#fff;border-radius:999px;padding:4px 11px;font-size:13px;font-weight:700;cursor:pointer}
#rl-tabs button.cur{background:#F2B33D}#rl-tabs button.done{color:#2f7d46}
#rl-close{border:2px solid #1d2733;border-radius:10px;background:#fff;padding:6px 14px;font-weight:800;cursor:pointer}
#rl h2{margin:12px 0 2px;font-size:24px}#rl-say{margin:0 0 10px;font-size:16px;line-height:1.6;color:#33475b}
#rl-stage{display:grid;gap:10px;justify-items:center}
#rl .rl-two{display:flex;gap:18px;align-items:center;flex-wrap:wrap;justify-content:center}
#rl .rl-keys{width:min(620px,100%);touch-action:manipulation}#rl .rl-keys-small{width:min(380px,100%)}#rl .rl-two .rl-staff{width:min(520px,100%)}#rl .rl-two>div{display:grid;gap:8px;justify-items:center}
#rl .rl-white{fill:#fff;stroke:#1d2733;stroke-width:2;cursor:pointer}#rl .rl-white.rl-mid{fill:#FFF3D1}
#rl .rl-black{fill:#1d2733;cursor:pointer}#rl .rl-white.on{fill:#9fd7a9}#rl .rl-black.on{fill:#2f9e5b}
#rl .rl-klabel{font-size:13px;font-weight:800;text-anchor:middle;fill:#5c6b7a;pointer-events:none}#rl .rl-kmid{font-size:11px;font-weight:800;text-anchor:middle;fill:#c0711b;pointer-events:none}
#rl .rl-staff{width:min(720px,100%);overflow:visible}
#rl .rl-line,#rl .rl-ledger{stroke:#1d2733;stroke-width:1.3}#rl .rl-clef{font-size:62px;fill:#1d2733}
#rl .rl-head{fill:#1d2733;stroke:#1d2733;stroke-width:1.6;cursor:pointer}#rl .rl-head.open{fill:#fff;stroke-width:2.2}
#rl .rl-stem{stroke:#1d2733;stroke-width:1.8}#rl .rl-flag{fill:none;stroke:#1d2733;stroke-width:2.4}#rl .rl-dot{fill:#1d2733}
#rl .rl-note.on .rl-head{fill:#E8590C;stroke:#E8590C}#rl .rl-note.on .rl-head.open{fill:#ffe1cc}
#rl .rl-rest{fill:none;stroke:#1d2733;stroke-width:3}
#rl .rl-cursor{stroke:#E8590C;stroke-width:3;opacity:0}#rl .rl-cursor.on{opacity:.8}
#rl .rl-fnum{font-size:15px;font-weight:900;text-anchor:middle}
#rl .f1{fill:#d1582a}#rl .f2{fill:#c9971c}#rl .f3{fill:#3b8f6a}#rl .f4{fill:#3c6fb0}#rl .f5{fill:#7a5bb5}
#rl .rl-hand{width:230px}#rl .rl-palm{fill:#ffe1c4;stroke:#1d2733;stroke-width:2}
#rl .rl-finger rect{fill:#ffe1c4;stroke:#1d2733;stroke-width:2;cursor:pointer}#rl .rl-finger text{font-size:17px;font-weight:900;text-anchor:middle;pointer-events:none}
#rl .rl-finger.on rect{fill:#F2B33D}
#rl .rl-row{display:flex;gap:12px;align-items:center}
#rl .rl-play,#rl .rl-primary{border:2.5px solid #1d2733;background:#2f9e5b;color:#fff;border-radius:12px;padding:9px 20px;font-size:16px;font-weight:900;cursor:pointer}
#rl .rl-lengths{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
#rl .rl-len{display:grid;justify-items:center;gap:4px;border:2px solid #1d2733;border-radius:12px;background:#fff;padding:6px 10px;font-weight:800;font-size:14px;cursor:pointer;width:150px}
#rl .rl-len .rl-staff{width:110px}#rl .rl-len.on{background:#FFF3D1}
#rl .rl-bar{display:flex;gap:3px}#rl .rl-bar i{width:22px;height:10px;border:1.5px solid #1d2733;border-radius:3px;overflow:hidden;background:#fff}#rl .rl-bar b{display:block;height:100%;background:#E8590C}
#rl .rl-hint{color:#6a7988;font-size:14px}
#rl-quiz{margin-top:14px;border-top:2px dashed #d7c9a8;padding-top:10px;display:grid;gap:8px;justify-items:center}
#rl-quiz>b{background:#F2B33D;border:2px solid #1d2733;border-radius:999px;padding:1px 12px}#rl-ask{font-weight:800;font-size:17px}
#rl-qbox{display:grid;gap:8px;justify-items:center}#rl-qbox .rl-staff{width:170px}
#rl .rl-choice{border:2px solid #1d2733;border-radius:10px;background:#fff;padding:7px 16px;font-size:16px;font-weight:800;margin:0 4px;cursor:pointer}
#rl-qbox:has(.rl-choice){display:flex;flex-wrap:wrap;justify-content:center}
#rl-result.ok{color:#2f7d46;font-weight:900;font-size:18px}#rl-result.no{color:#c0392b;font-weight:800}
#rl footer{display:flex;justify-content:space-between;margin-top:12px}
#rl footer button{border:2px solid #1d2733;border-radius:12px;background:#fff;padding:8px 18px;font-weight:800;font-size:15px;cursor:pointer}#rl footer button:disabled{opacity:.35}
#rl footer .rl-primary{background:#2f9e5b;color:#fff}
#rl .rl-slow{font-weight:700}
`;
window.ReadingLesson={open,close,lessons:LESSONS};
})();
