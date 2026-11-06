/* 曲谱列表（11-04 用户：拖进几十首要一个个显示、像网盘传输列表一样有进度；拖过的都留着；
   每首有关键数据；能多选、一键送到手套）。只在桌面版里用。转换走原来的 catalog_prepare，
   打开走原来的 GloveCatalog.open，送到手套走原来的 playBuiltin（只存不播）。 */
(()=>{
'use strict';
if(!window.NativeApp)return;
const $=id=>document.getElementById(id);
const CATS=['考级曲','练习曲','古典名曲','流行影视'];
let api=null,rows=[],byId=new Map(),filter='all',query='',sort='default',loadRevision=0,appSession='';
const selected=new Set(),jobs=new Map(),queue=[];let running=false,sending=false;
let progressTasks=[],progressRunning=false;const progressCache=new Map();
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const trimTitle=t=>{t=String(t||'');for(const [l,r] of [['（','）'],['(',')'],['《','》'],['【','】']])if(t.split(l).length>t.split(r).length)t=t.slice(0,t.lastIndexOf(l)).replace(/[\s\-_，,]+$/,'');return t;}; // 文件名被截断留下的半个括号去掉
const titleOf=row=>trimTitle((window.GloveTitle?window.GloveTitle(row):row.title)||row.filename||row.id)||String(row.title||row.id);
const token=()=>'list-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
function toast(text,bad=false){window.ComicGuide?.toast?window.ComicGuide.toast(text):window.GloveWorkspace?.notice(text,bad);}
function markSourceProgressDirty(id,generation){
 const row=byId.get(id);if(!row)return;
 row.proof_generation=generation;row.proof_current=null;row.reviewProgress=null;row.progressPending=true;row.progressError='正在重新识别';for(const key of progressCache.keys())if(key.startsWith(id+'|'))progressCache.delete(key);updateRow(id);
}

// ---------- 数据 ----------
async function load(){
 const version=++loadRevision,c=await api.catalog_list();if(version!==loadRevision)return;
 rows=[...c.builtins.map(r=>({...r,source:'builtin'})),...c.imports.map(r=>({...r,source:'import',category:'我导入的'}))];
 // 11-05 用户：“没有人工核对的，全部都是无核对的”——一律按软件检查结果算，不再有“人工核对过”
 for(const r of rows)r.playable=false;
 byId=new Map(rows.map(r=>[String(r.id),r]));
 prepareProgress();render();refreshProgress();
}
function numbers(row){
 const s=row.stats||{},converting=['waiting','converting'].includes(jobs.get(String(row.id))?.state),progress=row.progressPending||converting?null:(row.reviewProgress||row.proof_current||null);
 const notes=progress?progress.total:null;
 const checked=progress&&Number.isInteger(progress.checked)?Math.max(0,Math.min(notes,progress.checked)):null;
 const unmatched=progress?.unmatched||0;
 return {pages:s.pages||row.pages||null,notes,checked,remaining:checked==null||unmatched?null:notes-checked,rate:notes&&checked!=null&&!unmatched?checked/notes*100:null,unmatched,checking:!!progress?.checking};
}

function progressViewActive(){return (!$('convert')?.hidden&&document.body.classList.contains('score-list-on'))||(!$('library')?.hidden&&$('library')?.classList.contains('lib-show-builtin'));}
function prepareProgress(){
 progressTasks=[];
 for(const row of rows){
  const key=String(row.id)+'|'+String(row.proof_revision??'none')+'|'+String(row.proof_generation??0)+'|'+String(row.proof_cache_token??'none');
  if(key&&progressCache.has(key))row.reviewProgress=progressCache.get(key);
  else if(!row.proof_current)progressTasks.push(row);
 }
 progressTasks.sort((a,b)=>Number(b.source==='import')-Number(a.source==='import'));
}
async function refreshProgress(){
 if(progressRunning||!progressViewActive()||!progressTasks.length||!api?.catalog_progress_project)return;
 progressRunning=true;
 try{
  while(progressTasks.length&&progressViewActive()){
   const wrap=document.querySelector('#library:not([hidden]) .sl-table-wrap,#convert:not([hidden]) #score-list-view .sl-table-wrap'),bounds=wrap?.getBoundingClientRect();
   const visibleIds=new Set(bounds?[...wrap.querySelectorAll('tr[data-id]')].filter(tr=>{const r=tr.getBoundingClientRect();return r.bottom>bounds.top&&r.top<bounds.bottom;}).map(tr=>String(tr.dataset.id)):[]);
   const available=r=>!['waiting','converting'].includes(jobs.get(String(r.id))?.state);
   let index=progressTasks.findIndex(r=>visibleIds.has(String(r.id))&&available(r));if(index<0)index=progressTasks.findIndex(available);if(index<0)break;
   const row=progressTasks.splice(index,1)[0],id=String(row.id);if(byId.get(id)!==row)continue;
   try{
    const data=await api.catalog_progress_project(id,120);if(byId.get(id)!==row)continue;
    if(data?.available===false&&data.reason==='not_cached'){row.progressError=row.proof_revision?'打开后更新进度':'待识别';updateRow(id);continue;}
    const measured=await window.GloveWorkspace.calculateCatalogProgress(data);if(byId.get(id)!==row)continue;
    const result=await api.record_catalog_progress(id,data.review_revision??null,data.progress_generation,data.progress_cache_token,measured);if(byId.get(id)!==row)continue;
    if(result?.stored){row.proof_revision=data.review_revision??null;row.proof_generation=data.progress_generation;row.proof_cache_token=data.progress_cache_token;row.reviewProgress=measured;row.progressPending=false;row.progressError='';progressCache.set(id+'|'+String(row.proof_revision??'none')+'|'+String(row.proof_generation??0)+'|'+String(row.proof_cache_token??'none'),measured);}
    else{row.progressError='进度已变化，重新统计';progressTasks.push(row);}
   }catch(error){if(byId.get(id)===row)row.progressError='统计失败，点校对重试';}
   if(byId.get(id)===row)updateRow(id);
   await new Promise(resolve=>setTimeout(resolve,0));
  }
 }finally{progressRunning=false;}
}
function stateOf(row){
 const job=jobs.get(String(row.id));if(job)return job;
 const n=numbers(row);
 return Number.isInteger(row.stats?.notes)||n.notes!=null?{state:'done'}:row.proof_revision?{state:'saved'}:row.legacy_shared_review?{state:'legacy'}:{state:row.source==='import'?'idle':'builtin'};
}

// ---------- 画列表 ----------
function visible(){
 const q=query.trim().toLowerCase();
 let list=rows.filter(row=>{
  if(row.source!=='import')return false; // PDF 识谱只管转换：只列自己拖进来的
  const converting=['waiting','converting'].includes(jobs.get(String(row.id))?.state);
  if(filter==='todo'){const n=numbers(row);if(n.remaining===0)return false;}
  if(filter==='busy'&&!converting)return false;
  return !q||titleOf(row).toLowerCase().includes(q);
 });
 const rank=row=>{const j=jobs.get(String(row.id));return j?({converting:0,waiting:1,error:2,done:3}[j.state]??4):row.source==='import'?5:6;};
 if(sort==='default')list.sort((a,b)=>rank(a)-rank(b));
 else if(sort==='name')list.sort((a,b)=>titleOf(a).localeCompare(titleOf(b),'zh'));
 else if(sort==='left')list.sort((a,b)=>(numbers(b).remaining??-1)-(numbers(a).remaining??-1)||titleOf(a).localeCompare(titleOf(b),'zh'));
 return list;
}
function statusCell(row){
 const j=stateOf(row);
 if(j.state==='converting'){const pct=j.total?Math.round(j.done/j.total*100):null;return `<div class="sl-progress"><i style="width:${pct??35}%"${pct==null?' class="sl-indeterminate"':''}></i></div><small>${esc(j.label||'转换中')}${pct!=null?' · '+pct+'%':''}</small>`;}
 if(j.state==='waiting')return '<span class="sl-tag sl-wait">排队中</span>';
 if(j.state==='error')return `<span class="sl-tag sl-bad" title="${esc(j.error)}">转换失败</span>`;
 if(j.state==='sending')return `<span class="sl-tag sl-busy">${esc(j.label||'正在送到手套')}</span>`;
 if(j.state==='sent')return '<span class="sl-tag sl-good">✓ 已在手套里</span>';
 if(j.state==='done')return numbers(row).notes===0?'<span class="sl-tag sl-wait">未识别到音符</span>':'<span class="sl-tag sl-good">已转换</span>';
 if(j.state==='saved')return '<span class="sl-tag">已有校对记录</span>';
 if(j.state==='legacy')return '<span class="sl-tag" title="旧版记录保留在软件自带曲谱中；导入曲谱独立识别">旧记录在自带曲库</span>';
 if(j.state==='builtin')return '<span class="sl-tag">内置</span>';
 return '<span class="sl-tag">未转换</span>';
}
function leftCell(row){
 const n=numbers(row);
 if(n.notes===0)return row.stats?.notes>0?'<span class="sl-muted">当前没有需校对的右手音</span>':'<span class="sl-todo" title="这份 PDF 里没认出右手音符，可能不是钢琴谱">没认出音符</span>';
 if(n.notes==null)return `<span class="sl-muted" title="${esc(row.progressError||'正在按当前曲谱重新统计')}">${esc(row.stats?.human_progress_unavailable?'进度待核实':row.progressError||'正在统计校对进度')}</span>`;
 if(n.unmatched)return '<span class="sl-todo" title="原有修改未能全部对应，请进入校对页检查">需核对旧修改</span>';
 if(n.checked==null)return `<span class="sl-muted" title="${esc(row.progressError||'正在读取已保存的结果')}">${esc(row.progressError||'正在统计校对进度')}</span>`;
 const label=n.checking?`正在检查 ${n.checked} / ${n.notes} 音`:`${n.rate.toFixed(1)}%（${n.checked} / ${n.notes} 音）`;
 return `<span class="${n.remaining===0?'sl-ok':'sl-todo'}" title="自动检查和人工确认合并，同一音只算一次。软件可能漏错。">${label}</span>`;
}
function rowHtml(row){
 const n=numbers(row),id=esc(row.id),state=stateOf(row).state,converting=['converting','waiting'].includes(state),busy=converting||state==='sending';
 return `<tr data-id="${id}" class="${selected.has(String(row.id))?'sl-selected':''}">
  <td class="sl-check"><input type="checkbox" aria-label="选择" ${selected.has(String(row.id))?'checked':''}></td>
  <td class="sl-name"><strong title="${esc(titleOf(row))}">${esc(titleOf(row))}</strong>${row.filename&&row.filename!==titleOf(row)+'.pdf'?`<small>${esc(row.filename)}</small>`:''}</td>
  <td class="sl-num">${converting?'—':n.pages??'—'}</td>
  <td class="sl-num">${converting?'—':n.notes??'—'}</td>
  <td class="sl-num">${converting||n.rate==null?'—':n.rate.toFixed(1)+'%'}</td>
  <td class="sl-left">${converting?'—':leftCell(row)}</td>
  <td class="sl-state">${statusCell(row)}</td>
  <td class="sl-actions"><button type="button" data-act="open" ${busy?'disabled':''}>校对</button><button type="button" data-act="send" class="sl-send" ${busy||n.notes===0?'disabled':''}>送到手套</button></td>
 </tr>`;
}
function summary(){
 const mine=rows.filter(r=>r.source==='import'),total=mine.length,ready=mine.filter(r=>numbers(r).notes>0&&numbers(r).remaining===0).length,todo=mine.filter(r=>numbers(r).remaining>0).length,unknown=mine.filter(r=>numbers(r).remaining==null).length,empty=mine.filter(r=>numbers(r).notes===0).length;
 const busy=[...jobs.values()].filter(j=>j.state==='converting'||j.state==='waiting').length;
 $('sl-summary').innerHTML=`导入了 <b>${total}</b> 份 · 已校对完 <b>${ready}</b> · 待校对 <b>${todo}</b>`+(unknown?` · 进度待统计 <b>${unknown}</b>`:'')+(empty?` · 未识别到音符 <b>${empty}</b>`:'')+(busy?` · <span class="sl-busy-text">正在转换 ${busy} 首</span>`:'');
}
function render(){
 if(!$('score-list-view'))return;
 const list=visible();
 $('sl-body').innerHTML=list.map(rowHtml).join('')||'<tr><td colspan="8" class="sl-empty">'+(filter==='busy'?'当前没有正在转换的曲谱':rows.some(r=>r.source==='import')?'没有符合的曲谱':'还没有导入 PDF。把 PDF 拖进来，或点右上角「＋ 添加 PDF」。软件自带的曲子在「曲库」里。')+'</td></tr>';
 renderBuiltins();
 for(const button of document.querySelectorAll('#sl-filters button'))button.classList.toggle('on',button.dataset.filter===filter);
 updateBulk();summary();
}
function updateRow(id){
 const row=byId.get(String(id));if(!row)return;
 for(const [body,html] of [['#sl-body',rowHtml],['#bl-body',builtinHtml]]){
  const tr=document.querySelector(body+' tr[data-id="'+CSS.escape(String(id))+'"]');
  if(tr){const t=document.createElement('tbody');t.innerHTML=html(row);tr.replaceWith(t.firstElementChild);}
 }
 summary();
}
function updateBulk(){
 const count=selected.size,bar=$('sl-bulk');bar.hidden=!count;
 $('sl-bulk-count').textContent='已选 '+count+' 首';
 $('sl-bulk-remove').hidden=![...selected].some(id=>byId.get(id)?.source==='import');
 const shown=visible();$('sl-all').checked=shown.length>0&&shown.every(r=>selected.has(String(r.id)));
}

// ---------- 转换队列 ----------
// 切换软件页面可续跑；关闭程序后不把旧会话排队任务自动重新启动。
function saveQueue(){try{if(!appSession)return;const left=[...jobs.entries()].filter(([,j])=>j.state==='waiting'||j.state==='converting').map(([id,j])=>({id,name:j.name||'',force:!!j.force,quiet:!!j.quiet}));if(left.length)sessionStorage.setItem('sl-queue',JSON.stringify({session:appSession,items:left}));else sessionStorage.removeItem('sl-queue');}catch{}}
function resumeQueue(){try{const saved=JSON.parse(sessionStorage.getItem('sl-queue')||'null');if(!saved||Array.isArray(saved)||saved.session!==appSession){sessionStorage.removeItem('sl-queue');return;}if(Array.isArray(saved.items)&&saved.items.length)enqueue(saved.items);}catch{}}
function enqueue(items){
 for(const item of items){
  if(!item.id){toast((item.name||'文件')+'：'+(item.error||'没法读取'),true);continue;}
  const id=String(item.id),existing=jobs.get(id),force=item.force!==false;
  if(existing?.state==='converting'){if(force){existing.repeatRequested=true;existing.repeatName=item.name;}continue;}
  if(existing?.state==='waiting'){if(force)existing.force=true;continue;}
  for(const key of progressCache.keys())if(key.startsWith(id+'|'))progressCache.delete(key);
  jobs.set(id,{state:'waiting',name:item.name,force,quiet:!!item.quiet});queue.push(id);updateRow(id);
 }
 if(filter==='todo')filter='all';
 saveQueue();
 load().then(()=>run());
}
// 11-05：和校对页同一套规则数“还差几处”（同类合并后），列表和校对页不再对不上
function questionsFor(notes){
 const R=window.GloveReview;if(!Array.isArray(notes)||!R?.noteConcern)return null;
 const fin=v=>typeof v==='number'&&Number.isFinite(v),all=notes.filter(n=>!n.excluded&&n.hand!=='left'&&n.in_export_scope!==false);
 const ask=n=>R.noteConcern(n,true)||R.timingNeedsAction(n)||(R.askPerformance?R.askPerformance(n):R.hasPerformanceWarning(n));
 const key=n=>{const miss=R.reviewMissingFields(n,true);if(miss.includes('时长')||(n.automatic_reasons||[]).some(r=>/音值|音长|时值|时长/.test(r))){const r=n.rhythm_evidence||{};return 'd|'+(n.grace_kind||'')+'|'+(r.head||'')+'|'+(r.beams||0)+'|'+(r.dots||0)+'|'+(r.flag_bboxes?.length||0)+'|'+(Array.isArray(r.stem)?'stem':'nostem');}
  if(miss.includes('指法')){const chord=all.filter(x=>x.page===n.page&&fin(x.beat)&&fin(n.beat)&&Math.abs(x.beat-n.beat)<1e-6).map(x=>x.pitch).sort().join(',');return 'f|'+n.pitch+'|'+chord;}return 'one|'+n.id;};
 return new Set(all.filter(ask).map(key)).size;
}
async function run(){
 if(running)return;running=true;
 try{
  while(queue.length){
   const id=queue.shift(),job=jobs.get(id);if(!job||job.state!=='waiting')continue;
   const t=token();Object.assign(job,{state:'converting',label:'准备',done:0,total:0});updateRow(id);
   let ended=false;const poll=async()=>{while(!ended){try{const p=await api.get_conversion_progress(t);if(p&&p.state!=='unknown'){job.label=p.label||job.label;if(Number.isInteger(p.page_total)&&p.page_total>0){job.total=p.page_total;job.done=p.page_done||0;}updateRow(id);}}catch{}await new Promise(r=>setTimeout(r,250));}};
   poll();
   try{
    if(job.force)markSourceProgressDirty(id,await api.invalidate_catalog_progress(id));
    await api.catalog_prepare(id,120,!!job.force,t);
    if(job.force)markSourceProgressDirty(id,await api.invalidate_catalog_progress(id));
    if(job.repeatRequested){job.state='waiting';job.force=true;job.name=job.repeatName||job.name;job.repeatRequested=false;queue.push(id);}else job.state='done';
   }
   catch(error){job.state='error';job.error=error.message||String(error);toast('转换失败：'+(byId.get(id)?titleOf(byId.get(id)):id),true);}
   finally{ended=true;saveQueue();if(filter==='busy'&&!['waiting','converting'].includes(job.state))render();}
   await load();
  }
 }finally{running=false;}
 const loud=[...jobs.values()].filter(j=>j.state==='done'&&!j.quiet).length;
 if(loud)toast('转换完成：'+loud+' 首可以校对或送到手套');
}

// ---------- 打开、送到手套、移除 ----------
async function openScore(id){
 hide();window.GloveWorkspace?.show('convert');
 await window.GloveCatalog?.open(id);
 const row=byId.get(String(id)),label=$('review-current-file');if(row&&label)label.textContent=titleOf(row);
}
async function send(ids){
 if(sending)return;
 if(!window.GloveWorkspace?.gloveReady?.()){toast('先连上手套（顶栏圆点变绿）再送',true);return;}
 sending=true;let ok=0,skipped=0;
 try{
  for(const id of ids){
   const row=byId.get(id);if(!row)continue;const job={state:'sending',label:'正在打包…'};jobs.set(id,job);updateRow(id);
   try{
    const bundle=row.playable?await api.catalog_package(id):await window.GloveWorkspace.packageCatalogScore(id,titleOf(row));skipped+=bundle.skipped||0;
    job.label='正在存进手套…';updateRow(id);
    const status={style:{},classList:{add(){},remove(){},toggle(){}},set textContent(v){job.label=v;updateRow(id);},get textContent(){return job.label;}}; /* 播放报 setting 'color'：状态框要有 style */
    const slot=await window.GloveWorkspace.playBuiltin(bundle,null,status,{storeOnly:true});
    job.state='sent';job.label='';ok++;if(slot?.slot)job.slot=slot.slot;
   }catch(error){job.state='error';job.error=error.message||String(error);toast(titleOf(row)+'：'+job.error,true);}
   updateRow(id);
  }
 }finally{sending=false;}
 window.GloveWorkspace?.refreshLibrary?.().catch(()=>{});
 toast('已送到手套 '+ok+' 首'+(skipped?'（有 '+skipped+' 个没认准的音先跳过了）':'')+'，在「曲库」里点「开始训练」就能弹');
}
async function removeImports(ids){
 const list=ids.filter(id=>byId.get(id)?.source==='import');if(!list.length)return;
 if(!(await window.AppConfirm('从列表里移除 '+list.length+' 首？原 PDF 不受影响。',{ok:'移除'})))return;
 for(const id of list){try{await api.forget_import(id);selected.delete(id);jobs.delete(id);}catch(error){toast(error.message||String(error),true);}}
 await load();await window.GloveCatalog?.refresh?.();toast('已移除 '+list.length+' 首');
}
async function pick(){
 const picked=await api.pick_pdfs();if(!picked?.length)return;
 await window.GloveCatalog?.refresh?.();enqueue(picked);
}

// ---------- 页面 ----------
function show(){document.body.classList.add('score-list-on');if($('sl-sort'))$('sl-sort').value=sort;Promise.resolve(window.GloveWorkspace?.flush?.()).then(()=>load()).catch(()=>{});}
function hide(){document.body.classList.remove('score-list-on');}
function build(){
 const view=document.createElement('section');view.id='score-list-view';view.setAttribute('aria-label','曲谱列表');
 view.innerHTML=`<header class="sl-head"><div><h2>PDF 转换</h2><p id="sl-summary"></p><p class="sl-rate-help">自动检查无提示和人工确认的音合并计算；软件可能漏错，漏识的音需要补录。</p></div>
  <div class="sl-head-actions"><input id="sl-search" type="search" placeholder="搜曲名" aria-label="搜曲名"><button id="sl-add" type="button" class="sl-primary">＋ 添加 PDF</button></div></header>
  <div class="sl-drop">把 PDF 拖到这里，一次几十份也行，会一份一份转换</div>
  <nav id="sl-filters"><button data-filter="all">全部</button><button data-filter="todo">待校对</button><button data-filter="busy">转换中</button>
   <select id="sl-sort" aria-label="排序"><option value="default">默认顺序</option><option value="name">按曲名</option><option value="left">待校对多的在前</option></select></nav>
  <div id="sl-bulk" hidden><span id="sl-bulk-count"></span><button id="sl-bulk-send" type="button" class="sl-primary">送到手套</button><button id="sl-bulk-remove" type="button">从列表移除</button><button id="sl-bulk-clear" type="button">取消选择</button></div>
  <div class="sl-table-wrap"><table class="sl-table"><thead><tr><th class="sl-check"><input id="sl-all" type="checkbox" aria-label="全选"></th><th>曲名</th><th class="sl-num">页</th><th class="sl-num">右手音</th><th class="sl-num" title="自动检查与人工确认合并的音符占比">校对比例</th><th>校对进度</th><th>状态</th><th></th></tr></thead><tbody id="sl-body"></tbody></table></div>`;
 const convert=$('convert');convert.prepend(view);
 $('sl-add').onclick=()=>pick().catch(error=>toast(error.message||String(error),true));
 $('sl-search').oninput=event=>{query=event.target.value;render();};
 $('sl-sort').onchange=event=>{if(!event.isTrusted){event.target.value=sort;return;}sort=event.target.value;render();};
 $('sl-filters').onclick=event=>{const b=event.target.closest('button');if(!b)return;filter=b.dataset.filter;render();};
 $('sl-all').onchange=event=>{for(const row of visible()){if(event.target.checked)selected.add(String(row.id));else selected.delete(String(row.id));}render();};
 $('sl-bulk-clear').onclick=()=>{selected.clear();render();};
 $('sl-bulk-send').onclick=()=>send([...selected]);
 $('sl-bulk-remove').onclick=()=>removeImports([...selected]);
 $('sl-body').onclick=event=>{
  const tr=event.target.closest('tr[data-id]');if(!tr)return;const id=tr.dataset.id;
  const act=event.target.closest('button')?.dataset.act;
  if(act==='open'){openScore(id).catch(error=>toast(error.message||String(error),true));return;}
  if(act==='send'){send([id]);return;}
  if(event.target.matches('input[type=checkbox]')){if(event.target.checked)selected.add(id);else selected.delete(id);tr.classList.toggle('sl-selected',event.target.checked);updateBulk();return;}
 };
 $('sl-body').ondblclick=event=>{const tr=event.target.closest('tr[data-id]');if(tr&&!event.target.closest('button,input'))openScore(tr.dataset.id);};
 // 校对页回列表
 const back=document.createElement('button');back.type='button';back.id='sl-back';back.textContent='← PDF 转换';back.onclick=show;
 document.querySelector('.review-toolbar')?.prepend(back);
 // 「选择 PDF」改成系统选文件窗口（多选、记住上次的文件夹）
 const choose=document.querySelector('.review-choose');
 if(choose)choose.addEventListener('click',event=>{event.preventDefault();show();pick().catch(error=>toast(error.message||String(error),true));},true);
 // 点顶栏「PDF 识谱」先到列表；首页「回到校对」直接进校对
 $('convert-tab')?.addEventListener('click',()=>show());
 document.addEventListener('click',event=>{if(event.target.closest('#comic-continue-open'))hide();},true);
 // 校对页里的“还剩 N 处”同步到列表
 // 11-05 用户：校对完列表要马上更新——同步后立刻刷新这一行；离开校对页时也先同步一次
 const syncProgress=()=>{
  syncProgress.force=false;
  const id=window.GloveCatalog?.current?.(),project=window.GloveReviewActive?.project?.();const text=$('proof-bar')?.innerText||'';if(!id||!project)return;
  const m=text.match(/软件提示\s*(\d+)\s*处/),left=m?Number(m[1]):null,progress=window.GloveReview?.combinedProgress?.(project),row=byId.get(String(id));if(!row||!progress)return;
  const identity=window.GloveWorkspace?.progressIdentity?.();if(identity&&(identity.generation!==row.proof_generation||identity.cacheToken!==row.proof_cache_token||identity.scope!==row.proof_scope))return;
  const pending=!!project.validation_pending||!!project.validation_error||progress.checking,unmatched=(project.unmatched_review_notes||[]).length;
  if(row.stats?.questions===left&&row.reviewProgress?.checked===progress.checked&&row.reviewProgress?.total===progress.total&&row.reviewProgress?.unmatched===unmatched&&!!row.progressPending===pending)return;
  const oldLeft=row.stats?.questions;row.stats={...(row.stats||{}),human_reviewed_notes_v1:progress.human,human_review_total_v1:progress.total,...(left==null?{}:{questions:left})};row.progressPending=pending;row.progressError=project.validation_error?'检查未完成，点校对重试':pending?'正在检查':'';row.reviewProgress={...progress,unmatched};updateRow(String(id));renderBuiltins();
  if(left!=null&&oldLeft!==left)api.record_score_stats(String(id),{questions:left}).catch(()=>{});
 };
 setInterval(()=>{if(!document.body.classList.contains('score-list-on'))syncProgress();},1500);
 window.addEventListener('glove-review-progress',syncProgress);
 document.addEventListener('click',event=>{if(event.target.closest('.desktop-navigation button,#sl-back,#lib-tab-builtin')){syncProgress.force=true;syncProgress();}},true);
 document.addEventListener('click',event=>{if(event.target.closest('[data-tab="library"],#lib-tab-builtin,#lib-tab-import'))Promise.resolve(window.GloveWorkspace?.flush?.()).then(ok=>{if(ok!==false)return load();}).catch(()=>{});},true);
}
// ---------- 曲库「软件自带」：100 首分四类，播放 / 送到手套 / 校对 / 多选 ----------
let bFilter='全部',bQuery='',bSource='builtin'; /* 11-05 用户：PDF 转换出来的也要在曲库里有一栏 */const bSelected=new Set();
function builtinRows(){return rows.filter(r=>r.source===bSource&&(r.source_kind==='manual'||r.stats?.notes!==0)&&!(bSource==='import'&&jobs.get(String(r.id))&&['waiting','converting'].includes(jobs.get(String(r.id)).state)));} /* 扫描版有人工编配的也保留 */
function builtinVisible(){
 const q=bQuery.trim().toLowerCase();
 return builtinRows().filter(r=>(bFilter==='全部'||r.category===bFilter)&&(!q||titleOf(r).toLowerCase().includes(q)))
  .sort((a,b)=>CATS.indexOf(a.category)-CATS.indexOf(b.category)||Number(!!b.playable)-Number(!!a.playable)||(numbers(a).pages||0)-(numbers(b).pages||0));
}
function builtinHtml(row){
 const n=numbers(row),id=esc(row.id),j=jobs.get(String(row.id)),busy=j&&['sending','playing'].includes(j.state);
 const state=j?.state==='sending'||j?.state==='playing'?`<span class="sl-tag sl-busy">${esc(j.label||'')}</span>`:j?.state==='sent'?(j.played?'<span class="sl-tag sl-good">▶ 在弹（顶上「停止」可停）</span>':'<span class="sl-tag sl-good">✓ 已在手套里</span>'):j?.state==='error'?`<span class="sl-tag sl-bad" title="${esc(j.error)}">没成功</span>`:'';
 return `<tr data-id="${id}" class="${bSelected.has(String(row.id))?'sl-selected':''}">
  <td class="sl-check"><input type="checkbox" aria-label="选择" ${bSelected.has(String(row.id))?'checked':''}></td>
  <td class="sl-name"><strong title="${esc(titleOf(row))}">${esc(titleOf(row))}</strong><small>${esc(row.category||'')}${n.pages?' · '+n.pages+' 页':''}${n.notes?' · '+n.notes+' 个右手音':''}</small></td>
  <td class="sl-left">${leftCell(row)}${state?'<br>'+state:''}</td>
  <td class="sl-actions"><button type="button" data-act="play" class="bl-play" ${busy?'disabled':''}>▶ 播放</button><button type="button" data-act="send" class="sl-send" ${busy?'disabled':''}>送到手套</button><button type="button" data-act="open" ${busy?'disabled':''}>校对</button></td>
 </tr>`;
}
function renderBuiltins(){
 if(!$('bl-body'))return;
 const list=builtinVisible(),all=builtinRows();
 $('bl-body').innerHTML=list.map(builtinHtml).join('')||'<tr><td colspan="4" class="sl-empty">没找到，换个词试试</td></tr>';
 $('bl-filters').innerHTML=['全部',...CATS].map(c=>`<button data-filter="${c}" class="${c===bFilter?'on':''}">${c} <small>${c==='全部'?all.length:all.filter(r=>r.category===c).length}</small></button>`).join('');
 $('bl-bulk').hidden=!bSelected.size;$('bl-bulk-count').textContent='已选 '+bSelected.size+' 首';
 $('bl-all').checked=list.length>0&&list.every(r=>bSelected.has(String(r.id)));
 for(const [id,src] of [['lib-tab-builtin','builtin'],['lib-tab-import','import']]){const tab=$(id);if(tab)tab.querySelector('small').textContent=rows.filter(r=>r.source===src&&(r.playable||r.stats?.notes!==0)).length;}$('bl-filters').hidden=bSource==='import';if(!list.length&&bSource==='import')$('bl-body').innerHTML='<tr><td colspan="4" class="sl-empty">还没有转换好的曲谱。到「PDF 识谱」把 PDF 拖进去，转好就会出现在这里。</td></tr>';
}
async function playOne(id){
 const row=byId.get(id);if(!row)return;
 if(!window.GloveWorkspace?.gloveReady?.()){toast('先连上手套（顶栏圆点变绿）再播放',true);return;}
 const job={state:'playing',label:'正在准备…'};jobs.set(id,job);updateRow(id);
 const status={style:{},classList:{add(){},remove(){},toggle(){}},set textContent(v){job.label=v;updateRow(id);},get textContent(){return job.label;}}; /* 播放报 setting 'color'：状态框要有 style */
 try{await window.GloveWorkspace.playBuiltin(()=>row.playable?api.catalog_package(id):window.GloveWorkspace.packageCatalogScore(id,titleOf(row)),document.createElement('button'),status);job.state='sent';job.played=true;}
 catch(error){job.state='error';job.error=error.message||String(error);toast(titleOf(row)+'：'+job.error,true);}
 updateRow(id);
}
function buildBuiltins(){
 const library=$('library');if(!library||$('bl-panel'))return;
 // 两个标签：手套里的 / 软件自带
 const tabs=document.createElement('div');tabs.id='lib-tabs';
 tabs.innerHTML='<button id="lib-tab-glove" type="button" class="on">手套里的 <small id="lib-glove-count"></small></button><button id="lib-tab-builtin" type="button">软件自带 <small></small></button><button id="lib-tab-import" type="button">我转换的 <small></small></button>';
 library.querySelector('.heading').after(tabs);
 const panel=document.createElement('div');panel.id='bl-panel';
 panel.innerHTML=`<div class="bl-top"><nav id="bl-filters"></nav><input id="bl-search" type="search" placeholder="搜曲名" aria-label="搜软件自带的曲子"></div>
  <div id="bl-bulk" hidden><span id="bl-bulk-count"></span><button id="bl-bulk-send" type="button" class="sl-primary">送到手套</button><button id="bl-bulk-clear" type="button">取消选择</button></div>
  <div class="sl-table-wrap"><table class="sl-table bl-table"><thead><tr><th class="sl-check"><input id="bl-all" type="checkbox" aria-label="全选"></th><th>曲名</th><th>校对进度</th><th></th></tr></thead><tbody id="bl-body"></tbody></table></div>`;
 tabs.after(panel);
 const setTab=name=>{const list=name==='builtin'||name==='import';if(list){bSource=name;bFilter='全部';bSelected.clear();}library.classList.toggle('lib-show-builtin',list);library.classList.toggle('lib-show-import',name==='import');$('lib-tab-glove').classList.toggle('on',!list);$('lib-tab-builtin').classList.toggle('on',name==='builtin');$('lib-tab-import').classList.toggle('on',name==='import');if(list){renderBuiltins();refreshProgress();}};
 $('lib-tab-glove').onclick=()=>setTab('glove');$('lib-tab-builtin').onclick=()=>setTab('builtin');$('lib-tab-import').onclick=()=>setTab('import');
 window.ScoreList.libraryTab=setTab;
 $('bl-filters').onclick=event=>{const b=event.target.closest('button');if(!b)return;bFilter=b.dataset.filter;renderBuiltins();};
 $('bl-search').oninput=event=>{bQuery=event.target.value;renderBuiltins();};
 $('bl-all').onchange=event=>{for(const r of builtinVisible()){if(event.target.checked)bSelected.add(String(r.id));else bSelected.delete(String(r.id));}renderBuiltins();};
 $('bl-bulk-clear').onclick=()=>{bSelected.clear();renderBuiltins();};
 $('bl-bulk-send').onclick=()=>send([...bSelected]);
 $('bl-body').onclick=event=>{
  const tr=event.target.closest('tr[data-id]');if(!tr)return;const id=tr.dataset.id,act=event.target.closest('button')?.dataset.act;
  if(act==='play'){playOne(id);return;}
  if(act==='send'){send([id]);return;}
  if(act==='open'){window.GloveWorkspace?.show('convert');openScore(id).catch(error=>toast(error.message||String(error),true));return;}
  if(event.target.matches('input[type=checkbox]')){if(event.target.checked)bSelected.add(id);else bSelected.delete(id);tr.classList.toggle('sl-selected',event.target.checked);$('bl-bulk').hidden=!bSelected.size;$('bl-bulk-count').textContent='已选 '+bSelected.size+' 首';}
 };
 // 手套里没有曲子时，先看软件自带
 const songs=$('songs'),count=()=>{const n=songs?.querySelectorAll('.song').length||0;$('lib-glove-count').textContent=n;return n;};
 if(songs)new MutationObserver(count).observe(songs,{childList:true});
 setTimeout(()=>{if(!count())setTab('builtin');},1500);
}
// ---------- 曲库（手套里的曲子）多选：全选 / 下载 / 删除 ----------
function buildLibrary(){
 const songs=$('songs');if(!songs||$('lib-manage'))return;
 const bar=document.createElement('div');bar.id='lib-manage';
 bar.innerHTML='<label><input id="lib-all" type="checkbox"> 全选</label><span id="lib-count"></span><button id="lib-download" type="button">下载选中</button><button id="lib-delete" type="button" class="lib-danger">删除选中</button><button id="lib-to-list" type="button" class="sl-primary">＋ 从软件自带挑曲子送进来</button>';
 songs.before(bar);
 const picked=()=>[...songs.querySelectorAll('.song .lib-pick:checked')].map(box=>Number(box.closest('.song').dataset.slot));
 const sync=()=>{const n=picked().length,all=songs.querySelectorAll('.song .lib-pick');$('lib-count').textContent=n?'已选 '+n+' 首':'';$('lib-download').disabled=$('lib-delete').disabled=!n;$('lib-all').checked=all.length>0&&n===all.length;};
 const decorate=()=>{for(const row of songs.querySelectorAll('.song')){if(row.querySelector('.lib-pick'))continue;const box=document.createElement('input');box.type='checkbox';box.className='lib-pick';box.setAttribute('aria-label','选择这首');row.prepend(box);}sync();};
 new MutationObserver(decorate).observe(songs,{childList:true});decorate();
 songs.addEventListener('change',event=>{if(event.target.matches('.lib-pick'))sync();});
 $('lib-all').onchange=event=>{for(const box of songs.querySelectorAll('.song .lib-pick'))box.checked=event.target.checked;sync();};
 const runBulk=async(action)=>{const slots=picked();if(!slots.length)return;
  if(action==='delete'&&!(await window.AppConfirm('从手套里删除 '+slots.length+' 首？',{ok:'删除'})))return;
  try{await window.GloveWorkspace.libraryBulk(action,slots);}catch(error){toast(error.message||String(error),true);}sync();};
 $('lib-download').onclick=()=>runBulk('download');$('lib-delete').onclick=()=>runBulk('delete');
 $('lib-to-list').onclick=()=>window.ScoreList.libraryTab?.('builtin');
}
async function start(){
 api=await NativeApp.ready;
 try{appSession=String(await api.application_session_id());}catch{appSession='page-'+Date.now()+'-'+Math.random().toString(36).slice(2);}
 const wait=()=>new Promise(r=>{const check=()=>window.GloveCatalog&&$('convert')?r():setTimeout(check,200);check();});
 await wait();build();buildLibrary();buildBuiltins();await load();resumeQueue();setInterval(saveQueue,1000);setInterval(refreshProgress,750);addEventListener('pagehide',saveQueue);
 if(!$('convert').hidden)show(); /* 11-05 用户：进 PDF 识谱先看列表，不自动进校对页 */
}
window.ScoreList={show,hide,enqueue,reload:()=>load()};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>start().catch(console.error),{once:true});else start().catch(console.error);
})();
