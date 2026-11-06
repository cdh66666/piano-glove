/* Native window presentation. Existing controls retain their IDs and handlers. */
(() => {
 'use strict';
 function mount(){
  const body=document.body;
  if(!body.classList.contains('native-app')||body.dataset.desktopShell==='ready')return;
  body.dataset.desktopShell='ready';
  const $=id=>document.getElementById(id),header=body.querySelector(':scope > header'),nav=body.querySelector(':scope > nav'),main=body.querySelector(':scope > main');
  if(!header||!nav||!main)return;
  const icon=(content,viewBox='0 0 24 24')=>'<svg viewBox="'+viewBox+'" fill="none" aria-hidden="true">'+content+'</svg>';
  const brand=document.createElement('div');brand.className='desktop-brand';
  brand.innerHTML=icon('<rect x="3.5" y="4.5" width="25" height="23" rx="3" stroke="currentColor" stroke-width="1.5"/><path d="M10 5v22M16 5v22M22 5v22" stroke="currentColor" stroke-width="1.2"/><path d="M8 5h4v12H8zm6 0h4v12h-4zm6 0h4v12h-4z" fill="currentColor"/>','0 0 32 32');
  brand.append(header.querySelector('h1'));header.prepend(brand);header.classList.add('desktop-header');
  nav.classList.add('desktop-navigation');
  const libraryTab=nav.querySelector('[data-tab="library"]');if(libraryTab)libraryTab.textContent='曲库';
  const actions=document.createElement('div');actions.className='desktop-header-actions';
  const settings=document.createElement('button');settings.type='button';settings.id='desktop-settings-open';settings.className='desktop-icon-button';settings.title='设置';settings.setAttribute('aria-label','设置');settings.setAttribute('aria-expanded','false');settings.setAttribute('aria-controls','desktop-settings');
  settings.innerHTML=icon('<path d="m9 3-.7 2.2-2 .9-2.1-.5-1.5 2.6 1.4 1.7-.2 2.2L2.5 14 4 16.6l2.2-.3 1.8 1.3.5 2.2h3l.9-2.1 2.1-.7 2 .9 2.1-2.1-.9-2 .7-2.1 2.1-.9v-3l-2.2-.5-1.3-1.8.3-2.2L16.7 2l-1.6 1.4-2.2.2L11.6 2Z" transform="translate(1 1) scale(.9)" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="11.8" cy="10.9" r="3" stroke="currentColor" stroke-width="1.5"/>');
  const debug=document.createElement('a');debug.id='desktop-debug-open';debug.className='desktop-debug-link';debug.href='web_piano_glove.html?simple=1';debug.textContent='调手套';
  actions.append($('connection'),debug,settings,$('stop'));
  // 顶栏只给小白看“手套（USB）· 已就绪”；原文字（串口、型号）留给连接逻辑和悬停提示。
  const pill=$('connection');if(pill){const friendly=()=>{const text=pill.textContent;pill.dataset.friendly=text.replace(/^USB \S+ · [^·]+ · /,'手套（USB） · ').replace(/^USB \S+ · /,'手套（USB） · ');pill.title=text;};new MutationObserver(friendly).observe(pill,{childList:true,characterData:true,subtree:true});friendly();}
  // Window capture runs before the native link router, so a cancelled entry never navigates.
  // 11-04 用户：调手套是客户收到后自己要做的（每个人手不一样），不再拦截
  header.append(nav,actions);

  const parameters=document.createElement('aside');parameters.className='desktop-parameters';parameters.setAttribute('aria-label','练习参数');
  const parameterHeading=document.createElement('h2');parameterHeading.textContent='练习参数';parameters.append(parameterHeading);
  const controls=main.querySelector(':scope > .settings');
  if(controls){
   for(const id of ['tempo','amplitude','hold']){
    const input=$(id),label=input?.closest('label');if(!label)continue;
    const caption=document.createElement('span');caption.className='desktop-range-caption';
    const text=document.createElement('span');text.textContent=[...label.childNodes].filter(node=>node.nodeType===3).map(node=>node.textContent.trim()).join(' ');input.setAttribute('aria-label',text.textContent);
    for(const node of [...label.childNodes])if(node.nodeType===3)node.remove();
    caption.append(text,$(id+'-label'));label.prepend(caption);
   }
   parameters.append(controls);
  }
  const pose=$('feedback-panel')?.querySelector('.pose-feedback');
  if(pose){const detail=document.createElement('details');detail.className='desktop-position-details';const summary=document.createElement('summary');summary.textContent='拇指姿态反馈';detail.append(summary,pose);parameters.append(detail);}
  main.insertBefore(parameters,main.querySelector('footer'));

  const handHeading=$('feedback-panel')?.querySelector('h2');if(handHeading)handHeading.textContent='手指训练';
  const fingerCards=$('fingers')?.querySelectorAll('.finger-card')||[];
  fingerCards.forEach((button,index)=>{
   const number=document.createElement('span');number.className='desktop-finger-number';number.setAttribute('aria-hidden','true');number.textContent=String(index+1);button.prepend(number);
   const meter=button.querySelector('.position-meter'),value=$('meter-value-'+(index+2));
   if(meter&&value){const reading=document.createElement('span');reading.className='desktop-finger-reading';reading.append('位置 ',value);meter.prepend(reading);}
  });
  const trainHeading=$('train')?.querySelector('h2');if(trainHeading)trainHeading.textContent='连续练习';
  for(const button of document.querySelectorAll('[data-pattern]'))button.textContent={single:'逐指练习',combination:'组合练习',alternating:'交替练习'}[button.dataset.pattern]||button.textContent;
  if($('fastest-training')){$('fastest-training').textContent='最快速度';$('fastest-training').parentElement?.append($('fastest-training'));}

  const drawer=document.createElement('aside');drawer.id='desktop-settings';drawer.className='desktop-settings';drawer.hidden=true;drawer.setAttribute('role','dialog');drawer.setAttribute('aria-modal','true');drawer.setAttribute('aria-label','设置');
  drawer.innerHTML='<div class="desktop-settings-card"><div class="desktop-settings-heading"><h2>设置</h2><button id="desktop-settings-close" type="button" aria-label="关闭设置">关闭</button></div><div class="desktop-device-summary"><span>设备连接</span><p id="desktop-connection-detail"></p></div><a class="desktop-settings-link" href="web_piano_glove.html?simple=1"><span>调试与校准</span><span aria-hidden="true">›</span></a><button class="desktop-settings-link" id="desktop-phone-info" type="button"><span>手机连接说明</span><span aria-hidden="true">›</span></button><a class="desktop-settings-link" href="guide.html"><span>使用说明</span><span aria-hidden="true">›</span></a><a class="desktop-settings-link" href="guide.html#licenses"><span>第三方许可</span><span aria-hidden="true">›</span></a></div>';
  body.append(drawer);
  function closeSettings(){drawer.hidden=true;settings.setAttribute('aria-expanded','false');settings.focus();}
  settings.onclick=()=>{drawer.hidden=false;settings.setAttribute('aria-expanded','true');$('desktop-settings-close').focus();};
  $('desktop-settings-close').onclick=closeSettings;
  // Port choice: auto finds the current CP210x board; another USB board can be picked by hand.
  const portRow=document.createElement('label');portRow.className='desktop-port';portRow.textContent='串口 ';
  const portSelect=document.createElement('select');portSelect.id='desktop-port';portSelect.setAttribute('aria-label','选择手套串口');
  const portNote=document.createElement('small');portNote.id='desktop-port-note';portRow.append(portSelect,portNote);
  drawer.querySelector('.desktop-device-summary').append(portRow);
  async function portJson(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||j.msg||'串口操作失败');return j;}
  async function loadPorts(){try{const st=await portJson('/api/status'),ports=(await portJson('/api/ports')).ports||[];const options=[new Option('自动（当前型号 CP210x 直接连接）','')];for(const p of ports){if(p.score===-1000)continue;const desc=String(p.desc||'').replace(/\s*\(COM\d+\)$/,''),o=new Option(p.device+(p.candidate?'（手套）':' · '+desc.slice(0,18)),p.device);o.title=p.device+' · '+desc;options.push(o);}portSelect.replaceChildren(...options);portSelect.value=st.fixed&&ports.some(p=>p.device===st.fixed)?st.fixed:'';portNote.textContent=st.fixed?'已手动指定 '+st.fixed:'换了主控时在这里选它的串口';}catch(error){portNote.textContent='读取串口失败：'+error.message;}}
  portSelect.onchange=async()=>{const target=portSelect.value;portSelect.disabled=true;portNote.textContent=target?'正在连接 '+target+'…':'正在自动查找…';try{const r=await portJson('/api/connect',target?{port:target,baud:115200}:{auto:true});portNote.textContent=(r.msg||'已切换')+'；不会自动开始动作';}catch(error){portNote.textContent='连接失败：'+error.message;}finally{portSelect.disabled=false;}};
  settings.addEventListener('click',loadPorts);
  const usbHelp=$('usbDriverHelpEntry');
  if(usbHelp){usbHelp.classList.add('desktop-settings-link');usbHelp.innerHTML='<span>USB / 驱动帮助</span><span aria-hidden="true">›</span>';drawer.querySelector('.desktop-device-summary').after(usbHelp);usbHelp.addEventListener('click',closeSettings,{capture:true});}
  for(const link of drawer.querySelectorAll('a[href]'))link.addEventListener('click',closeSettings,{capture:true});
  $('desktop-phone-info').onclick=()=>{closeSettings();window.NativeApp?.phoneInfo?.();};
  drawer.addEventListener('click',event=>{if(event.target===drawer)closeSettings();});
  document.addEventListener('keydown',event=>{if(drawer.hidden)return;if(event.key==='Escape'){event.preventDefault();closeSettings();}if(event.key==='Tab'){const focusable=[...drawer.querySelectorAll('button,a[href],select')],first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});
  const connection=$('connection');
  function connectionChanged(){if(!/USB |热点/.test(connection.title||''))connection.title=connection.textContent;connection.classList.toggle('desktop-ready',connection.textContent.includes('已就绪'));$('desktop-connection-detail').textContent=connection.textContent+(connection.title&&connection.title!==connection.textContent?'（'+connection.title+'）':'');}
  connectionChanged();new MutationObserver(connectionChanged).observe(connection,{childList:true,characterData:true,subtree:true});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
