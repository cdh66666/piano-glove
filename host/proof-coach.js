/* 小白校对：不会看五线谱也能校对。
   - 「▶ 听这一行」：电脑放出这一行，原谱上正在响的音和所在小节一个个亮起来；可以连着往下听。
   - 点原谱上任意一个音，马上听到它。
   - 拿不准的地方显示「第 k / N 处」，每处可以「▶ 听这一小节」，选完再听一遍。
   - 第一次打开时用三步说清楚怎么做（听一听 → 看拿不准的 → 送到手套）。
   只读曲谱数据、只用电脑声音，不改数据、不碰手套。 */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const num=v=>typeof v==='number'&&Number.isFinite(v);
const review=()=>window.GloveReviewActive||null;
const project=()=>review()?.project?.()||null;
const FINGERS=['拇指','食指','中指','无名指','小指'];
let chosen='',chosenFor=null,audio=null,voices=[],timers=[],playing=null;

// ---------- 选的文件名（O5：显示“你选的”而不只是软件认出的名字） ----------
document.addEventListener('change',event=>{if(event.target?.id==='pdf'){chosen=event.target.files?.[0]?.name||'';chosenFor=null;}},true);
function chosenName(){const p=project();if(!p||!chosen)return '';if(chosenFor===null)chosenFor=p;return chosenFor===p?chosen:'';}

// ---------- 电脑声音 ----------
function context(){const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)return null;audio ||= new Audio({latencyHint:'interactive'});audio.resume?.();return audio;}
function tone(midi,when,seconds,level=.12){
 const ctx=context();if(!ctx||!num(midi))return;const start=Math.max(ctx.currentTime,when??ctx.currentTime),freq=440*Math.pow(2,(midi-69)/12);
 const gain=ctx.createGain(),osc=ctx.createOscillator(),harm=ctx.createOscillator(),over=ctx.createGain();
 osc.type='triangle';harm.type='sine';osc.frequency.value=freq;harm.frequency.value=freq*2;over.gain.value=.15;
 osc.connect(gain);harm.connect(over);over.connect(gain);gain.connect(ctx.destination);
 const end=start+Math.max(.12,seconds);gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(level,start+.01);gain.gain.setTargetAtTime(level*.35,start+.05,.4);gain.gain.setTargetAtTime(0,end,.05);
 osc.start(start);harm.start(start);osc.stop(end+.4);harm.stop(end+.4);voices.push(osc,harm);
}
function hush(){for(const v of voices){try{v.stop();}catch{}}voices=[];}

// ---------- 原谱上的音 ----------
const playable=n=>n&&n.hand==='right'&&!n.excluded&&num(n.beat)&&n.beat>=0&&num(Number(n.midi));
function noteById(id){return (project()?.notes||[]).find(n=>String(n.id)===String(id))||null;}
function visibleNotes(){
 if(!$('review-workspace')?.classList.contains('row-review')){const row=(window.GloveReview?.rowsFor?.(project())||[]).find(r=>r.key===$('review-row-select')?.value);return (row?.notes||[]).filter(playable).sort((a,b)=>a.beat-b.beat);}
 const seen=new Set(),list=[];
 for(const hit of document.querySelectorAll('#review-row-hits [data-note-id]')){const n=noteById(hit.dataset.noteId);if(playable(n)&&!seen.has(n.id)){seen.add(n.id);list.push(n);}}
 if(list.length){const begin=Math.min(...list.map(n=>n.beat)),end=Math.max(...list.map(n=>n.beat+(num(n.duration_beats)?n.duration_beats:0))),first=list[0],wholeRow=$('review-fragments')?.hidden!==false;
  for(const n of project()?.notes||[])if(playable(n)&&String(n.id).startsWith('manual-')&&!Array.isArray(n.bbox)&&n.page===first.page&&n.system===first.system&&(wholeRow||n.beat>=begin&&n.beat<end)&&!seen.has(n.id)){seen.add(n.id);list.push(n);}}
 return list.sort((a,b)=>a.beat-b.beat);
}
const marks=id=>document.querySelectorAll('#review-row-panel [data-note-id="'+CSS.escape(String(id))+'"],#review-overlay [data-note-id="'+CSS.escape(String(id))+'"]');
function clearLit(){for(const e of document.querySelectorAll('#review-row-panel .proof-now,#review-overlay .proof-now'))e.classList.remove('proof-now');document.querySelectorAll('.proof-measure').forEach(e=>e.remove());}
function measureBand(n,notes){
 const layer=$('review-row-hits');if(!layer)return;const same=notes.filter(x=>x.page===n.page&&x.system===n.system&&x.measure===n.measure);
 let left=Infinity,right=-Infinity;for(const x of same)for(const hit of layer.querySelectorAll('[data-note-id="'+CSS.escape(String(x.id))+'"]')){const l=parseFloat(hit.style.left),w=parseFloat(hit.style.width)||0;if(num(l)){left=Math.min(left,l);right=Math.max(right,l+w);}}
 if(!num(left)||!num(right))return;const band=document.createElement('div');band.className='proof-measure';band.style.left=Math.max(0,left-1.2)+'%';band.style.width=Math.min(100,right-left+2.4)+'%';
 const label=document.createElement('span');label.textContent=Number.isFinite(n.measure)?'这一行第 '+n.measure+' 小节':'这一小节';
 band.append(label);layer.prepend(band);
}
function light(group,notes){clearLit();for(const n of group)for(const e of marks(n.id))e.classList.add('proof-now');if(group[0])measureBand(group[0],notes);
 const f=group.map(n=>n.finger).filter(v=>v>=1&&v<=5);status(f.length?'正在响 '+[...new Set(f)].map(v=>v+' '+FINGERS[v-1]).join(' + '):'正在响');}

