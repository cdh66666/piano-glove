/* 校对向导：看图核对。按当前音需要处理的项目画对照图，并用橙色框标出该点的控件。
   所有修改都通过原有控件完成（点按钮、改输入框），不直接改数据。 */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const LETTERS=['C','D','E','F','G','A','B'],SOLFEGE={C:'Do',D:'Re',E:'Mi',F:'Fa',G:'Sol',A:'La',B:'Si'};
const ALTER={'##':2,'#':1,'':0,b:-1,bb:-2},ALTER_TEXT={2:'##',1:'#',0:'',[-1]:'b',[-2]:'bb'},ALTER_NAME={2:'重升',1:'升',0:'',[-1]:'降',[-2]:'重降'};
const currentProject=()=>window.GloveReviewActive?.project?.()||null;
const currentNote=()=>window.GloveReviewActive?.current?.()||null;
const num=v=>typeof v==='number'&&Number.isFinite(v);

function parsePitch(text){const m=/^([A-Ga-g])(##|bb|#|b|)(-?\d+)$/.exec(String(text||'').trim());return m?{letter:m[1].toUpperCase(),alter:ALTER[m[2]],octave:Number(m[3])}:null;}
const stepIndex=p=>p.octave*7+LETTERS.indexOf(p.letter);
const fromStep=(index,alter)=>{const octave=Math.floor(index/7);return {letter:LETTERS[index-octave*7],octave,alter};};
const pitchText=p=>p.letter+ALTER_TEXT[p.alter]+p.octave;
const pitchName=p=>(ALTER_NAME[p.alter]||'')+SOLFEGE[p.letter];

// ---------- 画图 ----------
function staffSvg(clef,written,tag=''){
 const base=clef==='bass'?18:30,y=56-(stepIndex(written)-base)*4;
 const top=Math.min(14,y-12),bottom=Math.max(66,y+12);let lines='';
 for(let i=0;i<5;i++)lines+=`<line x1="4" x2="92" y1="${24+i*8}" y2="${24+i*8}"/>`;
 for(let l=16;l>=y-1;l-=8)lines+=`<line class="ledger" x1="50" x2="74" y1="${l}" y2="${l}"/>`;
 for(let l=64;l<=y+1;l+=8)lines+=`<line class="ledger" x1="50" x2="74" y1="${l}" y2="${l}"/>`;
 const sign=written.alter>0?'♯':written.alter<0?'♭':'';
 return `<svg class="guide-staff" viewBox="0 ${top} 96 ${bottom-top}" aria-hidden="true">${lines}<text class="clef" x="7" y="${clef==='bass'?46:52}">${clef==='bass'?'𝄢':'𝄞'}</text>${sign?`<text class="sign" x="42" y="${y+5}">${sign}</text>`:''}<ellipse class="head" cx="62" cy="${y}" rx="5.6" ry="4" transform="rotate(-20 62 ${y})"/><line class="stem" x1="${y>40?67.2:56.8}" x2="${y>40?67.2:56.8}" y1="${y}" y2="${y>40?y-26:y+26}"/>${tag?`<text class="tag" x="4" y="${top+10}">${tag}</text>`:''}</svg>`;
}
function noteSvg(beats,dotted){
 const open=beats>=2,stem=beats<4,flags=beats>=1?0:Math.round(Math.log2(1/beats));let parts='';
 for(let i=0;i<flags;i++)parts+=`<path class="flag" d="M21 ${6+i*7}q8 4 7 13"/>`;
 return `<svg class="guide-note" viewBox="0 0 40 46" aria-hidden="true"><ellipse class="${open?'open':'head'}" cx="15" cy="37" rx="6.6" ry="4.6" transform="rotate(-20 15 37)"/>${stem?'<line class="stem" x1="21" x2="21" y1="36" y2="6"/>':''}${parts}${dotted?'<circle class="head" cx="28" cy="37" r="2.2"/>':''}</svg>`;
}
function beatBar(beats){
 let cells='';for(let i=0;i<4;i++){const fill=Math.max(0,Math.min(1,beats-i));cells+=`<i><b style="width:${fill*100}%"></b></i>`;}
 return `<span class="guide-beats" aria-hidden="true">${cells}</span>`;
}
const beatWords=b=>({6:'6 拍',4:'4 拍',3:'3 拍',2:'2 拍',1.5:'1 拍半',1:'1 拍',.75:'3/4 拍',.5:'1/2 拍',.375:'3/8 拍',.25:'1/4 拍',.125:'1/8 拍',.188:'3/16 拍',1.333:'4/3 拍',.667:'2/3 拍',.333:'1/3 拍',.167:'1/6 拍',.083:'1/12 拍',2.667:'8/3 拍'}[b]||Math.round(b*1000)/1000+' 拍');
const relationSvg={
 simultaneous:'<svg class="guide-relation" viewBox="0 0 70 40" aria-hidden="true"><line x1="2" x2="68" y1="12" y2="12"/><line x1="2" x2="68" y1="20" y2="20"/><line x1="2" x2="68" y1="28" y2="28"/><ellipse class="head" cx="34" cy="16" rx="5" ry="3.6"/><ellipse class="now" cx="34" cy="24" rx="5" ry="3.6"/></svg>',
 after:'<svg class="guide-relation" viewBox="0 0 70 40" aria-hidden="true"><line x1="2" x2="68" y1="12" y2="12"/><line x1="2" x2="68" y1="20" y2="20"/><line x1="2" x2="68" y1="28" y2="28"/><ellipse class="head" cx="20" cy="20" rx="5" ry="3.6"/><ellipse class="now" cx="46" cy="20" rx="5" ry="3.6"/></svg>',
 start:'<svg class="guide-relation" viewBox="0 0 70 40" aria-hidden="true"><line x1="2" x2="68" y1="12" y2="12"/><line x1="2" x2="68" y1="20" y2="20"/><line x1="2" x2="68" y1="28" y2="28"/><line class="bar" x1="20" x2="20" y1="12" y2="28"/><ellipse class="now" cx="34" cy="20" rx="5" ry="3.6"/></svg>'
};
const HAND='<svg class="guide-hand" viewBox="20 0 280 225" aria-hidden="true"><path class="palm" d="M107 114Q85 153 107 193Q130 224 212 219Q271 215 279 178L287 111Z"/><path d="M113 174L61 129Q45 111 32 125Q23 138 38 152L83 195Q110 220 125 190Z"/><path d="M108 135V48Q108 31 124 31Q140 31 140 48V129Z"/><path d="M154 128V24Q154 7 171 7Q188 7 188 24V128Z"/><path d="M203 129V38Q203 21 220 21Q237 21 237 38V131Z"/><path d="M252 137V78Q252 62 268 62Q284 62 284 78V149Z"/><text x="62" y="146">1</text><text x="124" y="84">2</text><text x="171" y="70">3</text><text x="220" y="84">4</text><text x="268" y="116">5</text></svg>';

function measureTimeline(n){
 const notes=(currentProject()?.notes||[]).filter(x=>x.page===n.page&&x.system===n.system&&x.measure===n.measure&&x.hand!=='left'&&!x.excluded);
 const known=notes.filter(x=>num(x.measure_beat));
 const length=num(n.meter_beats)&&n.meter_beats>0?n.meter_beats:Math.max(4,...known.map(x=>x.measure_beat+(num(x.duration_beats)?x.duration_beats:0)));
 const W=460,unit=W/length,cells=[];
 for(let b=0;b<Math.ceil(length);b++)cells.push(`<line class="beat" x1="${b*unit}" x2="${b*unit}" y1="0" y2="58"/><text class="num" x="${(b+.5)*unit}" y="12">第${b+1}拍</text>`);
 const lanes=[],blocks=known.sort((a,b)=>a.measure_beat-b.measure_beat).map(x=>{
  const start=x.measure_beat,width=Math.max(.12,num(x.duration_beats)?x.duration_beats:.25);
  let lane=lanes.findIndex(end=>end<=start+1e-6);if(lane<0||lane>2){lane=lanes.length<3?lanes.length:2;}lanes[lane]=start+width;
  const now=x.id===n.id;return `<rect class="${now?'now':'block'}" x="${start*unit+1}" y="${17+lane*14}" width="${Math.max(6,width*unit-2)}" height="12" rx="3"/>`;
 }).join('');
 const unknown=num(n.measure_beat)?'':`<rect class="unknown" x="${W-70}" y="17" width="68" height="12" rx="3"/><text class="num" x="${W-36}" y="42">这个音的位置待定</text>`;
 return `<svg class="guide-timeline" viewBox="0 0 ${W} 60" aria-hidden="true"><rect class="frame" x=".5" y=".5" width="${W-1}" height="58" rx="5"/>${cells.join('')}${blocks}${unknown}</svg>`;
}

// ---------- 各项内容 ----------
function card(html,label,onClick,opts={}){
 const b=document.createElement('button');b.type='button';b.className='guide-card'+(opts.listen?' guide-card-listen':'')+(opts.selected?' selected':'')+(opts.suggest?' comic-do-here':'')+(opts.wide?' guide-card-wide':'');b.innerHTML=html+`<span class="guide-card-label">${label}</span>`;
 if(opts.disabled)b.disabled=true;
 // 11-04 用户：校对完一个切换下一个会卡。点的答案和原来一样时数据不变，不会自动跳；0.7 秒内还停在这个音就直接跳下一处
 b.onclick=event=>{const id=currentNote()?.id;onClick(event);if(opts.listen||opts.stay)return;setTimeout(()=>{if(id!=null&&currentNote()?.id===id&&!$('review-inspector-content')?.hidden)finish('✓ 好了');},700);};
 return b;
}
function setPitch(text){const input=$('review-pitch');if(!input)return;input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}
function pitchPanel(box,n){
 const written=parsePitch(n.written_pitch||n.pitch_candidate||n.pitch),clef=n.clef==='bass'?'bass':'treble';
 box.append(head('音符在哪条线上？','对着放大镜，点位置一样的'));
 const row=document.createElement('div');row.className='guide-row';
 if(!written){box.append(para('没认出，在下面黄框填，如 C4'));return;}
 const key=n.pitch_context?.key_signature||{},choose=p=>setPitch(pitchText(p));
 if(n.octave_shift===null||n.octave_shift===undefined){
  const up={...written,octave:written.octave+1};
  row.append(card(staffSvg(clef,written),'上面<b>没有</b><br>8va 虚线',()=>choose(written)));
  row.append(card(staffSvg(clef,written,'8va'),'上面<b>有</b><br>8va 虚线',()=>choose(up),{suggest:true}));
 }else{
  const shift=Math.round((n.octave_shift||0)/12),current=parsePitch(n.pitch);
  for(const offset of [-2,-1,0,1,2]){
   const index=stepIndex(written)+offset,shape=offset?fromStep(index,0):written;
   if(offset)shape.alter=Number(key[shape.letter]||0);
   const sounding={...shape,octave:shape.octave+shift};
   row.append(card(staffSvg(clef,shape),({'-2':'往下<br><b>2 格</b>','-1':'往下<br><b>1 格</b>','0':'<b>现在这个</b>','1':'往上<br><b>1 格</b>','2':'往上<br><b>2 格</b>'})[String(offset)],()=>choose(sounding),{selected:current&&pitchText(current)===pitchText(sounding)})); // 11-05：不写音名，按在谱上的位置说
  }
 }
 box.append(row);
}
let durationMode=null,durationNote=null;
// 11-05 用户：时值要写几拍、几分之几（看样子对照音符选，同时写清楚）
const FRACTION={4:'全音符',2:'二分音符',1:'四分音符',.5:'八分音符',.25:'十六分音符',.125:'三十二分音符'};
function durationLabel(base,mode){const beats=base*(mode==='dotted'?1.5:mode==='triplet'?2/3:1);
 const frac=(mode==='dotted'?'附点':mode==='triplet'?'三连':'')+(FRACTION[base]||'');
 return `<b>${beatWords(Math.round(beats*1000)/1000)}</b><br>${frac}`;}
function durationPanel(box,n){
 const values=window.GloveReview?.NOTE_VALUES||[],now=window.GloveReview?.noteValueFor?.(n.duration_beats)||{};
 if(durationNote!==n.id){durationNote=n.id;durationMode=now.mode&&now.mode!=='custom'?now.mode:(n.rhythm_evidence?.dots?'dotted':'plain');}
 const r=n.rhythm_evidence||{},beams=r.beams||0,base=r.head==='whole'?4:r.head==='open'?2:r.head==='filled'?1/2**beams:null;
 box.append(head('弹多长？','对着放大镜里的音，点长得一样的'));
 const row=document.createElement('div');row.className='guide-row';const factor=durationMode==='dotted'?1.5:durationMode==='triplet'?2/3:1;
 values.forEach((value,index)=>{const beats=value.beats*factor;
  row.append(card(noteSvg(value.beats,durationMode==='dotted'),durationLabel(value.beats,durationMode),()=>{$('review-value-'+durationMode)?.click();$('review-note-values')?.children[index]?.click();},{selected:num(n.duration_beats)&&Math.abs(n.duration_beats-beats)<1e-5,suggest:base===value.beats}));});

 box.append(row);
 // 两个开关：旁边有小圆点 / 头上标着 3（再点一下就关掉）
 const modes=document.createElement('div');modes.className='guide-modes guide-toggles';
 for(const [mode,text] of [['dotted','旁边有小圆点 •（附点）'],['triplet','头上标着 3（三连音）']]){
  const m=document.createElement('button');m.type='button';const on=durationMode===mode;m.innerHTML=(on?'☑ ':'☐ ')+text;m.className=on?'selected':'';m.setAttribute('aria-pressed',String(on));
  m.onclick=()=>{durationMode=durationMode===mode?'plain':mode;const value=window.GloveReview?.noteValueFor?.(n.duration_beats);const idx=values.findIndex(v=>Math.abs(v.beats-(value?.beats??-1))<1e-6);$('review-value-'+durationMode)?.click();if(idx>=0)$('review-note-values')?.children[idx]?.click();refresh(true);};
  modes.append(m);
 }
 box.append(modes);
}
// 「听这一小节」直接放在卡片里，不用去右下角找
function listenCard(row){
 const play=$('proof-listen-measure');if(!play||play.hidden)return;
 row.append(card('<span class="guide-big">▶</span>','<b>听这一小节</b>',()=>play.click(),{listen:true}));
}
// 11-05 用户：开始位置要一个看得见的对照工具——上面是这一小节的原谱，下面是拍子尺，每个音连一条线到它排的拍子。
// 线歪了就是排错了；拖橙色块（或点早一点/晚一点）微调，松手就改好。
function beatName(b){const whole=Math.floor(b+1e-6),rest=Math.round((b-whole)*100)/100;return '第 '+(whole+1)+' 拍'+({.25:'又 1/4',.5:'半',.75:'又 3/4',.33:'又 1/3',.67:'又 2/3'}[rest]||(rest?'又 '+rest:''));}
function compareTool(n,onSet){
 const p=currentProject(),img=document.querySelector('#review-row-image svg image');if(!p||!n.bbox)return null;
 const page=p.pages?.find(x=>Number(x.page)===Number(n.page)),full=$('original-image');
 const href=img?(img.getAttribute('href')||img.getAttribute('xlink:href')):(!full?.hidden?full?.src:null),ix=img?+img.getAttribute('x'):0,iy=img?+img.getAttribute('y'):0,iw=img?+img.getAttribute('width'):Number(page?.width),ih=img?+img.getAttribute('height'):Number(page?.height);
 if(!href||!(iw>0&&ih>0))return null;
 const row=p.notes.filter(x=>x.page===n.page&&x.system===n.system&&Array.isArray(x.bbox)&&!x.excluded);
 const all=row.filter(x=>x.measure===n.measure),right=all.filter(x=>x.hand!=='left');
 let x0=Math.min(...all.map(x=>x.bbox[0])),x1=Math.max(...all.map(x=>x.bbox[2]));
 const prev=row.filter(x=>x.measure<n.measure).map(x=>x.bbox[2]),next=row.filter(x=>x.measure>n.measure).map(x=>x.bbox[0]);
 x0=prev.length?Math.max(...prev)+4:Math.max(ix,x0-24);x1=next.length?Math.min(...next)-4:Math.min(ix+iw,x1+24);
 let y0=Math.max(iy,Math.min(...right.map(x=>x.bbox[1]))-26),y1=Math.min(iy+ih,Math.max(...right.map(x=>x.bbox[3]))+26);
 if(!(x1>x0&&y1>y0))return null;
 const known=right.filter(x=>num(x.measure_beat));
 const meter=num(n.meter_beats)&&n.meter_beats>0?n.meter_beats:Math.max(1,...known.map(x=>Math.ceil(x.measure_beat+(num(x.duration_beats)?x.duration_beats:0))));
 const W=1000,IMG=126;let scale=Math.min(W/(x1-x0),IMG/(y1-y0));const sx=Math.min(W/(x1-x0),scale*Math.min(2,Math.max(1,(W*.6)/((x1-x0)*scale))));/* 窄小节横向最多拉宽 2 倍 */const iwid=(x1-x0)*sx,ihgt=(y1-y0)*scale,left=(W-iwid)/2;
 const R0=148,span0=30,span1=W-30,unit=(span1-span0)/meter,tx=b=>span0+b*unit,H=200;
 const ns='http://www.w3.org/2000/svg';
 let ticks='';for(let b=0;b<=meter*4;b++){const x=tx(b/4),major=b%4===0;ticks+=`<line class="${major?'tick':'tick-minor'}" x1="${x}" x2="${x}" y1="${R0-(major?6:2)}" y2="${R0+(major?34:6)}"/>`;if(major&&b<meter*4)ticks+=`<text class="tick-num" x="${x+unit/2}" y="${R0+44}">第 ${b/4+1} 拍</text>`;}
 const lanes=[];let links='',blocks='';
 for(const x of known.sort((a,b)=>a.measure_beat-b.measure_beat||a.bbox[1]-b.bbox[1])){
  const now=String(x.id)===String(n.id),cx=left+((x.bbox[0]+x.bbox[2])/2-x0)*sx,cy=(x.bbox[3]-y0)*scale+2,bx=tx(x.measure_beat);
  let lane=lanes.findIndex(e=>e<=x.measure_beat+1e-6);if(lane<0)lane=Math.min(lanes.length,2);lanes[lane]=x.measure_beat+(num(x.duration_beats)?x.duration_beats:.25);
  const w=Math.max(10,(num(x.duration_beats)?x.duration_beats:.25)*unit-3);
  if(!now){links+=`<path class="link" d="M${cx} ${cy} L${cx} ${ihgt+8} L${bx+4} ${R0}"/>`;blocks+=`<rect class="blk" x="${bx+1}" y="${R0+2+lane*9}" width="${w}" height="7" rx="2"/>`;}
 }
 const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('class','guide-compare');
 const cx=left+((n.bbox[0]+n.bbox[2])/2-x0)*sx,cy=(n.bbox[3]-y0)*scale+2,beat0=num(n.measure_beat)?n.measure_beat:null;
 svg.innerHTML=`<rect class="paper" x="${left}" y="0" width="${iwid}" height="${ihgt}"/><svg x="${left}" y="0" width="${iwid}" height="${ihgt}" viewBox="${x0} ${y0} ${x1-x0} ${y1-y0}" preserveAspectRatio="none"><image href="${href}" x="${ix}" y="${iy}" width="${iw}" height="${ih}"/></svg>`
  +`<rect class="ring" x="${left+(n.bbox[0]-x0)*sx-4}" y="${(n.bbox[1]-y0)*scale-4}" width="${(n.bbox[2]-n.bbox[0])*sx+8}" height="${(n.bbox[3]-n.bbox[1])*scale+8}" rx="5"/>`
  +`<line class="ruler" x1="${span0}" x2="${span1}" y1="${R0}" y2="${R0}"/>${ticks}${links}${blocks}`
  +`<path class="link-now" d=""/><g class="drag"><rect class="blk-now" y="${R0-14}" height="30" rx="6"/><text class="drag-label" y="${R0-20}"></text></g>`;
 const now=svg.querySelector('.link-now'),drag=svg.querySelector('.drag'),label=svg.querySelector('.drag-label'),bnow=svg.querySelector('.blk-now');
 const dw=Math.max(26,(num(n.duration_beats)?n.duration_beats:.25)*unit-3);
 let beat=beat0??0;
 const paint=b=>{const bx=tx(b);now.setAttribute('d',`M${cx} ${cy} L${cx} ${ihgt+8} L${bx+4} ${R0-14}`);bnow.setAttribute('x',bx+1);bnow.setAttribute('width',dw);label.setAttribute('x',bx+1);label.textContent=beatName(b);};
 paint(beat);
 const others=known.filter(x=>String(x.id)!==String(n.id)).map(x=>x.measure_beat);
 const snap=b=>{const near=others.find(o=>Math.abs(o-b)<.09);let v=near??Math.round(b*4)/4;return Math.max(0,Math.min(meter-.25,v));};
 const toBeat=e=>{const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const q=pt.matrixTransform(svg.getScreenCTM().inverse());return (q.x-span0)/unit;};
 let dragging=false;
 svg.addEventListener('pointerdown',e=>{const q=toBeat(e);if(q<-.3||q>meter+.3)return;dragging=true;try{svg.setPointerCapture(e.pointerId);}catch{}beat=snap(q);paint(beat);svg.classList.add('dragging');});
 svg.addEventListener('pointermove',e=>{if(!dragging)return;beat=snap(toBeat(e));paint(beat);});
 const end=e=>{if(!dragging)return;dragging=false;svg.classList.remove('dragging');if(beat0===null||Math.abs(beat-beat0)>1e-6)onSet(beat);};
 svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);
 svg.nudge=d=>{beat=snap(Math.max(0,Math.min(meter-.25,(beat0??0)+d)));paint(beat);onSet(beat);};
 return svg;
}
function timePanel(box,n){
 const review=window.GloveReviewActive,estimate=!!review?.canAcceptEstimate?.();
 const set=b=>{if(review?.setLocalBeat?.(b))toast('✓ 改到 '+beatName(b));};
 const tool=compareTool(n,set);
 if(tool){const wrapEl=document.createElement('div');wrapEl.className='guide-compare-wrap';wrapEl.append(tool);box.append(wrapEl);}
 const row=document.createElement('div');row.className='guide-row guide-row-small';
 if(tool){
  row.append(card('<span class="guide-big">◀</span>','<b>早一点</b>',()=>tool.nudge(-.25),{stay:true}));
  row.append(card('<span class="guide-big">▶</span>','<b>晚一点</b>',()=>tool.nudge(.25),{stay:true}));
 }

 row.append(card('<span class="guide-big">✓</span>','<b>对了</b>',()=>{if(estimate&&review.acceptEstimate())finish('✓ 好了');else finish('✓ 好了');},{suggest:true,stay:true}));
 const auto=$('review-start-automatic');
 if(auto&&!auto.hidden)row.append(card('<span class="guide-big">↺</span>','<b>让软件排</b>',()=>auto.click(),{stay:true}));
 box.append(row);
}
const FINGER_NAMES=['拇指','食指','中指','无名指','小指'];
function fingerPanel(box,n){
 box.append(head('哪根手指？','点谱上印的数字'));
 const row=document.createElement('div');row.className='guide-row';
 FINGER_NAMES.forEach((name,index)=>{const finger=index+1;row.append(card(`<span class="guide-digit f${finger}">${finger}</span>`,name,()=>$('review-finger-'+finger)?.click(),{selected:n.finger===finger}));});
 box.append(row);
}
function handPanel(box){
 box.append(head('右手的音吗？','手套只弹右手'));
 const row=document.createElement('div');row.className='guide-row';
 row.append(card('<span class="guide-big">右</span>','是右手<br><b>加进来</b>',()=>$('review-hand-repair')?.click(),{suggest:true}));
 row.append(card('<span class="guide-big">左</span>','是左手<br><b>跳过</b>',()=>$('review-next-problem')?.click()));
 box.append(row,para('连着右手横梁或标 m.d. ＝ 右手'));
}
const PLAIN={slur:'谱上这几个音头顶有一条弧线，意思是连起来弹、中间不断开。',tie:'两个一样的音被弧线连着，意思是按住不松、只弹一下。',tuplet:'几个音挤在同样的时间里（比如三连音），软件已经平均分好了。',dots:'音符旁边的小圆点让它变长一半，软件已经算好了。',syncopation:'重音不在拍子上（切分音），软件已经按谱排好了。',grace:'旁边的小音符是装饰音，很快地带过去。',trill:'颤音：两个挨着的音快速来回弹。',mordent:'波音：主音和旁边的音快速来回一下。',turn:'回音：围着这个音绕一小圈。',arpeggio:'琶音：几个音从下往上一个个快速弹出来。',broken_chord:'分解和弦：几个音一个个弹出来。',staccato:'跳音：弹得短一点，马上抬起。',staccatissimo:'跳音：弹得特别短。',tenuto:'保持音：按满这个音的时间。',accent:'重音：这个音弹重一点。',fermata:'延长记号：这个音多停一会儿。',source_timing:'软件没完全看清这个音什么时候弹，按前后的音估了一个位置。',fingering:'原谱这里没印指法，软件自己排了手指。',tremolo:'震音：快速重复地弹。',glissando:'滑音：手指在琴键上滑过去。',ottava:'谱上标了 8va，要弹高（或低）一组，软件已经换算好了。',pedal:'踏板记号，手套不用管。'};
function plainFor(kind){if(!kind)return '';if(PLAIN[kind])return PLAIN[kind];const key=Object.keys(PLAIN).find(k=>kind.startsWith(k)||kind.includes(k));return key?PLAIN[key]:'';}
function performancePanel(box,n){
 const info=window.GloveReview?.performanceInfo?.(n)||{};
 box.append(head(info.label||'特殊记号',plainFor(info.kind)||'软件排好了'));
 if(info.kind==='fingering'){ /* 11-05 用户：练习指法给的“听着对/不加花样”看不懂——直接给 1～5 根手指 */
  const est=Number(info.parameters?.performance_finger)||null,row=document.createElement('div');row.className='guide-row';
  const auto=$('review-performance-auto');
  /* 11-05 用户：不要“就用软件排的”这类按钮——直接选手指，不弹就点右边「不要这个音」 */
  FINGER_NAMES.forEach((label,index)=>{const finger=index+1;row.append(card(`<span class="guide-digit f${finger}">${finger}</span>`,label,()=>$('review-finger-'+finger)?.click(),{selected:est===finger}));});
  box.append(row);return;
 }
 const row=document.createElement('div');row.className='guide-row';
 for(const [id,big,label,suggest] of [['auto','✓','听着对<br><b>就这样弹</b>',true],['written','♩','不加花样<br><b>只弹谱上的音</b>',false]]){ // 11-04 用户：“什么叫用软件的？？”；撤销顶上已有
  const control=$('review-performance-'+id);if(!control)continue;
  row.append(card(`<span class="guide-big">${big}</span>`,label,()=>{if(!control.disabled)control.click();},{suggest}));
 }
 box.append(row);
}
// 「找不同」：软件没疑问的音，也让小白直接对照原谱的指法数字。点「一样」或点了数字，都给一句提示并收起。
let tabSel='finger',tabNote=null,tabNeed=null;
// 指法：只摆 5 个数字（11-05 用户：不要多余按钮；不弹就点右边「不要这个音」）
function fingerTab(box,n,need){
 const est=Number(window.GloveReview?.performanceInfo?.(n)?.parameters?.performance_finger)||null,now=n.finger||est;
 const row=document.createElement('div');row.className='guide-row';
 FINGER_NAMES.forEach((label,index)=>{const finger=index+1;row.append(card(`<span class="guide-digit f${finger}">${finger}</span>`,label,()=>{if(n.finger===finger&&need==='next'){finish('✓ 好了');return;}$('review-finger-'+finger)?.click();if(need==='next')finish('✓ 改成 '+finger);},{selected:now===finger}));});
 box.append(row);
}
function nextPanel(box,n){
 const name=FINGER_NAMES[(n.finger||0)-1];
 box.append(head('和原谱一样吗？',name?'对照音符头顶的数字':'软件没读到数字'));
 const row=document.createElement('div');row.className='guide-row';
 row.append(card('<span class="guide-big">✓</span>',name?'<b>一样</b>':'<b>没数字</b>',()=>finish('✓ 好了'),{suggest:true}));
 FINGER_NAMES.forEach((label,index)=>{const finger=index+1;row.append(card(`<span class="guide-digit f${finger}">${finger}</span>`,label,()=>{
  if(n.finger===finger){finish('✓ 好了');return;}
  $('review-finger-'+finger)?.click();finish('✓ 改成 '+finger);
 },{selected:n.finger===finger}));});
 box.append(row);
}
// 看完一个音：提示一句，然后跳到下一处要查的；都看完就收起下面的框。
function finish(text){if(document.body.classList.contains('score-list-on')||$('convert')?.hidden){window.GloveReviewActive?.attention?.().length||window.GloveReviewActive?.close?.();return;} /* 11-05：校对页不在眼前时不弹“好了” */
 const review=window.GloveReviewActive;
 const list=review?.attention?.()||[],left=new Set(list.map(n=>review?.attentionKey?.(n)||n.id)).size; // 一样的问题算一处
 if(left){review.advance?.();toast(text+' · 还剩 '+left+' 处');} /* 11-05 用户：说好了却还剩一处——还剩几处一律写出来 */
 else{review?.close?.();toast(text+' · 都看完了');}
}
let toastTimer=null;
function toast(text){
 let t=$('comic-review-toast');
 if(!t){t=document.createElement('div');t.id='comic-review-toast';t.className='comic-review-toast';t.setAttribute('role','status');t.setAttribute('aria-live','polite');document.body.append(t);}
 t.textContent=text;t.hidden=false;t.classList.remove('show');void t.offsetWidth;t.classList.add('show');
 clearTimeout(toastTimer);toastTimer=setTimeout(()=>{t.classList.remove('show');t.hidden=true;},4200);
}

// 为什么要查这个音：几个字，说清楚是哪一处、软件哪里拿不准
function why(need,n){
 const tw=String(n.timing_warning||''),grace=/^装饰音/.test(tw),blurry=(n.automatic_reasons||[]).some(r=>/音值/.test(r));
 if(need==='duration')return grace?'小音符，谱上没写弹多长':blurry?'符号没看清，不知道弹多长':'没读出弹多长';
 if(need==='finger')return '谱上没读到指法数字';
 if(need==='performance'){const info=window.GloveReview?.performanceInfo?.(n)||{};return info.kind==='fingering'?'谱上没印指法，软件排了手指，看对不对':(info.label||'特殊记号')+'，听一下对不对';}
 if(need==='pitch')return '音高没读准';
 if(need==='hand')return '不确定是不是右手';
 if(need==='time'){if(/小节起拍/.test(tw))return '小节第一个音的位置是猜的';if(grace)return '小音符，什么时候弹是猜的';if(/估计/.test(tw))return '这小节拍子没凑齐，位置是猜的';return '弹的时间对不上';}
 return '';
}
function whyLine(need,n){
 const reason=why(need,n);if(!reason)return null;
 const d=document.createElement('div');d.className='guide-why';
 const where=Number.isFinite(n.measure)?'这一行第 '+n.measure+' 小节 · ':''; // measure 是行内序号，不是谱上印的小节号
 // 11-04 用户：要我确认什么，直接说 → 原因后面跟一句“你要做的”
 const todo={duration:'看左边放大图，点长得一样的',finger:'点音符上印的数字',pitch:'看左边放大图，点位置一样的',hand:'看左边放大图：是右手的音吗？',time:'看下面的线：每个音连到它弹的拍子，歪了就拖橙色块',performance:'不懂就点「用软件的」'}[need]||'';
 d.innerHTML=`<span class="guide-why-where">${where}上面箭头指的音</span><span class="guide-why-reason">${reason}</span>${todo?`<span class="guide-why-todo">→ ${todo}</span>`:''}`;
 return d;
}
function head(title,text){const n=document.createElement('div');n.className='guide-head';n.innerHTML=`<b>${title}</b><span>${text}</span>`;return n;}
function para(text){const p=document.createElement('p');p.className='guide-note-text';p.textContent=text;return p;}
function wrap(html){const n=document.createElement('div');n.innerHTML=html;return n;}

// ---------- 当前要做什么、该点哪里 ----------
const NEED_TARGET={
 next:()=>[] // 没问题的音不再点亮「下一处 / 回到前面待查」，免得以为必须一直点
};
function currentNeed(){
 const inspector=$('review-inspector');if(!inspector||$('review-inspector-content')?.hidden)return null;
 const repair=$('review-hand-repair');if(repair&&!repair.hidden)return 'hand';
 if(/练习估计/.test($('review-edit-instruction')?.textContent||''))return 'performance';
 const flagged=id=>$(id)?.classList.contains('review-needs-action');
 if(flagged('review-pitch-settings'))return 'pitch';
 if(flagged('review-duration-section'))return 'duration';
 if(flagged('review-time-section'))return 'time';
 if(flagged('review-finger-section'))return 'finger';
 return 'next';
}
function highlight(need){
 for(const old of document.querySelectorAll('#review-inspector .comic-do-here'))if(!old.classList.contains('guide-card'))old.classList.remove('comic-do-here');
 for(const node of NEED_TARGET[need]?.()||[]){const button=node;if(button&&!button.disabled&&!button.hidden)button.classList.add('comic-do-here');}
}
let lastKey='',lastHeight=0,expanded=false,expandedNote=null,lastNeed='',lastNeedNote=null,cooldown=null;
function refresh(force=false){
 const inspector=$('review-inspector');if(!inspector)return;
 let box=$('comic-fix-guide');
 if(!box){box=document.createElement('div');box.id='comic-fix-guide';box.className='comic-fix-guide';box.setAttribute('role','note');box.innerHTML='<div id="comic-guide-lens"></div><div id="comic-guide-body"></div>';const anchor=$('review-note-warning');(anchor?.parentElement||inspector).insertBefore(box,anchor?anchor.nextSibling:null);}
 const need=currentNeed(),n=currentNote(),body=$('comic-guide-body');
 highlight(need);
 box.hidden=!need;
 if(expandedNote!==n?.id){expandedNote=n?.id;expanded=false;}
 inspector.classList.toggle('guide-compact',!!need&&!expanded);
 if(!need){lastKey='';resizeIfNeeded(box);return;}
 const key=[need,tabSel,n?.id,n?.pitch,n?.finger,n?.duration_beats,n?.measure_beat,durationMode,expanded,n?.validation_pending,!!$('proof-listen-measure'),...['auto','written','reset'].map(id=>$('review-performance-'+id)?.disabled)].join('|');
 if(!force&&key===lastKey)return;lastKey=key;body.replaceChildren();
 // 同一个音的问题刚处理完（卡片从「要查」变成「和原谱一样吗？」）：提示一句，自动跳到下一处；都看完就收起
 if(n&&lastNeedNote===n.id&&lastNeed&&lastNeed!=='next'&&need==='next'&&!n.validation_pending&&!(window.GloveReviewActive?.attention?.()||[]).some(x=>String(x.id)===String(n.id))){lastNeed='';lastNeedNote=null;lastKey='';setTimeout(()=>finish('✓ 好了'),0);return;}
 // 同一个音刚换成另一张卡片：新按钮先停 0.8 秒，免得同一下点击落到新按钮上
 if(n&&lastNeedNote===n.id&&lastNeed&&lastNeed!==need){box.classList.add('guide-cooldown');clearTimeout(cooldown);cooldown=setTimeout(()=>box.classList.remove('guide-cooldown'),800);}
 lastNeed=need;lastNeedNote=n?.id??null;
 if(!n)return;
 /* 11-05 用户：上面一排三个按钮「指法 / 节拍 / 时值」，右边黄色闪烁写为什么要查；下面是对应的选项 */
 const perfKind=window.GloveReview?.performanceInfo?.(n)?.kind;
 const def={finger:'finger',time:'time',duration:'duration',pitch:'pitch',hand:'hand',performance:perfKind==='fingering'?'finger':'performance',next:'finger'}[need]||'finger';
 if(tabNote!==n.id){tabNote=n.id;tabNeed=need;tabSel=def;} /* 只在换音时回到默认标签；同一个音里自己点的标签不被后台刷新打断 */
 const tabs=[['finger','指法'],['time','节拍'],['duration','时值']];
 if(need==='pitch')tabs.push(['pitch','音高']);if(need==='hand')tabs.push(['hand','左右手']);if(need==='performance'&&perfKind!=='fingering')tabs.push(['performance','记号']);
 const bar=document.createElement('div');bar.className='guide-tabs';
 for(const [k,label] of tabs){const b=document.createElement('button');b.type='button';b.className='guide-tab'+(k===tabSel?' on':'')+(k===def&&need!=='next'?' need':'');b.textContent=label;b.onclick=()=>{tabSel=k;refresh(true);};bar.append(b);}
 const reason=whyLine(need,n);if(reason)bar.append(reason);
 const close=document.createElement('button');close.type='button';close.className='guide-close';close.textContent='收起';close.title='收起本音的校对框，不会改变这个音';close.onclick=()=>window.GloveReviewActive?.close?.();bar.append(close);
 body.append(bar);
 const pane=document.createElement('div');pane.className='guide-pane';body.append(pane);
 ({pitch:pitchPanel,duration:durationPanel,time:timePanel,finger:fingerTab,hand:handPanel,performance:performancePanel}[tabSel]||fingerTab)(pane,n,need);
 resizeIfNeeded(box);
}
// 上面整行：要查的音下面一个会跳的箭头。放大镜固定放在下面框的左边（11-04 用户：放大镜别挡曲谱，放下方预留位置）
let lastScrolledNote=null;
function placeMagnifier(){
 const region=$('review-score-region'),lens=$('comic-guide-lens'),box=$('comic-fix-guide');if(!region||!lens||!box)return;
 $('comic-row-magnifier')?.remove();
 if(lens.parentElement!==box)box.prepend(lens);
 let arrow=$('comic-row-arrow');
 if(!arrow){arrow=document.createElement('div');arrow.id='comic-row-arrow';arrow.setAttribute('aria-hidden','true');region.append(arrow);}
 // 试听时跟随正在响的音；停止后回到当前校对的音。
 const sounding=document.querySelector('#review-row-hits .review-row-hit.proof-now');
 const hit=sounding||document.querySelector('#review-row-hits .review-row-hit.current'),open=!!sounding||!$('review-inspector-content')?.hidden;
 let h=hit?.getBoundingClientRect();
 if(!hit||!open||!h.width){arrow.hidden=true;return;}
 // 换到新的一处：整行比框高时，把这个音滚到眼前
 if(hit.dataset.noteId!==lastScrolledNote){lastScrolledNote=hit.dataset.noteId;const rr=region.getBoundingClientRect(),y=h.top-rr.top+region.scrollTop;if(h.top<rr.top+10||h.bottom>rr.bottom-40)region.scrollTop=Math.max(0,y-40);h=hit.getBoundingClientRect();}
 const r=region.getBoundingClientRect(),st=region.scrollTop;
 arrow.hidden=false;arrow.classList.remove('mag-up');arrow.classList.add('mag-left');
 Object.assign(arrow.style,{left:(h.left-r.left-24)+'px',top:((h.top+h.bottom)/2-r.top+st-11)+'px'}); // 11-05 用户：箭头在正下方挡住看 → 放到左边指着、半透明
}
function resizeIfNeeded(box){const height=box.hidden?0:box.offsetHeight;if(height!==lastHeight){lastHeight=height;window.dispatchEvent(new Event('resize'));}}
let queued=false;
const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;refresh();placeMagnifier();});};
// 11-05 用户：版型固定；左下「送到手套」挪到上面一行，「导出曲谱」放进「更多工具」；没有要查的音时下面照样占位
function fixedLayout(){
 const source=document.querySelector('#review-workspace .review-source');
 if(source&&!$('proof-idle')){const idle=document.createElement('div');idle.id='proof-idle';idle.innerHTML='<span>软件暂无提示，请对照原谱校对</span><button type="button" id="proof-idle-next">下一行 →</button>';source.append(idle);idle.querySelector('button').onclick=()=>$('review-row-next')?.click();}
 const play=$('review-play-glove'),bar=document.querySelector('#convert .review-toolbar');
 if(play&&bar&&!play.classList.contains('moved-top')){play.classList.add('moved-top');const anchor=$('proof-guide');bar.insertBefore(play,anchor||null);}
 const playStatus=$('review-play-status');if(play&&bar&&playStatus&&playStatus.parentElement!==bar)play.after(playStatus);
 const exp=$('export'),tools=$('review-file-tools');
 if(exp&&tools&&!exp.classList.contains('moved-tools')){exp.classList.add('moved-tools');tools.append(exp);}
}
function start(){
 const inspector=$('review-inspector');if(!inspector){setTimeout(start,200);return;}
 fixedLayout();setInterval(fixedLayout,1500);
 new MutationObserver(schedule).observe(inspector,{subtree:true,attributes:true,attributeFilter:['class','hidden','disabled']});
 for(const id of ['review-selected-note','review-edit-instruction']){const node=$(id);if(node)new MutationObserver(schedule).observe(node,{childList:true,characterData:true,subtree:true});}
 const hits=$('review-row-hits');if(hits)new MutationObserver(schedule).observe(hits,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});
 window.addEventListener('resize',schedule);
 refresh();
}
if(!document.body.classList.contains('native-app'))return;
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
// 11-05：「更多」里的术语换成大白话（按钮本身和逻辑不变）
const PLAIN_WORDS=[[/^附点\s*•?$/,'带小圆点'],[/^三连音\s*3?$/,'标着 3'],[/^音值待补$/,'还没选'],[/^采用练习编排$/,'用软件排的'],[/^恢复自动$/,'撤回我的改动'],[/^接着前音$/,'前一个音弹完再弹'],[/^和前音一起$/,'和前一个音同时按'],[/^小节开头$/,'这小节最先弹'],[/^确认这拍$/,'就从这儿弹'],[/^其他设置$/,'更多选项']];
function plainWords(){for(const el of document.querySelectorAll('#review-inspector button,#review-inspector small,#review-inspector .review-edit-label,#review-inspector label>span')){if(el.children.length)continue;const t=el.textContent.trim();for(const [re,word] of PLAIN_WORDS)if(re.test(t)){el.textContent=word;break;}}
 const hint=[...document.querySelectorAll('#review-inspector small,#review-inspector p')].find(e=>/1 = 小节开头/.test(e.textContent));if(hint)hint.textContent='从这小节第几拍开始弹（1 = 第一拍，1.5 = 第一拍和第二拍中间）';}
setInterval(plainWords,800);
window.ComicGuide={refresh,toast};
})();
