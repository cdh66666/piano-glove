/* 漫画风桌面外壳：首页三步、角色提示、按钮说明、Esc 停止。
   只在 EXE 窗口（body.native-app）运行；不新增设备命令，所有动作都点击原有控件，
   因此开始/停止、控制权、失联不自动恢复等原逻辑保持不变。 */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const art=()=>window.ComicArt||{mascot:()=>'',icon:()=>'',burst:()=>''};
const store={get(k){try{return localStorage.getItem(k);}catch{return null;}},set(k,v){try{localStorage.setItem(k,v);}catch{}}};
const KEY_SEEN='pianoGlove.comic.welcomed.v1';
const KEY_LENS='pianoGlove.comic.lens.v1';

function el(tag,props={},html=''){const n=document.createElement(tag);for(const [k,v] of Object.entries(props)){if(k==='class')n.className=v;else if(k==='text')n.textContent=v;else n.setAttribute(k,v);}if(html)n.innerHTML=html;return n;}
function whenReady(test,run,tries=80){const value=test();if(value)return run(value);if(tries>0)setTimeout(()=>whenReady(test,run,tries-1),150);}

// ---------- 连接状态与角色心情 ----------
function connectionState(){
 const text=$('connection')?.textContent||'';
 if(/已就绪/.test(text))return 'ready';
 if(/未连接|中断|未找到|失败|无法/.test(text))return 'off';
 if(/等待舵机/.test(text))return 'servo';
 return 'wait';
}
function running(){
 const text=$('activity')?.textContent||'';
 return /演奏中|准备中|手指训练|训练中|练习中|等待到位|\d+\s*\/\s*\d+/.test(text)&&!/已停止|已完成|待机/.test(text);
}
const moods={ready:'idle',off:'worried',wait:'think',servo:'worried'};
const heroCopy={
 off:['先把手套连上吧','用 USB 数据线把手套主控接到电脑，我会自动去找它。找不到时点「USB / 驱动帮助」。不连手套也能先做 PDF 识谱校对。'],
 wait:['正在和手套打招呼…','已经发现设备，正在读取舵机、校准和曲库。稍等几秒，状态变成「已就绪」就能开始。'],
 servo:['舵机还没通电','主控已经连上，但舵机没有回应。请打开手套的舵机电源（先别戴在手上），通电后会自动就绪。编号、校准和手套里的曲谱都还在，不用重新设置。不通电也能先做 PDF 识谱校对。'],
 ready:['手套已就绪！','选一种练习开始吧。任何时候都可以点右上角红色「停止」，或者按 Esc 键。'],
 run:['动起来啦！','正在练习中。想停就点「停止」或按 Esc；断开或重启后手套不会自己再动。']
};
function refreshState(){
 const state=connectionState(),busy=running(),conn=$('connection');
 if(conn){conn.classList.toggle('comic-conn-ready',state==='ready');conn.classList.toggle('comic-conn-wait',state==='wait'||state==='servo');conn.classList.toggle('comic-conn-off',state==='off');}
 document.body.classList.toggle('comic-running',busy);
 document.body.classList.toggle('comic-servo-wait',state==='servo');
 const mood=busy?'sing':state==='ready'?'idle':moods[state];
 const brand=document.querySelector('.desktop-brand');
 if(brand&&brand.dataset.mood!==mood){brand.dataset.mood=mood;brand.querySelector('.comic-mascot')?.remove();brand.insertAdjacentHTML('afterbegin',art().mascot(mood,'钢琴手套小音'));}
 const hero=$('comic-hero-mascot');
 if(hero&&hero.dataset.mood!==(busy?'sing':state==='ready'?'happy':moods[state])){const m=busy?'sing':state==='ready'?'happy':moods[state];hero.dataset.mood=m;hero.innerHTML=art().mascot(m);}
 const copy=heroCopy[busy?'run':state];
 if($('comic-hero-title')&&$('comic-hero-title').textContent!==copy[0]){$('comic-hero-title').textContent=copy[0];$('comic-hero-text').textContent=copy[1];}
 const chip=$('comic-hero-connection');if(chip){chip.textContent=conn?.textContent||'正在读取设备';chip.title=chip.textContent;chip.className='comic-chip '+state;}
 for(const id of ['comic-hero-activity','comic-step-activity']){const act=$(id);if(act)act.textContent=$('activity')?.textContent||'待机';}
 const status=$('review-simple-status');if(status)status.classList.toggle('comic-clear',/(^|\D)0\s*(音|处|个)|无待/.test(status.textContent));
 const cont=$('comic-continue');
 if(cont){const file=$('review-current-file')?.textContent||'',left=window.GloveReviewActive?.attention?.()?.length,has=!!file&&!/先选择/.test(file)&&!$('review-workspace')?.hidden&&left!==0, /* 11-04 用户：校对完了不要一直停在开始页 */resume=null; /* 11-05 用户：别每次都显示「上次的曲谱 · 回到校对」；只在当前曲子还有没查完的时候显示 */cont.classList.toggle('available',has||!!resume);$('comic-continue-name').textContent=has?'继续校对：'+file:resume?'上次的曲谱：'+resume.name:'';}
 const again=$('comic-drop-resume');if(again){again.hidden=true;again.textContent=window.GloveResume?'继续上次：'+window.GloveResume.name:'';}
}