// ---------- 播放 ----------
function speed(){return $('proof-slow')?.checked?.5:.75;} // 默认比原速慢一点，方便看清；勾「慢一点」再慢一半
function bpm(){const v=Number($('bpm')?.value);return v>=10&&v<=240?v:120;}
function stop(text=''){
 const was=playing;playing=null;for(const t of timers)clearTimeout(t);timers=[];hush();clearLit();
 if(was){$('proof-listen-row').textContent='▶ 听这一行';$('proof-listen-row').classList.remove('playing');$('proof-listen-measure')&&($('proof-listen-measure').textContent='▶ 听这一小节');}
 status(text);
}
function play(notes,{onDone,kind='row'}={}){
 stop();const ctx=context();if(!notes.length){status('这段没有音');return false;}
 const token={kind};playing=token;const sec=60/bpm()/speed(),first=notes[0].beat,t0=(ctx?ctx.currentTime:0)+.15;
 const groups=new Map();for(const n of notes){const key=Math.round((n.beat-first)*1000);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(n);}
 let last=0;for(const [key,group] of groups){const at=key/1000*sec;for(const n of group){const len=Math.max(.15,Math.min(2.5,(num(n.duration_beats)&&n.duration_beats>0?n.duration_beats:.5)*sec));tone(Number(n.midi),t0+at,len*.92);last=Math.max(last,at+len);}
  timers.push(setTimeout(()=>{if(playing===token)light(group,notes);},150+at*1000));}
 timers.push(setTimeout(()=>{if(playing!==token)return;playing=null;clearLit();if(onDone)onDone();else{status('听完了');stop(status.last);}},150+last*1000+250));
 if(kind==='row'){$('proof-listen-row').textContent='■ 停';$('proof-listen-row').classList.add('playing');}
 else if($('proof-listen-measure'))$('proof-listen-measure').textContent='■ 停';
 return true;
}
function nextRow(){
 const frag=$('review-fragment-next');if(frag&&!frag.disabled&&!$('review-fragments')?.hidden){frag.click();return true;}
 return !!review()?.openNextRow?.();
}
// 连着听：整首按一条时间线排好，提前把下一行的音排进声卡，到点再翻行 —— 换行不停顿（11-04 用户：换片段会卡）
function rowNotes(row){return (row?.notes||[]).filter(playable).sort((a,b)=>a.beat-b.beat);}
function listenRow(throughEnd=false){
 if(playing?.kind==='row'){stop('停了');return;}
 const first=visibleNotes();if(!first.length){status('这段没有音');return;}
 const go=play(first,{kind:'row',onDone:()=>{}});if(!go)return;
 const token=playing,ctx=context(),sec=60/bpm()/speed(),B0=first[0].beat,T0=(ctx?ctx.currentTime:0)+.15,started=performance.now()+150;
 const continuePlaying=throughEnd||(!document.body.classList.contains('native-app')&&!!$('proof-continue')?.checked);
 const rows=(window.GloveReview?.rowsFor?.(project())||[]).filter(r=>rowNotes(r).length);
 const curKey=first[0].page+':'+first[0].system;let index=rows.findIndex(r=>r.key===curKey);
 const at=beat=>(beat-B0)*sec; // 秒，相对开头
 let lastEnd=Math.max(...first.map(n=>at(n.beat)+Math.max(.15,(num(n.duration_beats)&&n.duration_beats>0?n.duration_beats:.5)*sec)));
 for(const t of timers.splice(0))clearTimeout(t); // 去掉 play() 里“这一行完了”的收尾，改成下面接着排
 const lightAll=(notes,list,shift=0)=>{const groups=new Map();for(const n of notes){const k=Math.round(n.beat*1000);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(n);}for(const [k,g] of groups){const ms=started-performance.now()+(at(k/1000)+shift)*1000;timers.push(setTimeout(()=>{if(playing===token)light(g,list);},Math.max(0,ms)));}};
 lightAll(first,first);
 const finish=text=>{timers.push(setTimeout(()=>{if(playing!==token)return;playing=null;clearLit();$('proof-listen-row').textContent='▶ 听这一行';$('proof-listen-row').classList.remove('playing');status(text);},Math.max(0,started-performance.now()+lastEnd*1000+250)));};
 const queueNext=()=>{
  if(playing!==token)return;
  if(!continuePlaying||index<0||index+1>=rows.length){finish(continuePlaying&&index+1>=rows.length?'整首听完了':'这一行听完了');return;}
  index++;const notes=rowNotes(rows[index]);const startSec=Math.max(at(notes[0].beat),lastEnd-.05);const shift=startSec-at(notes[0].beat);
  for(const n of notes){const len=Math.max(.15,Math.min(2.5,(num(n.duration_beats)&&n.duration_beats>0?n.duration_beats:.5)*sec));tone(Number(n.midi),T0+at(n.beat)+shift,len*.92);lastEnd=Math.max(lastEnd,at(n.beat)+shift+len);}
  // 到这一行第一个音时翻过去（声音已经排好，翻页慢一点也不断）
  timers.push(setTimeout(()=>{if(playing!==token)return;review()?.openNextRow?.();setTimeout(()=>{if(playing===token)lightAll(notes,notes,shift);},30);},Math.max(0,started-performance.now()+startSec*1000-40)));
  // 下一行开始前 1.5 秒，再排下一行
  timers.push(setTimeout(queueNext,Math.max(0,started-performance.now()+(lastEnd-1.5)*1000)));
 };
 timers.push(setTimeout(queueNext,Math.max(0,started-performance.now()+(lastEnd-1.5)*1000)));
}
function listenMeasure(){
 if(playing?.kind==='measure'){stop('停了');return;}
 const n=review()?.current?.();if(!n){status('先点一个音');return;}
 const notes=(project()?.notes||[]).filter(x=>playable(x)&&x.page===n.page&&x.system===n.system&&x.measure===n.measure).sort((a,b)=>a.beat-b.beat);
 const visible=visibleNotes();play(notes,{kind:'measure',onDone:()=>{if($('proof-listen-measure'))$('proof-listen-measure').textContent='▶ 听这一小节';status('听完了');}});
 if(!visible.length)status('正在播放这一小节');
}
function status(text){status.last=text;const e=$('proof-status');if(e)e.textContent=text||'';}

