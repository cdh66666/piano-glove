/* Native file intake and reviewed built-in scores. Playback needs a button click. */
(()=>{
'use strict';
if(!window.NativeApp)return;
const $=id=>document.getElementById(id);let busy=false,intake=Promise.resolve(),currentId='',intakeEpoch=0;
function enqueue(task){const next=intake.catch(()=>{}).then(task);intake=next;return next;}
async function mount(){
 if(!window.GloveWorkspace)return;
 const workspace=window.GloveWorkspace,api=await NativeApp.ready;
 const readyPanel=document.createElement('div');readyPanel.id='native-ready-library';readyPanel.innerHTML='<div><strong>软件自带的曲子</strong><span>建议对照原谱检查后练习</span></div><input id="native-ready-search" type="search" placeholder="搜曲名，如 车尔尼、哈农、圣诞" aria-label="搜索软件自带的曲子"><select id="native-ready-select" aria-label="选择内置曲谱"></select><button id="native-ready-play" type="button">播放</button><button id="native-ready-export" type="button">导出曲谱</button><small id="native-ready-status" role="status"></small>';$('library').querySelector('.heading').after(readyPanel);
 // 曲名给人看：去掉网站编号和“_五线谱_带指法”尾巴；只写“第N首”的车尔尼练习曲补上书名（PDF 里写着 艺术家：车尔尼）。
 const CZERNY_NUMBERED=new Set(['1002163','1002165','1002168','1002169','1002170']);
 const displayTitle=row=>{let t=String(row?.title||'').replace(/^\d{5,}_\d+_/,'').replace(/_(五线谱|带指法|黑键标注?|简谱)/g,'').replace(/\.pdf$/i,'').trim();if(CZERNY_NUMBERED.has(String(row?.id))&&/^第\d+首/.test(t))t='车尔尼练习曲 '+t;return t||String(row?.title||'');};
 window.GloveTitle=displayTitle;
 const readySelect=$('native-ready-select'),readyPlay=$('native-ready-play'),readyExport=$('native-ready-export'),readyStatus=$('native-ready-status');let preparing=false,exporting=false;
 let readyNoMatch=false; // 搜不到时别让下拉框停在旧结果上
 function filterReady(){const box=$('native-ready-search');const q=(box?.value||'').trim().toLowerCase();let first=null;for(const o of readySelect.options){const hit=!q||o.textContent.toLowerCase().includes(q);o.hidden=!hit;if(hit&&!first)first=o;}if(q&&first&&readySelect.selectedOptions[0]?.hidden)readySelect.value=first.value;if(box)box.title=q?([...readySelect.options].filter(o=>!o.hidden).length+' 首符合'):'';const status=readyStatus,miss=!!q&&!first;if(status&&(miss||readyNoMatch))status.textContent=miss?'没找到「'+box.value.trim()+'」，换个词试试；清空搜索框就能看到全部':'';readyNoMatch=miss;readyControls();}
 $('native-ready-search')?.addEventListener('input',filterReady);
 function readyControls(){readyPlay.disabled=readyExport.disabled=preparing||exporting||readyNoMatch||!readySelect.value;readySelect.disabled=preparing||exporting||readyNoMatch;}
 readyPlay.onclick=async()=>{if(preparing||exporting||!readySelect.value)return;preparing=true;readyControls();readyStatus.textContent='正在准备曲谱…';try{await workspace.playBuiltin(()=>api.catalog_package(readySelect.value),readyPlay,readyStatus);}catch(error){readyStatus.textContent=error.message||String(error);workspace.notice(readyStatus.textContent,true);}finally{preparing=false;readyControls();}};
 readyExport.onclick=async()=>{if(preparing||exporting||!readySelect.value)return;exporting=true;readyControls();readyStatus.textContent='正在准备曲谱…';try{const bundle=await api.catalog_package(readySelect.value),bytes=Uint8Array.from(atob(bundle.base64),c=>c.charCodeAt(0));const saved=await NativeApp.save(bytes,bundle.name);readyStatus.textContent=saved?'已导出带原谱曲谱，可传给手机使用':'已取消保存';}catch(error){readyStatus.textContent=error.message||String(error);workspace.notice(readyStatus.textContent,true);}finally{exporting=false;readyControls();}};
 const select=document.createElement('select');select.id='native-score-catalog';select.className='native-catalog-select';select.setAttribute('aria-label','内置与已导入原谱');
 const status=document.createElement('span');status.id='native-review-save';status.className='native-review-save';
 ($('review-tools-panel')||document.querySelector('.review-toolbar')).append(select);document.querySelector('.review-toolbar').append(status);
 const add=$('add-note');add.textContent='补录音符';($('review-tools-panel')||document.querySelector('.review-toolbar')).append(add);
 $('save-review').textContent='导出复核文件';
 const reviewLabel=$('review-file').closest('label');for(const node of reviewLabel.childNodes)if(node.nodeType===3)node.textContent='导入复核文件';
 const blank=document.createElement('div');blank.id='native-drop-blank';blank.innerHTML='<strong>拖入 PDF 开始转换</strong><p>也可以点下面的按钮选一份内置原谱</p>';$('convert').insertBefore(blank,$('review-workspace'));
 let activeBatch=null,catalogRows={builtins:[],imports:[]};
 const panel=document.createElement('section');panel.id='native-conversion-panel';panel.hidden=true;panel.setAttribute('aria-label','PDF 批量转换进度');panel.innerHTML='<header><strong id="native-conversion-title">正在转换曲谱</strong><button id="native-conversion-stop" type="button">完成当前后停止</button></header><div id="native-conversion-overall-label" role="status" aria-live="polite"></div><progress id="native-conversion-overall" aria-label="批量已处理份数" max="1" value="0"></progress><div class="native-conversion-current"><span id="native-conversion-position"></span><strong id="native-conversion-current"></strong></div><p id="native-conversion-stage" aria-live="polite"></p><progress id="native-conversion-current-progress" aria-label="当前曲谱处理进度"></progress><p id="native-conversion-pages"></p><div id="native-conversion-list" aria-label="逐份转换状态"></div>';$('convert').insertBefore(panel,blank);
 const history=document.createElement('details');history.id='native-conversion-history';history.hidden=true;const historyTitle=document.createElement('summary'),historyList=document.createElement('div');history.append(historyTitle,historyList);($('review-tools-panel')||document.querySelector('.review-toolbar')).append(history);
 const updateBlank=()=>blank.hidden=!!activeBatch||!$('review-workspace').hidden;
 new MutationObserver(updateBlank).observe($('review-workspace'),{attributes:true,attributeFilter:['hidden']});updateBlank();
 async function refresh(){const catalog=await api.catalog_list(),current=select.value,currentReady=readySelect.value;catalogRows=catalog;select.replaceChildren(new Option('选择内置原谱（'+catalog.builtins.length+'）',''));for(const [name,rows] of [['内置原谱',catalog.builtins],['已导入',catalog.imports]]){if(!rows.length)continue;const group=document.createElement('optgroup');group.label=name;for(const row of rows)group.append(new Option(displayTitle(row),row.id));select.append(group);}select.value=current;const ready=catalog.builtins.filter(row=>row.playable);readySelect.replaceChildren(...ready.map(row=>new Option(displayTitle(row),row.id)));filterReady();if(ready.some(row=>row.id===currentReady))readySelect.value=currentReady;readyPanel.hidden=!ready.length;readyControls();return catalog;}

 // 11-05 用户：点「校对」要等一两秒，先在屏幕中间给个进度条（和倒计时一样的样子），打开好就消失
 function name0(id){return [...select.options].find(option=>option.value===id)?.textContent||'';}
 function openingOverlay(name){
  let box=null,timer=setTimeout(()=>{box=document.createElement('div');box.className='app-opening';box.setAttribute('role','status');
   box.style.cssText='position:fixed;inset:0;z-index:2147482000;display:flex;align-items:center;justify-content:center;background:rgba(245,240,232,.72);font-family:"Microsoft YaHei UI",sans-serif';
   box.innerHTML='<div style="background:#fff;border:2px solid #23212b;border-radius:16px;box-shadow:5px 5px 0 #23212b;padding:24px 30px;min-width:min(380px,80vw);text-align:center;color:#23212b"><b style="font-size:20px;display:block;margin-bottom:6px">正在打开…</b><span style="font-size:14px;color:#5b6474;display:block;margin-bottom:14px"></span><div style="height:14px;border:2px solid #23212b;border-radius:8px;overflow:hidden;background:#fff"><i style="display:block;height:100%;width:0;background:#2f9e5b;transition:width .3s ease-out"></i></div></div>';
   box.querySelector('span').textContent=name;document.body.append(box);
   const bar=box.querySelector('i'),t0=performance.now();const step=()=>{if(!box)return;const s=(performance.now()-t0)/1000;bar.style.width=Math.min(92,100*(1-Math.exp(-s/1.2)))+'%';requestAnimationFrame(step);};requestAnimationFrame(step);},150);
  return {done(){clearTimeout(timer);if(box){const b=box;box=null;b.querySelector('i').style.width='100%';setTimeout(()=>b.remove(),180);}}};
 }
 async function open(id,force=false){if(!id||busy)return false;if(force){try{const name=[...select.options].find(option=>option.value===id)?.textContent||'当前曲谱';return await runPdfBatch([{name}],{existingId:id,force:true});}catch(error){workspace.notice(error.message||String(error),true);return false;}}busy=true;select.disabled=true;const previousId=currentId;workspace.notice('正在打开曲谱…');const loading=openingOverlay(name0(id));try{if(await workspace.flush()===false)throw Error('当前修改尚未保存，请先处理编辑框或保存错误');workspace.show('convert');const bpm=120,result=await api.catalog_open(id,bpm);workspace.openProject(result);currentId=id;select.value=id;workspace.notice(result.project?.source_kind==='manual'?(result.review?'已恢复人工编配曲谱的校对进度':'人工编配曲谱已就绪'):(result.review?'已恢复这份原谱的校对进度':'原谱已打开'));return true;}catch(error){select.value=previousId;workspace.notice(error.message||String(error),true);return false;}finally{loading.done();select.disabled=false;busy=false;}}
 select.onchange=()=>{const id=select.value;return enqueue(()=>open(id));};
 const originalRecognize=$('recognize').onclick;$('recognize').onclick=event=>{const id=select.value;return enqueue(()=>id?open(id,true):originalRecognize(event));};
 $('pdf').addEventListener('change',()=>{select.value='';});
 const catalogButton=document.createElement('button');catalogButton.type='button';catalogButton.textContent='内置原谱';catalogButton.id='native-builtin-entry';catalogButton.onclick=()=>{workspace.show('convert');if($('review-tools'))$('review-tools').open=true;select.focus();try{select.showPicker?.();}catch{}};$('library').querySelector('.heading').append(catalogButton);
 let explicitSlot=false;
 const usedSlots=()=>new Set([...document.querySelectorAll('#songs .song-title')].map(e=>Number(e.textContent.match(/^\d+/)?.[0])));
 function prepareSlot(){const used=usedSlots();if(!explicitSlot){let slot=1;while(used.has(slot)&&slot<=100)slot++;if(slot<=100)$('slot').value=slot;}const slot=Number($('slot').value);$('upload').textContent=used.has(slot)?'替换第 '+slot+' 首':'上传到第 '+slot+' 首';}
 $('slot').addEventListener('input',()=>{explicitSlot=true;prepareSlot();});$('pgl').addEventListener('change',prepareSlot);
 const stageNames={loading:'读取曲谱',cache:'读取已有识别结果',recognizing:'识别原谱',postprocess:'整理音符',arranging:'生成练习编排',preview:'准备原谱图片',saving:'保存识别结果',validating:'校验转换结果',done:'转换完成',error:'转换未完成'};
 const jobToken=()=>window.crypto?.randomUUID?.()||'conversion-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
 function updateBatch(batch){
  panel.dataset.total=String(batch.items.length);panel.dataset.completed=String(batch.completed);panel.dataset.currentIndex=String(batch.index+1);
  $('native-conversion-overall').max=batch.items.length;$('native-conversion-overall').value=batch.completed;
  $('native-conversion-overall-label').textContent='已处理 '+batch.completed+' / '+batch.items.length+' 份 · 已转换 '+batch.successes+' · 失败 '+batch.failures;
  $('native-conversion-position').textContent='第 '+(batch.index+1)+' / '+batch.items.length+' 份';$('native-conversion-current').textContent=batch.items[batch.index]?.name||'';$('native-conversion-current').title=$('native-conversion-current').textContent;
 }
 function currentStage(batch,value){
  if(activeBatch!==batch)return;const stage=value.stage||'loading',bar=$('native-conversion-current-progress');panel.dataset.stage=stage;
  $('native-conversion-stage').textContent=value.label||stageNames[stage]||'正在处理曲谱';
  if(stage==='recognizing'&&value.determinate===true&&Number.isInteger(value.page_done)&&Number.isInteger(value.page_total)&&value.page_total>0){bar.max=value.page_total;bar.value=Math.max(0,Math.min(value.page_done,value.page_total));$('native-conversion-pages').textContent='已识别 '+bar.value+' / '+value.page_total+' 页';}
  else{bar.removeAttribute('value');$('native-conversion-pages').textContent=value.error||'正在处理，请稍候。';}
 }
 function observeJob(batch,token){
  panel.dataset.token=token;batch.currentToken=token;let ended=false,timer=null,sequence=-1;
  const poll=async()=>{if(ended||activeBatch!==batch||batch.currentToken!==token)return;try{if(typeof api.get_conversion_progress==='function'){const state=await api.get_conversion_progress(token);if(!ended&&activeBatch===batch&&batch.currentToken===token&&state?.token===token&&Number(state.sequence??0)>=sequence){sequence=Number(state.sequence??0);if(state.state!=='unknown')currentStage(batch,state);}}}catch{}finally{if(!ended&&activeBatch===batch&&batch.currentToken===token)timer=setTimeout(poll,150);}};
  poll();return()=>{ended=true;clearTimeout(timer);if(batch.currentToken===token)batch.currentToken=null;};
 }
 function itemState(item,state,text){item.state=state;item.row.dataset.status=state;item.status.textContent=text;item.status.title=text;if(item.id)item.row.dataset.scoreId=item.id;}
 $('native-conversion-stop').onclick=()=>{if(!activeBatch)return;activeBatch.stopRequested=true;intakeEpoch++;$('native-conversion-stop').disabled=true;$('native-conversion-title').textContent='当前曲谱完成后停止';};
 async function runPdfBatch(pdfs,{existingId=null,force=false}={}){
  if(await workspace.flush()===false)throw Error('当前修改尚未保存，请先处理编辑框或保存错误');
  workspace.show('convert');workspace.notice('正在转换 '+pdfs.length+' 份曲谱…');const previousId=currentId,batch={items:[],index:0,completed:0,successes:0,failures:0,stopRequested:false,currentToken:null};
  const controls=[$('pdf'),$('recognize'),select,$('review-file'),$('add-note')].filter(Boolean).map(element=>({element,disabled:element.disabled}));
  activeBatch=batch;busy=true;panel.dataset.active='true';panel.hidden=false;document.body.classList.add('conversion-busy');blank.hidden=true;for(const row of controls)row.element.disabled=true;
  $('native-conversion-title').textContent=pdfs.length>1?'正在批量转换曲谱':'正在转换曲谱';$('native-conversion-stop').disabled=false;$('native-conversion-stop').hidden=pdfs.length<2;$('native-conversion-list').replaceChildren();
  for(const [index,file]of pdfs.entries()){const row=document.createElement('div'),name=document.createElement('span'),status=document.createElement('small');row.className='native-conversion-item';row.dataset.index=String(index);name.textContent=file.name;name.title=file.name;row.append(name,status);$('native-conversion-list').append(row);const item={name:file.name,row,status,id:null,state:'pending'};batch.items.push(item);itemState(item,'pending','等待处理');}
  updateBatch(batch);currentStage(batch,{stage:'loading',label:'准备读取文件'});let lastSuccess=null,lastResult=null,opened=false;
  try{
   await new Promise(resolve=>setTimeout(resolve,16));
   for(let index=0;index<pdfs.length;index++){
    if(batch.stopRequested)break;batch.index=index;const item=batch.items[index],token=jobToken();updateBatch(batch);currentStage(batch,{stage:'loading',label:'读取 '+item.name});itemState(item,'reading','读取文件');
    let stopObserving=()=>{};
    try{
     if(existingId)item.id=existingId;else{const file=pdfs[index];item.id=await api.register_pdf(file.name,await NativeApp.as64(await file.arrayBuffer()));}
     itemState(item,'processing','正在转换');currentStage(batch,{stage:'loading',label:'正在准备曲谱'});stopObserving=observeJob(batch,token);
     const forceFile=existingId?!!force:true;if(forceFile)await api.invalidate_catalog_progress(item.id);
     const full=index===pdfs.length-1||typeof api.catalog_prepare!=='function',result=full?await api.catalog_open(item.id,120,forceFile,token):await api.catalog_prepare(item.id,120,forceFile,token);
     if(forceFile){const generation=await api.invalidate_catalog_progress(item.id);if(full&&result)result.progress_generation=generation;}
     if(full&&!result?.project)throw Error('转换结果不完整，请重试');
     if(!full&&!result?.id)throw Error('转换结果不完整，请重试');itemState(item,'done','已转换');batch.successes++;lastSuccess=item;if(full)lastResult=result;
    }catch(error){batch.failures++;itemState(item,'error','失败：'+(error.message||String(error)));}
    finally{stopObserving();batch.completed++;updateBatch(batch);}
   }
   for(const item of batch.items)if(item.state==='pending')itemState(item,'cancelled','未开始（已停止）');
   if(lastSuccess){
    if(!lastResult){batch.index=batch.items.indexOf(lastSuccess);updateBatch(batch);currentStage(batch,{stage:'cache',label:'打开最后识别完成的曲谱'});const token=jobToken(),stopObserving=observeJob(batch,token);try{lastResult=await api.catalog_open(lastSuccess.id,120,false,token);}finally{stopObserving();}}
    if(!lastResult?.project)throw Error('曲谱已转换，但暂未能打开；可从已导入目录重试');
    workspace.openProject(lastResult);lastResult=null;currentId=lastSuccess.id;opened=true;
   }
   const catalog=await refresh();select.value=currentId;
   const failed=batch.items.filter(item=>item.state==='error').map(item=>item.name);workspace.notice('已转换 '+batch.successes+' / '+batch.items.length+' 份'+(batch.stopRequested?'；已停止后续队列':'')+(failed.length?'；失败 '+failed.length+' 份：'+failed.join('、')+'。更多工具中可查看转换记录。':''),failed.length>0);return opened;
  }catch(error){workspace.notice(error.message||String(error),true);select.value=previousId;return false;}
  finally{
   historyList.replaceChildren(...batch.items.map(item=>item.row));historyTitle.textContent='转换记录 · 已转换 '+batch.successes+' / '+batch.items.length+(batch.failures?' · 失败 '+batch.failures:'');history.hidden=false;
   for(const row of controls)row.element.disabled=row.disabled;
   lastResult=null;activeBatch=null;busy=false;panel.dataset.active='false';panel.hidden=true;document.body.classList.remove('conversion-busy');updateBlank();
  }
 }
 async function importFiles(files){
  const list=Array.from(files||[]);if(!list.length)return;
  const pdfs=list.filter(file=>/\.pdf$/i.test(file.name));
  if(pdfs.length&&window.ScoreList){ // 11-04：拖进来的 PDF 全部进「曲谱列表」排队转换，列表一直都在
   workspace.show('convert');window.ScoreList.show();const items=[];
   for(const file of pdfs){try{const registered=await api.register_pdf(file.name,await NativeApp.as64(await file.arrayBuffer()));items.push({id:registered,name:file.name,force:true});}catch(error){items.push({name:file.name,error:error.message||String(error)});}}
   await refresh();window.ScoreList.enqueue(items);return;
  }
  if(pdfs.length){await runPdfBatch(pdfs);return;}
  if(await workspace.flush()===false)throw Error('当前修改尚未保存，请先处理编辑框或保存错误');
  const file=list[0];if(/\.json$/i.test(file.name)){workspace.show('convert');const review=JSON.parse(await file.text());if(!review||!Array.isArray(review.notes))throw Error('复核文件不正确');const catalog=await refresh(),source=[...catalog.builtins,...catalog.imports].find(row=>row.sha256===review.source_sha256);if(source)workspace.openProject(await api.catalog_open(source.id,120));workspace.importReview(review);select.value=currentId=source?.id||'';return;}
  if(/\.pgl(?:pack)?$/i.test(file.name)){workspace.show('library');const bytes=await file.arrayBuffer();try{if(/\.pglpack$/i.test(file.name))await GlovePack.unpack(bytes);else GlovePack.validatePgl(new Uint8Array(bytes));}catch(error){$('pgl').value='';$('pgl').dispatchEvent(new Event('change',{bubbles:true}));throw error;}const transfer=new DataTransfer();transfer.items.add(file);$('pgl').files=transfer.files;$('pgl').dispatchEvent(new Event('change',{bubbles:true}));workspace.notice('曲谱已就绪，上传位置已选好');return;}
  workspace.notice('可拖入 PDF、PGL、PGLPACK 或复核 JSON 文件',true);
 }
 window.GloveCatalog={refresh,open:id=>enqueue(()=>open(id)),current:()=>currentId,rows:()=>catalogRows};
 workspace.importFiles=files=>{const list=Array.from(files||[]),epoch=intakeEpoch;return enqueue(()=>epoch===intakeEpoch?importFiles(list):workspace.notice('已取消后续导入'));};
 $('pdf').multiple=true;
 $('pdf').onchange=async()=>{const files=Array.from($('pdf').files||[]);try{await workspace.importFiles(files);}catch(error){workspace.notice(error.message||String(error),true);}finally{$('pdf').value='';}};
 await refresh();
 document.addEventListener('click',event=>{if(event.target.closest('#desktop-debug-open,a[href*="web_piano_glove"]')){const home=document.getElementById('comic-home-tab'),onHome=home&&(home.classList.contains('selected')||home.getAttribute('aria-current')==='page');const tab=onHome?'home':document.querySelector('.desktop-navigation [data-tab].selected')?.dataset.tab||'home';try{sessionStorage.setItem('glove-return-tab',tab);}catch{}}},true);
 const reopen=async()=>{const previous=await api.restore_workspace();workspace.restore(previous);const catalogue=await refresh(),all=[...catalogue.builtins,...catalogue.imports],selected=all.find(row=>String(row.id)===String(previous.score_id||''))||all.find(row=>row.sha256===previous.project?.source_sha256);if(selected){select.value=selected.id;currentId=selected.id;}};
 // 新启动不自动打开上一首：只记下来，由用户点「继续」。切换页面回来才自动恢复。
 const launch=api.launch_state?await api.launch_state():null;
 if(launch){workspace.restore({ui:launch.ui});if(launch.last_name)window.GloveResume={name:launch.last_name,open:()=>{window.GloveResume=null;workspace.show('convert');workspace.notice('正在打开上次的曲谱…');return enqueue(async()=>{await reopen();workspace.show('convert');});}};window.ComicShell?.home(true);window.dispatchEvent(new Event('glove-resume'));}else{await reopen(); /* 11-05 用户：从调手套回来别自动打开校对页，回到去之前的那页 */let back=null;try{back=sessionStorage.getItem('glove-return-tab');sessionStorage.removeItem('glove-return-tab');}catch{}if(back==='convert'){workspace.show('convert');window.ScoreList?.show?.();}else if(back&&back!=='home'){document.querySelector('.desktop-navigation [data-tab="'+back+'"]')?.click();}else window.ComicShell?.home(true);}
 const staged=await api.take_staged_files();if(staged.length)await workspace.importFiles(staged.map(row=>new File([Uint8Array.from(atob(row.content),c=>c.charCodeAt(0))],row.name)));
 document.addEventListener('change',event=>{if(event.target.closest('#convert,.settings'))workspace.queueSave(false);});
 document.addEventListener('click',event=>{if(event.target.closest('#convert,[data-tab]'))setTimeout(()=>workspace.queueSave(false),30);});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>mount().catch(error=>console.error(error)),{once:true});else mount().catch(error=>console.error(error));
})();