// ---------- 首页 ----------
function clickTab(tab){document.querySelector('.desktop-navigation [data-tab="'+tab+'"]')?.click();}
function buildHome(main){
 const home=el('section',{id:'comic-home','aria-label':'开始'});home.hidden=true;
 const I=art().icon;
 home.innerHTML=
 '<div class="comic-hero"><div id="comic-hero-mascot"></div><div class="comic-bubble"><h2 id="comic-hero-title"></h2><p id="comic-hero-text"></p></div>'+
 '<div class="comic-hero-status"><span id="comic-hero-connection" class="comic-chip">正在读取设备</span><span class="comic-activity">当前：<b id="comic-hero-activity">待机</b></span></div></div>'+
 '<div id="comic-continue" class="comic-continue">'+I('score')+'<span id="comic-continue-name"></span><button type="button" id="comic-continue-open">回到校对</button></div>'+
 '<div class="comic-steps">'+
  '<article class="comic-step"><span class="comic-step-number">1</span><h3>连上手套，按你的手调一下</h3><p>USB 插上自动连接（顶栏圆点变绿）。每个人手不一样，第一次用先点「调手套」，约 1 分钟。</p><div class="comic-step-actions">'+
   '<button type="button" id="comic-debug" class="comic-fit-hand">'+I('hand')+'调手套</button><button type="button" id="comic-usb-help">'+I('plug')+'USB / 驱动帮助</button><button type="button" id="comic-phone-help">'+I('phone')+'手机怎么连</button></div></article>'+
  '<article class="comic-step"><span class="comic-step-number">2</span><h3>选一种练习</h3><div class="comic-choice">'+
   '<button type="button" data-comic-go="train">'+I('hand')+'<b>手指训练</b><small>点手指卡片按下/抬起，或做逐指、组合、交替练习</small></button>'+
   '<button type="button" data-comic-go="library">'+I('music')+'<b>曲库跟随</b><small>选手套里的曲谱或内置曲谱，跟着原谱练</small></button>'+
   '<button type="button" data-comic-go="convert">'+I('score')+'<b>PDF 识谱校对</b><small>导入带指法的 PDF → 看问题 → 修正 → 导出或上传</small></button>'+
  '</div></article>'+
  '<article class="comic-step"><span class="comic-step-number">3</span><h3>开始与停止</h3><p>在训练或曲库页点「开始」。随时点红色「停止」或按 <b>Esc</b>。连接断开、设备重启后不会自己继续动。</p><span class="comic-activity">现在：<b id="comic-step-activity">待机</b></span><div class="comic-step-actions"><button type="button" id="comic-home-stop" class="comic-big-stop">'+I('stop')+'停止</button></div></article>'+
 '</div>'+
 '<div class="comic-tips"><strong>不会看谱？</strong><span>读谱小课从琴键和手指讲起，可随时跳过，不会让手套动。</span><button type="button" id="comic-open-guide">'+I('book')+'读谱小课</button><button type="button" id="comic-open-manual">'+I('help')+'使用说明</button><button type="button" id="comic-show-coach">再看一次入门提示</button></div>';
 main.insertBefore(home,main.querySelector(':scope>footer'));
 $('comic-usb-help').onclick=()=>{const entry=$('usbDriverHelpEntry');if(entry)entry.click();else window.NativeApp?.notice?.('usb-driver');};
 $('comic-phone-help').onclick=()=>window.NativeApp?.phoneInfo?.();
 $('comic-debug').onclick=()=>$('desktop-debug-open')?.click();
 {let fitted=false;try{fitted=localStorage.getItem('piano-hand-fitted')==='1';}catch{}$('comic-debug').classList.toggle('comic-do-here',!fitted);if(!fitted)$('comic-debug').insertAdjacentHTML('beforeend','<small class="comic-first-badge">第一次先做</small>');}
 for(const b of home.querySelectorAll('[data-comic-go]'))b.onclick=()=>clickTab(b.dataset.comicGo);
 $('comic-home-stop').onclick=()=>$('stop')?.click();
 $('comic-continue-open').onclick=()=>{if(window.GloveResume)return window.GloveResume.open();clickTab('convert');window.ScoreList?.hide?.();};
 $('comic-open-guide').onclick=()=>{if(window.ReadingLesson){window.ReadingLesson.open();return;} /* 11-04：读谱小课独立窗口，不再跳到 PDF 识谱 */const home=$('comic-home-tab'),fromHome=!!home&&(home.classList.contains('selected')||home.getAttribute('aria-current')==='page'||!!document.querySelector('#comic-home:not([hidden])')),back=document.querySelector('.desktop-navigation [data-tab].selected')?.dataset.tab;clickTab('convert');setTimeout(()=>$('review-help')?.click(),30);const ret=fromHome?()=>home.click():back&&back!=='convert'?()=>clickTab(back):null;if(ret)$('guide-close')?.addEventListener('click',()=>setTimeout(ret,0),{once:true});};
 $('comic-open-manual').onclick=()=>{const link=document.querySelector('.desktop-settings a[href^="guide.html"]');if(link)link.click();};
 $('comic-show-coach').onclick=()=>coach(true);
 return home;
}
function setHome(on){
 const home=$('comic-home'),button=$('comic-home-tab');if(!home)return;
 if(on){if(document.body.classList.contains('playing-view'))return;clickTab('train');for(const b of document.querySelectorAll('.desktop-navigation [data-tab]'))b.classList.remove('selected');}
 home.hidden=!on;document.body.classList.toggle('comic-home-view',on);button?.classList.toggle('selected',on);button?.setAttribute('aria-current',on?'page':'false');
 refreshState();
}