// 点原谱上的音：马上听到它（不影响原来的“点了就选中”）
document.addEventListener('pointerdown',event=>{
 const el=event.target?.closest?.('#review-row-panel [data-note-id], #review-overlay [data-note-id]');if(!el||event.button!==0)return;
 const n=noteById(el.dataset.noteId);if(!n||!num(Number(n.midi)))return;if(playing)stop();
 tone(Number(n.midi),null,.5);status(n.finger>=1&&n.finger<=5?n.finger+' '+FINGERS[n.finger-1]:'不用手指');
},true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&playing)stop('停了');},true);

// ---------- 拿不准的地方：第 k / N 处 ----------
// 11-04 用户：一样的问题算一处；再加一条进度条
function refreshIssues(){
 const box=$('proof-issues');if(!box)return;const r=review(),list=r?.attention?.()||[],cur=r?.current?.();
 const keyOf=n=>r?.attentionKey?.(n)||'one|'+n.id,keys=[...new Set(list.map(keyOf))];
 const p=project(),progress=window.GloveReview?.combinedProgress?.(p)||{checked:0,total:0,checking:false};
 const curKey=cur&&list.some(n=>String(n.id)===String(cur.id))?keyOf(cur):null,index=curKey?keys.indexOf(curKey):-1;
 box.hidden=!p;
 const percent=progress.total?(progress.checked/progress.total*100).toFixed(1)+'%':'—';
 const text=(progress.checking?'正在检查 ':'已校对 '+percent+' · ')+progress.checked+' / '+progress.total+' 音 · 软件提示 '+keys.length+' 处';
 if(box.dataset.text!==text){box.dataset.text=text;$('proof-issues-label').textContent=text;}
 const bar=$('proof-progress');if(bar){bar.max=Math.max(1,progress.total);bar.value=progress.checked;bar.title='自动检查无提示或已人工确认的音合并计数；漏识的音需要补录，软件仍可能漏掉错误。';}
 $('proof-issue-go').hidden=!keys.length||index>=0;
}


