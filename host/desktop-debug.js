/* Native-only debug presentation; no connection or motor commands are added. */
(function(root){
 'use strict';
 const preferenceKey='piano-native-debug-ui-v1';
 const inputIds=['calSecs','rtDepth','rtSpeed','rtCycles','speed','fSpeed','fDepth','selMap','nLow','nHigh','followVel','loop','closedLoop','autoOff','sndOn','sndVol','sndAll','demoOne','demoSlot','rawCmd'];
 function assetPath(value){const path=String(value||'').split('?',1)[0];return /^\/?assets\/score-excerpts\/[A-Za-z0-9_-]+\.png$/.test(path)?'/'+path.replace(/^\//,''):null;}
 function assetLoader(ready,makeUrl){
  const cache=new Map();
  return path=>{
   const key=assetPath(path);if(!key)return Promise.reject(Error('原谱图片路径不正确'));
   if(!cache.has(key))cache.set(key,(async()=>{try{const api=await ready,reply=await api.request(key,'GET',null,false,{});if(reply.status!==200||!reply.binary||!String(reply.body).startsWith('iVBORw0KGgo'))throw Error('原谱图片未能读取');return makeUrl(reply.body);}catch(error){cache.delete(key);throw error;}})());
   return cache.get(key);
  };
 }
 function collectInputs(document){const values={};for(const id of inputIds){const input=document.getElementById(id);if(input)values[id]=input.type==='checkbox'?!!input.checked:String(input.value);}values.combination=[...document.querySelectorAll('.demoPick')].map(input=>({value:input.value,checked:!!input.checked}));return values;}
 function restoreInputs(document,values){
  for(const id of inputIds){const input=document.getElementById(id),value=values?.[id];if(!input||value===undefined)continue;if(input.type==='checkbox'){if(typeof value==='boolean')input.checked=value;}else if(typeof value==='string'){if(input.tagName==='SELECT'&&![...input.options].some(option=>option.value===value))continue;input.value=value;}}
  for(const choice of values?.combination||[]){const input=[...document.querySelectorAll('.demoPick')].find(node=>node.value===choice.value);if(input&&typeof choice.checked==='boolean')input.checked=choice.checked;}
  for(const [id,label,suffix,zero] of [['speed','speedLabel','%'],['fSpeed','fSpeedLabel','','最快'],['fDepth','fDepthLabel','%'],['sndVol','sndVolLabel','%'],['rtDepth','rtDepthL','%'],['rtSpeed','rtSpeedL','','最快']]){const input=document.getElementById(id),output=document.getElementById(label);if(input&&output)output.textContent=zero&&Number(input.value)===0?zero:input.value+suffix;}
 }
 async function leaveDebug(runtime,navigate){
  const active=runtime.deliveryDemoBusy?.()||runtime.pianoStrictTrainingActive?.()||runtime.PianoDeliveryHooks?.getState?.().playing;
  if(active)await runtime.deliveryDemoStop();
  await navigate('software');
 }
 const exported={assetPath,assetLoader,collectInputs,restoreInputs,inputIds,leaveDebug};
 if(typeof module!=='undefined'&&module.exports)module.exports=exported;
 if(!root.document)return;
 function mount(){
  const document=root.document,body=document.body,$=id=>document.getElementById(id),frame=$('demoRoot'),header=$('demoTop');
  if(!body.classList.contains('native-app')||!frame||!header||body.dataset.desktopDebug==='ready')return;
  const notice=text=>{if($('demoNotice'))$('demoNotice').textContent=text;};
  const back=$('native-back')||document.createElement('button');back.id='native-back';back.type='button';back.removeAttribute('style');back.textContent='返回主界面';back.setAttribute('aria-label','返回主界面');
  back.onclick=async()=>{if(back.disabled)return;savePreferences();back.disabled=true;try{await leaveDebug(root,page=>root.NativeApp.navigate(page));}catch(error){back.disabled=false;notice('返回未完成：'+error.message);}};
  header.prepend(back);header.querySelector('h1').textContent='调手套';
  const device=document.createElement('details');device.className='desktop-debug-device';
  const summary=document.createElement('summary');summary.textContent='设备设置';
  const deviceBody=document.createElement('div');deviceBody.className='desktop-debug-device-body';
  const portLabel=document.createElement('label');portLabel.append('USB 串口 ',$('demoPort'));
  const help=document.createElement('button');help.type='button';help.textContent='USB / 驱动帮助';help.onclick=()=>{device.open=false;root.PianoUsbDriver?.open();};
  deviceBody.append(portLabel,$('demoFlash'),help);device.append(summary,deviceBody);header.insertBefore(device,$('demoStop'));
  if($('demoEnrollNext'))$('demoFoot').append($('demoEnrollNext'));

  const manualCalibration=$('demoManualCalibration'),manualActions=$('demoManualActions');
  for(const panel of [manualCalibration,manualActions])if(panel){panel.hidden=false;panel.open=false;}
  if(manualCalibration)manualCalibration.querySelector('summary').textContent='手动端点与方向';
  if(manualCalibration){
   manualCalibration.addEventListener('toggle',()=>{manualCalibration.querySelector('summary').textContent=manualCalibration.open?'返回自动校准':'手动端点与方向';});
   manualCalibration.querySelector('h2').textContent='手动记录六轴端点';
   manualCalibration.querySelector('.demoCalibrationHeading').append($('demoValidationOpen'));
   const pressed=$('demoPress'),capturePressed=pressed.onclick,slotSelect=$('demoSlot');
   const pressCaption=()=>{pressed.textContent=Number(slotSelect.value)<5?'记录按下 · 下一指':'记录按下／侧摆';};
   slotSelect.addEventListener('change',pressCaption);pressCaption();
   pressed.onclick=async event=>{const slot=Number(slotSelect.value),before=root.PianoDeliveryDemo?.state?.().samples?.[slot];await capturePressed.call(pressed,event);const after=root.PianoDeliveryDemo?.state?.().samples?.[slot];if(after&&after!==before&&after.range&&slot<5){slotSelect.value=String(slot+1);pressCaption();notice('已记录，下一步：'+slotSelect.selectedOptions[0].textContent+'抬起后点记录');}};
  }
  if(manualActions)manualActions.querySelector('summary').textContent='单指与组合参数';
  // Score playback lives in the main library (firmware-timed); the host-timed song demo
  // here stalls on USB latency, so the debug page keeps only setup and motion checks.
  if($('demoTabSongs'))$('demoTabSongs').hidden=true;
  if($('demoTabCalibration'))$('demoTabCalibration').textContent='① 按我的手调';
  const actionPanel=document.createElement('section');actionPanel.id='desktopDebugActions';actionPanel.className='demo-panel';actionPanel.hidden=true;
  const actionBlock=$('demoActionProgress')?.closest('.demoBlock');
  if(actionBlock){actionPanel.append(actionBlock);actionBlock.querySelector('h2').textContent='动作测试';}
  frame.insertBefore(actionPanel,$('demoFoot'));
  const actionsTab=document.createElement('button');actionsTab.id='desktopDebugActionsTab';actionsTab.type='button';actionsTab.textContent='② 试一试';$('demoTabs').insertBefore(actionsTab,$('demoTabSongs'));
  if(manualActions){manualActions.open=true;manualActions.querySelector('summary').textContent='指定手指与组合';}
  for(const [id,label] of [['demoQuickSingle','逐指测试'],['demoQuickTogether','全手组合'],['demoQuickAlternate','五指交替']])if($(id))$(id).lastChild.textContent=label;
  function closeActions(){actionPanel.hidden=true;body.classList.remove('desktop-debug-actions-open');actionsTab.classList.remove('active');}
  actionsTab.onclick=()=>{if(root.deliveryDemoBusy?.()){notice('先停下当前动作，再切到「试一试」…');$('demoStop')?.click();let tries=0;const again=()=>{if(!root.deliveryDemoBusy?.())actionsTab.onclick();else if(++tries<20)setTimeout(again,200);else notice('还停不下来，请点右上角「停止」');};setTimeout(again,200);return;} /* 11-05 用户：试一试有时点了没反应——原来手套在动时只在底下小字提示 */$('demoTabCalibration').click();if(manualActions)manualActions.open=true;actionPanel.hidden=false;body.classList.add('desktop-debug-actions-open');$('demoTabs').querySelectorAll('button').forEach(node=>node.classList.toggle('active',node===actionsTab));savePreferences();};
  // 连上手套后原页面会再把「行程校准」标成选中；动作测试开着时只亮它自己。
  new MutationObserver(()=>{if(body.classList.contains('desktop-debug-actions-open'))for(const node of $('demoTabs').querySelectorAll('button.active'))if(node!==actionsTab)node.classList.remove('active');}).observe($('demoTabs'),{subtree:true,attributes:true,attributeFilter:['class']});
  const next=$('demoEnrollNext'),originalNext=next?.onclick;
  if(next)next.onclick=event=>/动作展示|动作测试/.test(next.textContent)?actionsTab.click():originalNext?.call(next,event);
  // The song tab is hidden here, so the post-calibration step points at motion checks.
  if(next){const relabel=()=>{const label=next.querySelector('.demoNextLabel');if(label&&label.textContent.includes('开始曲目'))label.textContent='下一步：动作测试';};new MutationObserver(relabel).observe(next,{childList:true,characterData:true,subtree:true});relabel();}
  const calibrationProgress=$('demoCalibrationProgress');
  if(calibrationProgress)new MutationObserver(()=>{if(calibrationProgress.textContent==='点击右侧单指、组合或交替。')calibrationProgress.textContent='点击上方「动作测试」，选择单指、组合或交替。';}).observe(calibrationProgress,{childList:true,characterData:true,subtree:true});

  // Reuse the original engineering controls instead of maintaining a second set.
  const originalMain=body.querySelector(':scope > main'),tools=document.createElement('section');tools.id='desktopDebugTools';tools.className='demo-panel';tools.hidden=true;
  const toolsNav=document.createElement('nav');toolsNav.className='desktop-debug-tools-nav';toolsNav.setAttribute('aria-label','更多调试功能');
  for(const [page,label]of[['connect','连接信息'],['assign','编号映射'],['cal','手动校准'],['test','单指与测速'],['play','MIDI 演奏'],['log','命令日志']]){const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.debugPage=page;button.onclick=()=>{document.querySelector('#tabbar [data-p="'+page+'"]').click();toolsNav.querySelectorAll('button').forEach(node=>node.classList.toggle('active',node===button));savePreferences();};toolsNav.append(button);}
  tools.append(toolsNav);if(originalMain)tools.append(originalMain);frame.insertBefore(tools,$('demoFoot'));
  const toolsTab=document.createElement('button');toolsTab.id='desktopDebugToolsTab';toolsTab.type='button';toolsTab.textContent='更多调试';toolsTab.hidden=true;$('demoTabs').append(toolsTab);
  function engineering(enabled){const simple=body.classList.contains('pg-simple');if(simple===enabled)$('simpleEngineering')?.click();}
  function closeTools(){tools.hidden=true;body.classList.remove('desktop-debug-tools-open');toolsTab.classList.remove('active');engineering(false);}
  toolsTab.onclick=()=>{closeActions();engineering(true);tools.hidden=false;body.classList.add('desktop-debug-tools-open');$('demoTabs').querySelectorAll('button').forEach(node=>node.classList.toggle('active',node===toolsTab));if(!toolsNav.querySelector('.active'))toolsNav.querySelector('[data-debug-page="connect"]').click();savePreferences();};
  for(const id of ['demoTabEnrollment','demoTabCalibration','demoTabSongs'])$(id)?.addEventListener('click',()=>{closeActions();closeTools();setTimeout(savePreferences,0);},{capture:true});

  let restoring=false;
  function savePreferences(){if(restoring)return;try{root.localStorage.setItem(preferenceKey,JSON.stringify({inputs:collectInputs(document),song:document.querySelector('.demoSong.selected')?.dataset.song||'0',view:!actionPanel.hidden?'actions':!tools.hidden?'tools':$('demoSongs')?.hidden===false?'songs':$('demoEnrollment')?.hidden===false?'enroll':'cal',page:toolsNav.querySelector('.active')?.dataset.debugPage||'connect'}));}catch{}}
  function restorePreferences(){let saved;try{saved=JSON.parse(root.localStorage.getItem(preferenceKey)||'null');}catch{}if(!saved)return;restoring=true;restoreInputs(document,saved.inputs);document.querySelector('.demoSong[data-song="'+String(saved.song).replace(/[^0-9]/g,'')+'"]')?.click();if(saved.view==='actions')actionsTab.click();else if(saved.view==='enroll')$('demoTabEnrollment')?.click();restoring=false;}
  document.addEventListener('input',savePreferences);document.addEventListener('change',savePreferences);document.addEventListener('click',event=>{if(event.target.closest?.('.demoSong'))setTimeout(savePreferences,0);});restorePreferences();

  const urls=new Set(),load=assetLoader(root.NativeApp.ready,base64=>{const url=URL.createObjectURL(new Blob([Uint8Array.from(atob(base64),character=>character.charCodeAt(0))],{type:'image/png'}));urls.add(url);return url;});
  const imageError=document.createElement('p');imageError.id='desktopDebugImageError';imageError.hidden=true;imageError.setAttribute('role','status');$('demoScoreExcerpt')?.append(imageError);
  async function resolveImage(image){const source=image.getAttribute('src'),path=assetPath(source);if(!path)return;image.dataset.nativeAssetState='loading';imageError.hidden=true;try{const url=await load(path);if(image.getAttribute('src')!==source)return;image.src=url;image.dataset.nativeAssetState='ready';}catch(error){if(image.getAttribute('src')!==source)return;image.dataset.nativeAssetState='failed';imageError.textContent=error.message+'，请重新选择曲目';imageError.hidden=false;}}
  const image=$('demoScoreImage');if(image){new MutationObserver(records=>{if(records.some(record=>record.attributeName==='src'))resolveImage(image);}).observe(image,{attributes:true,attributeFilter:['src']});resolveImage(image);}
  root.addEventListener('pagehide',()=>{savePreferences();for(const url of urls)URL.revokeObjectURL(url);},{once:true});
  function handFitted(){try{return root.localStorage.getItem('piano-hand-fitted')==='1';}catch{return false;}}
  function fitForCustomer(){
   const tabs=$('demoTabs'),enroll=$('demoTabEnrollment');if(enroll&&tabs){enroll.textContent='⓪ 舵机编号';enroll.classList.add('desktop-debug-aftersales');tabs.prepend(enroll); /* 11-05 用户：不写售后，写 0，放在 1、2 前面 */}
   const mount=$('demoMountOpen')?.closest('.demoSetupEntries')||$('demoMountOpen');mount?.style.setProperty('display','none','important'); // 装舵机臂是出厂/售后的事
   if($('demoCalibrationGuide'))$('demoCalibrationGuide').textContent='按你的手调一下（约 1 分钟）';
   const progress=$('demoCalibrationProgress');if(progress&&/先抬起/.test(progress.textContent))progress.textContent='① 戴好手套　② 点「开始调」　③ 每根手指按提示慢慢弯到底，再伸直';
   const start=$('demoCalStart');const label=()=>{if(start&&/校准/.test(start.textContent)&&!/单独/.test(start.textContent))start.textContent=handFitted()?'再调一遍':'开始调';};
   if(start){label();new MutationObserver(label).observe(start,{childList:true,characterData:true,subtree:true});}
   // 调完（页面提示去做动作）就记下来：开始页不再提醒
   if(progress)new MutationObserver(()=>{if(/单指、组合或交替/.test(progress.textContent)){try{root.localStorage.setItem('piano-hand-fitted','1');}catch{}label();}}).observe(progress,{childList:true,characterData:true,subtree:true});
  }
  // 会改动手套的按钮再确认一次（第一次调手套不问）。
  const guarded={demoCalStart:'再调一遍？上次调的会被换掉。',demoEnrollStart:'重新编号会改动 6 个舵机的编号，弄错了手套就动不了。确定要重新编号吗？',demoFlash:'烧录会改写手套里的程序，中途断开可能让手套无法使用。确定要烧录吗？'};
  root.addEventListener('click',event=>{const button=event.target.closest?.('button'),warning=button&&!button.disabled&&guarded[button.id];if(button?.dataset.appConfirmed==='1'){delete button.dataset.appConfirmed;return;}if(warning&&(button.id!=='demoCalStart'||(handFitted()&&!root.deliveryDemoBusy?.()))){event.preventDefault();event.stopImmediatePropagation();(root.AppConfirm?root.AppConfirm(warning):Promise.resolve(root.confirm(warning))).then(ok=>{if(ok){button.dataset.appConfirmed='1';button.click();}});}},true);
  // 11-04 用户：调手套是客户收到后自己做的（每个人手不一样）→ 默认进「按我的手调」，说明三步；舵机编号挪到最后标「售后」
  fitForCustomer();
  if(!root.deliveryDemoBusy?.()){
   $('demoTabCalibration')?.click();
   // 连上手套后原页面可能自己切到「舵机编号」；刚进来 8 秒内用户没点过标签，就留在「按我的手调」
   let touched=false;$('demoTabs')?.addEventListener('pointerdown',()=>{touched=true;},{capture:true});
   const keep=new MutationObserver(()=>{if(!touched&&$('demoEnrollment')&&!$('demoEnrollment').hidden&&!root.deliveryDemoBusy?.())$('demoTabCalibration')?.click();});
   if($('demoEnrollment'))keep.observe($('demoEnrollment'),{attributes:true,attributeFilter:['hidden']});
   setTimeout(()=>keep.disconnect(),8000);
  }
  body.dataset.desktopDebug='ready';document.documentElement.classList.remove('native-preparing');
 }
 if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})(typeof window==='undefined'?globalThis:window);