// ---------- 按钮说明 ----------
function caption(button,title,hint){if(!button||button.querySelector('small'))return;button.textContent='';button.append(document.createTextNode(title));const s=el('small',{text:hint});button.append(s);button.title=hint;}
function hint(target,text,after=false){if(!target||target.parentElement?.querySelector(':scope>.comic-hint[data-for="'+target.id+'"]'))return;const n=el('small',{class:'comic-hint','data-for':target.id||'',text});after?target.after(n):target.append(n);}
function decorate(){
 const nav=document.querySelector('.desktop-navigation');
 const icons={train:'hand',library:'music',convert:'score'};
 for(const b of nav?.querySelectorAll('[data-tab]')||[]){if(!b.querySelector('.comic-icon'))b.insertAdjacentHTML('afterbegin',art().icon(icons[b.dataset.tab]));}
 const convert=$('convert-tab');if(convert){const t=[...convert.childNodes].find(n=>n.nodeType===3);if(t)t.textContent='PDF 识谱';}
 if(nav&&!$('comic-home-tab')){const home=el('button',{type:'button',id:'comic-home-tab',title:'开始：连接、选练习、停止的说明'});home.innerHTML=art().icon('home')+'开始';home.onclick=()=>setHome(true);nav.prepend(home);}
 // 顶栏说明
 const debug=$('desktop-debug-open');if(debug&&nav&&debug.parentElement!==nav)nav.append(debug);if(debug){debug.title='按你的手调手套、试一试动作';if(!debug.querySelector('.comic-icon'))debug.insertAdjacentHTML('afterbegin',art().icon('wrench'));}
 const settings=$('desktop-settings-open');if(settings)settings.title='设置：设备信息、驱动帮助、手机连接、使用说明';
 const stop=$('stop');if(stop&&!stop.querySelector('.comic-icon')){stop.insertAdjacentHTML('afterbegin',art().icon('stop'));stop.insertAdjacentHTML('beforeend','<span class="comic-key" aria-hidden="true">Esc</span>');stop.title='立即停止手套动作（键盘 Esc 也可以）';stop.setAttribute('aria-keyshortcuts','Escape');}
 // 训练
 caption($('fastest-training'),'最快速度','速度直接拉到 1000%');
 const patterns={single:['逐指练习','五指轮流按下抬起'],combination:['组合练习','多指组合按下'],alternating:['交替练习','手指交替按下']};
 for(const b of document.querySelectorAll('#train [data-pattern]')){const p=patterns[b.dataset.pattern];if(p)caption(b,p[0],p[1]);}
 const heading=$('feedback-panel')?.querySelector('.heading');
 if(heading&&!heading.querySelector('.comic-subtitle'))heading.querySelector('h2')?.after(el('span',{class:'comic-subtitle',text:'点一下手指卡片：按下；再点一下：抬起。可以同时按几根。'}));
 const train=$('train')?.querySelector('h2');if(train&&!train.nextElementSibling?.classList?.contains('comic-subtitle'))train.after(el('span',{class:'comic-subtitle',text:'选好次数后点一种练习开始；「最快速度」把速度拉到 1000%。'}));
 // 参数
 const tempo=$('tempo')?.closest('label');
 if(tempo){const caption=tempo.querySelector('.desktop-range-caption>span');if(caption&&caption.textContent==='速度')caption.textContent='速度（节奏倍率）';hint(tempo,'曲谱与练习的节拍快慢，100% 为原速；不改变舵机本身转速。');}
 hint($('amplitude')?.closest('label'),'按下有多深：占已校准行程的百分比，100% 走满。');
 hint(document.querySelector('.settings .sound'),'电脑本地播放琴声，不影响手套动作。');hint(document.querySelector('.settings .sound-offset'),'琴声比手指早就往右调（延后），晚就往左调（提前）。');
 const parameters=document.querySelector('.desktop-parameters>h2');if(parameters&&!parameters.querySelector('.comic-icon'))parameters.insertAdjacentHTML('afterbegin',art().icon('gear'));
 // 曲库
 const library=$('library')?.querySelector('.heading h2');if(library&&!library.nextElementSibling?.classList?.contains('comic-subtitle'))library.after(el('span',{class:'comic-subtitle',text:'手套里存的曲谱：点「开始训练」跟着练。'}));
 const max=$('max-score-tempo');if(max)max.title='把速度一次设成 1000%（10 倍节奏）';
 const refresh=$('refresh');if(refresh)refresh.title='重新读取手套里的曲库';
}
function capacityBar(){
 const node=$('capacity');if(!node)return;
 const m=node.textContent.match(/(\d+)\s*\/\s*(\d+)\s*首/);
 let bar=node.querySelector('.comic-capacity-bar');
 if(!m){bar?.remove();return;}
 if(!bar){bar=el('span',{class:'comic-capacity-bar','aria-hidden':'true'},'<i></i>');node.append(bar);}
 bar.firstChild.style.width=Math.min(100,Number(m[1])/Math.max(1,Number(m[2]))*100)+'%';
}
// 还没打开曲谱时，直接在空白页选内置原谱（原下拉框在收起的工具面板里，这里只是它的入口）
function builtinPicker(){
 const source=$('native-score-catalog')?.matches?.('select')?$('native-score-catalog'):$('native-score-catalog')?.querySelector('select');
 const actions=document.querySelector('.comic-drop-actions');if(!source||!actions)return;
 let picker=$('comic-drop-picker');
 if(!picker){picker=el('select',{id:'comic-drop-picker','aria-label':'选择内置原谱'});actions.after(picker);picker.onchange=()=>{if(!picker.value)return;source.value=picker.value;source.dispatchEvent(new Event('change',{bubbles:true}));};}
 picker.replaceChildren(...[...source.children].map(n=>n.cloneNode(true)));picker.value='';picker.focus();try{picker.showPicker?.();}catch{}
}
function dropBlank(){
 const blank=$('native-drop-blank');if(!blank||blank.dataset.comic)return !!blank;
 blank.dataset.comic='1';const I=art().icon;
 blank.insertAdjacentHTML('afterbegin',art().mascot('think','小音'));
 const actions=el('div',{class:'comic-drop-actions'},'<button type="button" id="comic-drop-choose">'+I('folder')+'选择 PDF</button><button type="button" id="comic-drop-builtin">'+I('music')+'打开内置原谱</button><button type="button" id="comic-drop-review">'+I('upload')+'继续复核文件</button><button type="button" id="comic-drop-resume" hidden></button>');
 blank.append(actions,el('p',{class:'comic-drop-note',text:'适合从网上下载的电子版五线谱（音符上印着指法数字），可一次拖入多份；拍照或扫描的谱子不一定能认。认完会标出拿不准的地方，不放心可以对照原谱改。'}));
 $('comic-drop-choose').onclick=()=>$('pdf')?.click();
 $('comic-drop-builtin').onclick=builtinPicker;
 const entry=$('native-builtin-entry');if(entry){const openTools=entry.onclick;entry.onclick=event=>{if(document.body.classList.contains('review-view'))return openTools?.(event);clickTab('convert');builtinPicker();};}
 $('comic-drop-review').onclick=()=>$('review-file')?.click();
 $('comic-drop-resume').onclick=()=>window.GloveResume?.open();
 return true;
}
let fingerFrame=0;
function tagFingers(){fingerFrame=0;for(const label of document.querySelectorAll('#review-row-annotations .review-row-label')){const d=(label.textContent||'').trim().match(/^[1-5]/);const v=d&&!label.classList.contains('unfingered')?d[0]:'';if((label.dataset.finger||'')!==v){if(v)label.dataset.finger=v;else delete label.dataset.finger;}}}
function rangeFill(){for(const input of document.querySelectorAll('body.native-app input[type=range]')){const min=Number(input.min||0),max=Number(input.max||100),v=Number(input.value);const p=max>min?Math.max(0,Math.min(100,(v-min)/(max-min)*100)):0;input.style.setProperty('--fill',p.toFixed(1)+'%');}}