// ---------- 第一次校对：三步说明 ----------
const SEEN='piano-glove-proof-coach-seen-v1';
function seen(){try{return localStorage.getItem(SEEN)==='1';}catch{return false;}}
function markSeen(){try{localStorage.setItem(SEEN,'1');}catch{}}
function showCoach(){
 if($('proof-coach-card'))return;const card=document.createElement('div');card.id='proof-coach-card';card.className='proof-coach-card';card.setAttribute('role','dialog');card.setAttribute('aria-label','不会看谱也能校对');
 card.innerHTML='<h3>不会看谱也能校对</h3><ol>'
  +'<li><b>① ▶ 听这一行</b>：亮的音一个个往右走就对</li>'
  +'<li><b>② 去看待查的</b>：对照原谱数字和时值，拿不准可先跳过</li>'
  +'<li><b>③ ▶ 送到手套，开始弹</b></li></ol>'
  +'<p>不校对也行，直接 ③</p>'
  +'<div class="proof-coach-actions"><button type="button" id="proof-coach-try">先听第一行</button><button type="button" id="proof-coach-close">知道了</button></div>';
 document.body.append(card);
 const close=()=>{card.remove();markSeen();};
 $('proof-coach-close').onclick=close;
 $('proof-coach-try').onclick=()=>{close();review()?.openFirstRow?.();setTimeout(listenRow,350);};
}

// ---------- 装到页面上 ----------
function mount(){
 const toolbar=document.querySelector('.review-row-toolbar');if(!toolbar||$('proof-bar'))return !!toolbar;
 const bar=document.createElement('div');bar.id='proof-bar';bar.className='proof-bar';
 bar.innerHTML='<button type="button" id="proof-listen-row" class="proof-listen" title="电脑放出这一行，原谱上正在响的音会亮起来">▶ 听这一行</button>'
  +'<button type="button" id="proof-listen-first" class="proof-first" title="回到第一行，从头听整首">⏮ 从头听</button>'
  +'<label class="proof-opt" title="一行听完自动翻到下一行接着听"><input type="checkbox" id="proof-continue" checked>连着听</label>'
  /* 11-04 用户：「再慢一点」删掉 */
  +'<span id="proof-issues" class="proof-issues" hidden><progress id="proof-progress" class="proof-progress" value="0" max="1"></progress><span id="proof-issues-label"></span><button type="button" id="proof-issue-go">去看</button></span>'
  +'<span id="proof-status" class="proof-status" role="status" aria-live="polite"></span>';
 toolbar.after(bar);
 $('proof-listen-row').onclick=()=>listenRow();
 $('proof-listen-first').onclick=()=>{stop();review()?.openFirstRow?.();setTimeout(()=>{if(onReviewScreen())listenRow(true);},350);};
 // 顶上的「❓ 不会看谱？怎么校对」也打开同一份三步说明
 document.querySelector('#proof-guide>summary')?.addEventListener('click',event=>{event.preventDefault();showCoach();});
 $('proof-issue-go').onclick=()=>{stop();const first=review()?.attention?.()[0];if(first)review().select(first.id);};
 // 拿不准的那张卡片里：听这一小节
 const actions=$('review-editor-actions');
 if(actions&&!$('proof-listen-measure')){const b=document.createElement('button');b.type='button';b.id='proof-listen-measure';b.className='proof-listen-measure';b.textContent='▶ 听这一小节';b.title='电脑放出这个音所在的小节，选完一个选项可以再听一遍';b.onclick=listenMeasure;const buttons=actions.querySelector('.review-action-buttons')||actions;buttons.prepend(b);}
 // 换行、换谱时停下
 for(const id of ['review-row-prev','review-row-next','review-row-select','review-fragment-prev','review-fragment-next','pdf'])$(id)?.addEventListener(id==='review-row-select'||id==='pdf'?'change':'click',event=>{if(event.isTrusted&&playing)stop();});
 $('stop')?.addEventListener('click',()=>playing&&stop('已停下。'));
 return true;
}
let coachShown=false;
function onReviewScreen(){const ws=$('review-workspace');return !!ws&&!ws.hidden&&ws.offsetParent!==null&&document.body.classList.contains('review-view');}
document.addEventListener('click',event=>{if(playing&&event.target?.closest?.('nav button,[data-tab],[data-comic-go],#desktop-debug-open,.comic-nav button'))setTimeout(()=>{if(playing&&!onReviewScreen())stop();},50);},true);
setInterval(()=>{
 if(!mount())return;refreshIssues();
 const ws=$('review-workspace'),ready=onReviewScreen()&&!!project(); // 只在校对页弹说明
 if(ready&&!coachShown&&!seen()&&!document.body.classList.contains('proof-coach-off')){coachShown=true;showCoach();}
 if(playing&&!onReviewScreen())stop(); // 11-04 用户：切到别的界面还在响 → 停
},400);

window.GloveProof={chosenName,listenRow,listenMeasure,stop,showCoach};
})();
