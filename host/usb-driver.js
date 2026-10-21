'use strict';
(function(root){
const official='https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers';
const download='https://www.silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip';
function view(status,connected=false){
 if(connected)return {show:false,title:'USB 已连接',detail:'驱动与串口已就绪。'};
 const state=status?.state||'unavailable';
 if(state==='missing_driver')return {show:true,title:'已检测到主控，需要安装 USB 驱动',detail:'点击“自动安装并连接”即可。程序会下载官方驱动、完成安装，再重新连接。'};
 if(state==='device_error')return {show:true,title:'主控 USB 设备报错',detail:'Windows 已发现 CP2102，但设备未正常工作'+(Number.isInteger(status.problem_code)?'（代码 '+status.problem_code+'）':'')+'。查看驱动帮助并重新检测。'};
 if(state==='ready')return {show:false,title:'串口驱动已就绪',detail:'页面会按现有连接流程重新查找主控。'};
 if(state==='unplugged')return {show:true,title:'未检测到主控 USB',detail:'请接上主控，并使用支持数据传输的 USB 线。接好后会自动重新检测；已接好仍无反应可查看 USB 帮助。'};
 return {show:true,title:'暂时无法确认 USB 驱动状态',detail:'不能据此判断缺少驱动。可查看安装步骤，或在设备管理器核对 CP2102 是否有黄色感叹号。'};
}
const api={view,state:()=>null,open:()=>{},install:()=>{}};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
if(!root.document||!['127.0.0.1','localhost','[::1]'].includes(root.location.hostname))return;
function init(){
 if(document.getElementById('usbDriverDialog'))return;
 const header=document.getElementById('demoTop')||document.querySelector('body>header');
 if(!header)return;
 // The compact console already has its connection button. Keep its layout.
 const help=document.getElementById('demoTop')?null:document.createElement('button');
 if(help){help.id='usbDriverHelpEntry';help.textContent='USB / 驱动帮助';(document.querySelector('nav')||header).append(help);}
 const dialog=document.createElement('dialog');dialog.id='usbDriverDialog';dialog.className='usbDriverDialog';dialog.setAttribute('aria-labelledby','usbDriverGuideTitle');
 dialog.innerHTML=`<div class="usbDriverHeading"><div><small>第一次在这台 Windows 电脑使用</small><h2 id="usbDriverGuideTitle">安装 CP2102 串口驱动</h2></div><button id="usbDriverClose" aria-label="关闭驱动帮助">关闭</button></div><p id="usbDriverGuideState" role="status"></p><ol><li><b>下载官方驱动</b><p>适用于 Windows 10 / 11，选择 CP210x Universal Windows Driver。</p><a class="usbDriverPrimary" href="${download}" target="_blank" rel="noopener noreferrer">下载官方驱动 ZIP</a> <a href="${official}" target="_blank" rel="noopener noreferrer">官网下载页</a></li><li><b>解压，然后在设备管理器安装</b><p>右键 Windows 开始按钮 → 设备管理器 → 其他设备 → 带黄色感叹号的 <strong>CP2102 USB to UART Bridge Controller</strong>。</p><p>右键它 → 更新驱动程序 → 浏览我的电脑以查找驱动程序 → 选择刚解压的文件夹，勾选“包括子文件夹” → 下一步。</p><p class="usbDriverNote">ZIP 中没有安装 EXE 是正常的；请先解压，不要选择 ZIP 文件。Windows 如询问管理员权限，请由电脑使用者确认。</p></li><li><b>看到 COM 口后，回到调试台</b><p>成功后，设备应出现在“端口（COM 和 LPT）”，名称含 Silicon Labs CP210x，后面带 COM 编号。</p><button id="usbDriverCheck" class="usbDriverPrimary">安装完成，重新检测</button></li></ol><p id="usbDriverCheckResult" role="status"></p><details><summary>仍然没有 COM 口？</summary><p>确认使用数据线，重新插拔主控 USB，并检查设备管理器中的错误代码。代码 28 表示缺少驱动；其他错误需要按实际错误处理。安装驱动不需要给舵机重新编号或重新烧录。</p></details>`;
 document.body.append(dialog);
 // The normal path is one click; manual steps stay available as a fallback.
 const guide=document.getElementById('usbDriverGuideTitle');guide.textContent='USB 驱动与自动连接';
 const steps=dialog.querySelector('ol'),fallback=document.createElement('details');fallback.innerHTML='<summary>自动安装遇到问题？查看手动安装步骤</summary>';steps.replaceWith(fallback);fallback.append(steps);
 const install=document.createElement('div');install.className='usbDriverInstallBox';install.innerHTML='<p>自动下载并校验官方驱动，安装后自动检测 COM 口、恢复连接。支持 Silicon Labs 与微软 Windows Update 官方分发。</p><button id="usbDriverInstall" class="usbDriverPrimary">自动安装并连接</button><p class="usbDriverNote">Windows 可能弹出管理员授权窗口，请在系统窗口确认。程序不会卸载现有驱动、重启电脑、重新编号或启动舵机。</p><p id="usbDriverInstallState" role="status"></p>';fallback.before(install);
 let latest=null,connected=false,checking=false,lastCheck=0,starting=false;
 api.state=()=>latest;
 function paint(){const model=view(latest,connected),job=latest?.installation||{},installing=starting||!!job.busy;document.getElementById('usbDriverGuideState').textContent=model.title+'。'+model.detail;document.getElementById('usbDriverCheck').disabled=checking||installing;const canInstall=['missing_driver','device_error'].includes(latest?.state),button=document.getElementById('usbDriverInstall');button.disabled=installing||connected||!canInstall;button.textContent=installing?'正在安装…':'自动安装并连接';document.getElementById('usbDriverInstallState').textContent=job.message||'';document.dispatchEvent(new CustomEvent('usbdriver:state',{detail:{...latest,connected}}));}
 async function read(path,body){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);try{const r=await fetch(path,body===undefined?{cache:'no-store',signal:controller.signal}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});const value=await r.json();if(!r.ok||value.ok===false)throw Error(value.error||'状态服务暂不可用');return value;}finally{clearTimeout(timer);}}
 async function check(force=false){if(checking||!force&&Date.now()-lastCheck<(latest?.installation?.busy?1000:5000))return;checking=true;lastCheck=Date.now();try{const status=await read('/api/status');connected=!!status.connected;if(connected&&!force&&!latest?.installation?.busy){latest={...latest,state:'ready'};return;}const previous=latest?.state;latest=await read('/api/driver'+(force?'?refresh=1':''));if(latest.state==='ready'&&latest.port_available&&previous!=='ready'){await read('/api/ports');document.dispatchEvent(new CustomEvent('usbdriver:ready'));}document.getElementById('usbDriverCheckResult').textContent=latest.state==='ready'?(latest.port_available?'驱动已就绪，调试台会重新连接；不会启动动作。':'驱动正常，正在等待系统分配 COM 口。'):view(latest,connected).detail;}catch(e){if(!connected)latest={...latest,state:'unavailable'};document.getElementById('usbDriverCheckResult').textContent='重新检测未完成，请确认本机调试服务仍在运行。';}finally{checking=false;paint();}}
 async function autoInstall(){if(starting||latest?.installation?.busy||connected)return;starting=true;paint();try{latest={...latest,installation:await read('/api/driver/install',{})};}catch(e){latest={...latest,installation:{busy:false,error:e.message}};}finally{starting=false;lastCheck=0;paint();check(true);}}
 api.open=()=>{paint();if(!dialog.open)dialog.showModal();check(true);};
 if(help)help.onclick=api.open;
 document.getElementById('usbDriverClose').onclick=()=>dialog.close();
 api.install=autoInstall;document.getElementById('usbDriverInstall').onclick=autoInstall;
 document.getElementById('usbDriverCheck').onclick=()=>check(true);
 setInterval(()=>{if(!document.hidden)check();},1000);check();
}
root.PianoUsbDriver=api;
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})(typeof window==='undefined'?globalThis:window);