// ---------- 首次入门提示（可关闭，不强制） ----------
function coach(force=false){
 if(!force&&store.get(KEY_SEEN))return;
 $('comic-coach')?.remove();
 const box=el('aside',{id:'comic-coach',class:'comic-coach',role:'status','aria-live':'polite'});
 box.innerHTML=art().mascot('happy','小音')+'<div class="comic-bubble"><b>嗨，我是小音！</b><br>第一次用：① 点「调手套」按你的手调一下，② 选一种练习。<br>想停：红色「停止」或 Esc。<br><button type="button" id="comic-coach-close">知道了</button></div>';
 document.body.append(box);
 const close=()=>{store.set(KEY_SEEN,'1');box.remove();};
 $('comic-coach-close').onclick=close;
 setTimeout(()=>{if(document.body.contains(box)&&!force)close();},20000);
}

// ---------- Esc 停止 ----------
function escapeStop(event){
 if(event.key!=='Escape'||event.defaultPrevented||event.repeat)return;
 // 弹窗多为 fixed 定位，offsetParent 恒为 null，要用 getClientRects 判断是否可见；有弹窗时把 Esc 留给弹窗自己关闭。
 const open=[...document.querySelectorAll('[role=dialog],[aria-modal=true],dialog[open],.score-guide')].some(d=>!d.hidden&&d.getClientRects().length>0&&!d.contains($('stop')));
 if(open)return;
 if(document.activeElement?.closest?.('#review-inspector'))return;
 // 不靠界面文字判断是否在运动：文字一变就会漏停。空闲时多发一次停止没有害处。
 const stop=$('stop');if(!stop||stop.disabled)return;
 event.preventDefault();stop.click();
}


function mount(){
 const body=document.body;
 if(!body.classList.contains('native-app')||body.dataset.comicShell==='ready')return;
 body.dataset.comicShell='ready';body.classList.add('comic-theme');
 const main=body.querySelector(':scope>main');if(!main)return;
 decorate();buildHome(main);
 // 原标签被选中（含程序切换，如打开曲谱）时自动离开首页
 const nav=document.querySelector('.desktop-navigation');
 if(nav)new MutationObserver(()=>{if(document.body.classList.contains('comic-home-view')&&nav.querySelector('[data-tab].selected'))setHome(false);}).observe(nav,{subtree:true,attributes:true,attributeFilter:['class']});
 for(const id of ['connection','activity','review-simple-status','review-current-file'])whenReady(()=>$(id),n=>new MutationObserver(refreshState).observe(n,{childList:true,characterData:true,subtree:true}));
 whenReady(()=>$('review-workspace'),n=>new MutationObserver(refreshState).observe(n,{attributes:true,attributeFilter:['hidden']}));
 whenReady(()=>$('capacity'),n=>{const obs=new MutationObserver(()=>{obs.disconnect();capacityBar();obs.observe(n,{childList:true,characterData:true,subtree:true});});capacityBar();obs.observe(n,{childList:true,characterData:true,subtree:true});});
 whenReady(()=>$('review-row-annotations'),n=>new MutationObserver(()=>{if(!fingerFrame)fingerFrame=requestAnimationFrame(tagFingers);}).observe(n,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['class']}));
 whenReady(()=>$('native-drop-blank'),dropBlank);
 whenReady(()=>$('review-row-select'),select=>{const on=()=>store.get(KEY_LENS)!=='off',b=el('button',{type:'button',id:'comic-lens-toggle',title:'在当前音旁边放大显示原谱，方便看清指法和音符'});b.textContent='放大镜';const paint=()=>{b.setAttribute('aria-pressed',String(on()));document.body.classList.toggle('comic-no-lens',!on());};b.onclick=()=>{store.set(KEY_LENS,on()?'off':'on');paint();};select.parentElement.append(b);paint();});
 whenReady(()=>$('native-ready-play'),b=>{if(!b.querySelector('.comic-icon'))b.insertAdjacentHTML('afterbegin',art().icon('play'));const s=$('native-ready-select');if(s)s.title='这些内置曲谱已整首核对，选好即可播放';});
 document.addEventListener('keydown',escapeStop);
 document.addEventListener('input',e=>{if(e.target?.type==='range')rangeFill();});
 setInterval(rangeFill,700);rangeFill();
 refreshState();setInterval(refreshState,1000);
 // 首次使用（没有入门记录）落在「开始」页；之后保持上次恢复的标签页。
 if(!store.get(KEY_SEEN)){setTimeout(()=>{setHome(true);coach();},400);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
window.ComicShell={home:setHome,coach,refresh:refreshState};
})();

// 11-05 用户：舵机一直使能（用力）不动会嗡嗡响 → 停着用力超过 15 秒，屏幕中间弹提示并响三声，一键全部松开
(()=>{
 'use strict';
 const HOLD_MS=15000,REPEAT_MS=30000;let stillSince=null,shownAt=0,box=null,snoozeUntil=0,audio=null;
 function beep(){try{const A=window.AudioContext||window.webkitAudioContext;if(!A)return;audio||=new A();audio.resume?.();const t=audio.currentTime+.05;for(let i=0;i<3;i++){const o=audio.createOscillator(),g=audio.createGain();o.type='square';o.frequency.value=988;o.connect(g);g.connect(audio.destination);const s=t+i*.32;g.gain.setValueAtTime(0,s);g.gain.linearRampToValueAtTime(.18,s+.01);g.gain.setValueAtTime(.18,s+.18);g.gain.linearRampToValueAtTime(0,s+.2);o.start(s);o.stop(s+.22);}}catch{}}
 function hide(){if(box){box.remove();box=null;}}
 function show(){
  if(!box){
   box=document.createElement('div');box.id='servo-hold-alert';box.setAttribute('role','alertdialog');
   box.style.cssText='position:fixed;inset:0;z-index:2147481000;display:flex;align-items:center;justify-content:center;background:rgba(35,33,43,.3);font-family:"Microsoft YaHei UI",sans-serif;pointer-events:none';
   box.innerHTML='<div style="pointer-events:auto;background:#FFF4E5;border:3px solid #E8590C;border-radius:18px;box-shadow:6px 6px 0 #23212b;padding:26px 32px;max-width:min(460px,88vw);text-align:center;color:#23212b"><div style="font-size:44px;line-height:1">🔊</div><b style="display:block;font-size:22px;margin:8px 0 6px">手套一直在用力</b><span style="display:block;font-size:15px;margin-bottom:18px">舵机停着用力会嗡嗡响、发热。不用了就松开。</span><div style="display:flex;gap:12px;justify-content:center"><button type="button" data-act="keep" style="min-width:120px;min-height:46px;border:2px solid #23212b;border-radius:12px;background:#fff;font-size:16px;font-weight:900;cursor:pointer">还要按着</button><button type="button" data-act="release" style="min-width:140px;min-height:46px;border:2px solid #23212b;border-radius:12px;background:#E8590C;color:#fff;font-size:17px;font-weight:900;cursor:pointer;box-shadow:2px 2px 0 #23212b">全部松开</button></div></div>';
   box.addEventListener('click',e=>{const act=e.target.closest?.('button')?.dataset.act;if(act==='release'){document.getElementById('stop')?.click();hide();stillSince=null;}else if(act==='keep'){snoozeUntil=performance.now()+REPEAT_MS*2;hide();}});
   document.body.append(box);
  }
  beep();shownAt=performance.now();
 }
 window.addEventListener('glove-state',e=>{
  const s=e.detail||{},now=performance.now();
  const holding=!!s.active&&!s.moving_mask&&!(s.duration_ms>0&&s.elapsed_ms>0&&s.elapsed_ms<s.duration_ms); // 在用力、手指都不动、也不是在播曲子
  if(!holding){stillSince=null;hide();return;}
  stillSince??=now;
  if(now-stillSince<HOLD_MS||now<snoozeUntil)return;
  if(!box||now-shownAt>REPEAT_MS)show();
 });
})();

// 11-05 用户：换了新主控就用不了 → 软件自己认出手套程序旧了/没有，弹框一键更新（独立升级器，校准和曲谱保留）
(function firmwareWatch(){
 if(!document.body?.classList?.contains('native-app'))return;
 const key=v=>{const m=/^(\d+)\.(\d+)\.(\d+)(?:-r(\d+)(?:\.(\d+))?)?$/.exec(String(v||''));return m?m.slice(1).map(x=>+(x||0)):null;};
 const older=(a,b)=>{for(let i=0;i<5;i++){if(a[i]!==b[i])return a[i]<b[i];}return false;};
 // 11-05 用户：固件要起正常版本名，点开能看是什么时候的、改了什么，还要有主动更新的按钮
 const RELEASES={'r29.2':['v1.0','2026-11-02',['第一版漫画界面配套固件','舵机掉线时不死机']],
  'r29.3':['v1.1','2026-11-03',['等舵机通电时，手套里的曲子照样能用']],
  'r29.4':['v1.2','2026-11-03',['手机上“最快速度”直接拉到最快']],
  'r29.6':['v1.3','2026-11-03',['手机热点弹快曲子不再断连']],
  'r29.8':['v1.4','2026-11-05',['修好有几根手指动得慢（按下的力度恢复成满力）']]};
 const rel=v=>{const r=/r\d+(?:\.\d+)?/.exec(String(v||''))?.[0]||'';return RELEASES[r]||[String(v||'?').replace(/^\d+\.\d+\.\d+-/,''),'',[]];};
 window.__fwName=v=>rel(v)[0];
 let info=null,asked=new Set();
 async function check(){
  const link=window.__gloveLink;if(!link||!link.connected||Date.now()-link.at>15000)return;
  if(!info){try{const api=await NativeApp.ready;info=await api.firmware_upgrade_info();}catch{info={available:false};}}
  if(!info.available)return;
  const ver=/(?:^|\s)ver=(\S+)/.exec(link.info)?.[1]||'',ours=/fw=PIANO_GLOVE/.test(link.info);
  if(!link.info&&!ours)return;
  const want=key(info.version),have=key(ver);
  const need=!ours?'none':have&&want&&older(have,want)?'old':null;if(!need)return;
  const tag=need+':'+ver;if(asked.has(tag))return;asked.add(tag);
  show(need,ver);
 }
 function show(need,ver){
  let box=document.getElementById('fw-upgrade');if(box)box.remove();
  box=document.createElement('div');box.id='fw-upgrade';box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');
  const [haveName,haveDate,haveNotes]=rel(ver),[wantName,wantDate,wantNotes]=rel(info?.version),newer=need!=='info'||(info?.available&&key(ver)&&key(info.version)&&older(key(ver),key(info.version)));
  const list=a=>a.length?'<ul>'+a.map(t=>'<li>'+t+'</li>').join('')+'</ul>':'';
  box.innerHTML=`<div class="fwu-card"><h2>${need==='info'?'手套固件 '+haveName:'手套固件需要更新'}</h2>${need==='none'?'<p>这块主控里还没有钢琴手套的固件。</p>':`<p class="fwu-ver"><b>现在：${haveName}</b>${haveDate?' · '+haveDate:''}</p>${list(haveNotes)}`}${info?.available?(newer?`<p class="fwu-ver"><b>新版：${wantName}</b>${wantDate?' · '+wantDate:''}</p>${list(wantNotes)}`:'<p class="fwu-ok">✓ 已经是最新版</p>'):'<p class="fwu-small">没找到「固件升级」文件夹（放在软件旁边才能更新）。</p>'}<p class="fwu-small">点「更新固件」，约 1 分钟，别拔线。舵机会先松开（戴着也没关系）；编号、校准和曲谱都保留，不用重开软件。</p><div class="fwu-bar" hidden><i></i></div><div class="fwu-actions"><button type="button" class="fwu-go"${info?.available?'':' disabled'}>${newer?'更新固件':'再写一遍（修复用）'}</button><button type="button" class="fwu-later">${need==='info'?'关闭':'以后再说'}</button></div><p class="fwu-err" role="status"></p></div>`;
  document.body.append(box);
  box.querySelector('.fwu-later').onclick=()=>box.remove();
  box.querySelector('.fwu-go').onclick=async()=>{ // 11-05 用户：更新固件不要重启软件——在软件里直接升级、显示进度、完了自动重连
   const err=box.querySelector('.fwu-err'),bar=box.querySelector('.fwu-bar'),fill=bar.querySelector('i'),go=box.querySelector('.fwu-go'),later=box.querySelector('.fwu-later');
   go.disabled=later.disabled=true;bar.hidden=false;err.textContent='正在让舵机松开…';
   try{const api=await NativeApp.ready;await api.firmware_upgrade_start();
    for(;;){await new Promise(r=>setTimeout(r,500));const st=await api.firmware_upgrade_status();fill.style.width=(st.percent||0)+'%';err.textContent=(st.text||'正在升级…')+(st.state==='running'?' · '+(st.percent||0)+'%（别拔线）':'');
     if(st.state==='done'){err.textContent='✓ 更新好了，正在重新连接手套…';setTimeout(()=>box.remove(),3500);break;}
     if(st.state==='error'){go.disabled=later.disabled=false;go.textContent='再试一次';break;}}
   }catch(e){err.textContent=e.message||String(e);go.disabled=later.disabled=false;}};
  box.querySelector('.fwu-go').focus();
 }
 window.__fwShow=async(mode,ver)=>{if(!info){try{const api=await NativeApp.ready;info=await api.firmware_upgrade_info();}catch{info={available:false};}}show(mode,ver);};
 const css=document.createElement('style');css.textContent='#fw-upgrade{position:fixed;inset:0;z-index:260;display:grid;place-items:center;background:#1d273399}#fw-upgrade .fwu-bar{height:12px;border:2px solid #1d2733;border-radius:999px;overflow:hidden;background:#fff;margin:10px 0}#fw-upgrade .fwu-bar i{display:block;height:100%;width:0;background:#2e9e62;transition:width .3s}#fw-upgrade .fwu-card{width:min(520px,calc(100vw - 32px));background:#FFFBF2;border:3px solid #1d2733;border-radius:18px;box-shadow:0 10px 0 #1d273333,0 18px 40px #0004;padding:22px 26px;color:#1d2733}#fw-upgrade h2{margin:0 0 8px;font-size:22px}#fw-upgrade p{margin:6px 0;font-size:16px;line-height:1.6}#fw-upgrade .fwu-small{font-size:14px;color:#4c5d6e}#fw-upgrade .fwu-actions{display:flex;gap:12px;margin-top:14px}#fw-upgrade button{border:2.5px solid #1d2733;border-radius:12px;padding:9px 20px;font-size:16px;font-weight:900;cursor:pointer;background:#fff}#fw-upgrade .fwu-go{background:#2f9e5b;color:#fff}#fw-upgrade .fwu-err{color:#b23a1d;font-weight:700;min-height:1.4em}#fw-upgrade ul{margin:2px 0 8px;padding-left:22px;font-size:15px;line-height:1.6}#fw-upgrade .fwu-ver{margin:10px 0 0}#fw-upgrade .fwu-ok{color:#2f7a4a;font-weight:900}#fw-upgrade button:disabled{opacity:.5;cursor:default}#fw-ver{cursor:pointer;font-family:inherit;align-self:center;padding:5px 10px;border:2px solid #fff;border-radius:999px;background:#ffffff1a;color:#fff;font-size:12px;font-weight:800;white-space:nowrap}#fw-ver[hidden]{display:none}';
 document.head.append(css);
 setInterval(()=>check().catch(()=>{}),3000);
 // 11-05 用户：固件版本号显示在右上角
 // 11-05：版本号原来只在传曲子后才读到，平时不显示 → 每 10 秒自己读一次连接状态（只读电脑这边的记录，不打扰手套）
 let fwPolling=false,fwConnectedAt=null;setInterval(()=>{if(fwPolling)return;fwPolling=true;fetch('/api/status').then(r=>r.json()).then(async st=>{if(!st.connected){fwConnectedAt=null;window.__gloveLink={connected:false,info:'',at:Date.now()};return;}if(st.connectedAt===fwConnectedAt&&/ver=/.test(window.__gloveLink?.info||''))return;const info=await fetch('/api/software/status').then(r=>r.json());if(/ver=/.test(String(info.device_info||''))){fwConnectedAt=st.connectedAt;window.__gloveLink={connected:!!info.connected,info:String(info.device_info||''),at:Date.now()};}}).catch(()=>{}).finally(()=>{fwPolling=false;});},5000); /* 每次连上只向手套查一次版本 */
 setInterval(()=>{const link=window.__gloveLink,ver=link&&link.connected?(/(?:^|\s)ver=(\S+)/.exec(link.info)?.[1]||''):'';let tag=document.getElementById('fw-ver');const bar=document.querySelector('.desktop-header-actions');if(!bar)return;if(!tag){tag=document.createElement('button');tag.type='button';tag.id='fw-ver';tag.title='点开看固件版本、更新内容，可以更新固件';tag.onclick=async()=>{const v=(/(?:^|\s)ver=(\S+)/.exec(window.__gloveLink?.info||'')?.[1])||'';window.__fwShow?.('info',v);};bar.insertBefore(tag,document.getElementById('desktop-settings-open'));}tag.hidden=!ver;tag.textContent=ver?'固件 '+(window.__fwName?.(ver)||ver):'';},1500);
})();

// 11-05 用户：「更多工具」小菜单——点外面或按 Esc 收起
document.addEventListener('pointerdown',e=>{const t=document.getElementById('review-tools');if(t?.open&&!t.contains(e.target))t.open=false;},true);
document.addEventListener('keydown',e=>{const t=document.getElementById('review-tools');if(e.key==='Escape'&&t?.open){t.open=false;e.stopPropagation();}},true);
