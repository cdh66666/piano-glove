(function(root){
'use strict';
// The in-window guide is an about:srcdoc iframe. WebView2 injects pywebview
// only into the top document, so the guide must use its owning window's bridge.
const parentReady=(()=>{try{return root.parent!==root&&root.location.href==='about:srcdoc'?root.parent?.NativeApp?.ready:null;}catch{return null;}})();
const ready=new Promise(resolve=>{if(root.pywebview?.api)resolve(root.pywebview.api);else if(parentReady&&typeof parentReady.then==='function')parentReady.then(resolve);else root.addEventListener('pywebviewready',()=>resolve(root.pywebview.api),{once:true});});
const previewUrls=new Set(),pending=new Set();let controller='',leaving=false;
const bytes64=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
async function as64(value){const bytes=new Uint8Array(await new Blob([value]).arrayBuffer());let text='';for(let at=0;at<bytes.length;at+=16384)text+=String.fromCharCode(...bytes.subarray(at,at+16384));return btoa(text);}
async function encode(body){if(body==null)return {body:null,raw:false};if(body instanceof URLSearchParams)return {body:body.toString(),raw:false};if(body instanceof ArrayBuffer||ArrayBuffer.isView(body)||body instanceof Blob)return {body:await as64(body),raw:true};return {body,raw:false};}
function pathOf(value){const text=String(value);if(text.startsWith('/api/'))return text;const url=new URL(text,root.location.href);if(url.pathname.startsWith('/api/'))return url.pathname+url.search;throw Error('这个操作不属于软件接口');}
function aborted(){return new DOMException('请求已取消','AbortError');}
async function dispatch(path,options={},jsonText=false){
 const signal=options.signal;if(signal?.aborted)throw aborted();
 const headers=Object.fromEntries(new Headers(options.headers||{}).entries());
 if(jsonText)headers['x-piano-json-text']='1';
 if(headers['x-piano-controller'])controller=headers['x-piano-controller'];
 const payload=await encode(options.body),api=await ready;if(signal?.aborted)throw aborted();
 const operation=api.request(pathOf(path),options.method||'GET',payload.body,payload.raw,headers);
 pending.add(operation);operation.then(()=>pending.delete(operation),()=>pending.delete(operation));
 if(!signal)return operation;
 return new Promise((resolve,reject)=>{const cancel=()=>reject(aborted());signal.addEventListener('abort',cancel,{once:true});operation.then(v=>{signal.removeEventListener('abort',cancel);if(!signal.aborted)resolve(v);},e=>{signal.removeEventListener('abort',cancel);reject(e);});});
}
async function preview(body){
 if(!body?.source_preview?.available)return body;
 for(const page of body.source_preview.pages||[]){
  if(!/^\/api\/software\/source\/[0-9a-f]{64}\/\d+$/.test(page.image_url||''))continue;
  const reply=await dispatch(page.image_url);
  if(reply.status!==200||!reply.binary||!String(reply.body).startsWith('iVBORw0KGgo'))throw Error('原谱图片未能读取');
  const url=URL.createObjectURL(new Blob([bytes64(reply.body)],{type:'image/png'}));previewUrls.add(url);page.image_url=url;
 }
 return body;
}
root.NativeApp={
 ready,
 as64,
 async checkProject(project,options={}){
  if(leaving)return new Promise(()=>{});
  const signal=options.signal;if(signal?.aborted)throw aborted();
  const api=root.pywebview?.api;
  if(typeof api?.check_project==='function'){
   const headers=new Headers(options.headers||{});if(headers.get('x-piano-controller'))controller=headers.get('x-piano-controller');
   // pywebview synchronously snapshots the object for its bridge. Avoid
   // stringify(project), faux HTTP bytes and Response copies around that step.
   const operation=api.check_project(project);
   pending.add(operation);operation.then(()=>pending.delete(operation),()=>pending.delete(operation));
   if(!signal)return operation;
   return new Promise((resolve,reject)=>{const cancel=()=>reject(aborted());signal.addEventListener('abort',cancel,{once:true});operation.then(v=>{signal.removeEventListener('abort',cancel);if(!signal.aborted)resolve(v);},e=>{signal.removeEventListener('abort',cancel);reject(e);});});
  }
  // Older native APIs and readiness races keep the existing frozen JSON path.
  const response=await root.fetch('/api/software/check',{...options,method:'POST',headers:{...options.headers,'Content-Type':'application/json'},body:JSON.stringify({project})}),value=await response.json();
  if(!response.ok||value.ok===false)throw Error(value.error||'设备请求失败');return value;
 },
 async notice(href){const reply=await dispatch('/'+href);if(reply.status!==200)throw Error('许可文件未能读取');const value=reply.binary?new TextDecoder().decode(bytes64(reply.body)):String(reply.body);const d=document.createElement('dialog');d.style.cssText='width:min(800px,90vw);max-height:85vh;border:1px solid #bbcedd;border-radius:12px;padding:22px;background:#f5f8fb;color:#24394c;font:14px Microsoft YaHei UI';const title=document.createElement('h3');title.textContent=decodeURIComponent(href.split('/').pop());const pre=document.createElement('pre');pre.textContent=value;pre.style.cssText='max-height:60vh;overflow:auto;white-space:pre-wrap;line-height:1.6';const close=document.createElement('button');close.textContent='关闭';close.onclick=()=>{d.close();d.remove();};d.append(title,pre,close);document.body.append(d);d.showModal();},
 async save(data,name){const api=await ready,result=await api.save_file(await as64(data),name);return !!result.saved;},
 ownsPreviewUrl:url=>previewUrls.has(url),
 releasePreview(source){for(const p of source?.pages||[]){if(previewUrls.delete(p.image_url))URL.revokeObjectURL(p.image_url);}},
 async navigate(page){if(leaving)return;if(root.GloveWorkspace?.flush)await root.GloveWorkspace.flush();leaving=true;if(controller)await dispatch('/api/stop',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({controller,scope:'owned'})});await Promise.allSettled([...pending]);await(await ready).open_page(page);},
 async showGuide(){const html=await(await ready).page_html('guide');const d=document.createElement('dialog');d.className='native-guide-dialog';d.style.cssText='width:min(980px,92vw);height:88vh;padding:0;border:1.5px solid #23212B;border-radius:12px;overflow:hidden';const frame=document.createElement('iframe');frame.title='使用说明';frame.style.cssText='display:block;width:100%;height:100%;border:0';frame.srcdoc=html+'<style>#native-back{display:none!important}<\/style>';const close=document.createElement('button');close.type='button';close.textContent='关闭';close.style.cssText='position:absolute;right:18px;top:12px;z-index:2';close.onclick=()=>{d.close();d.remove();};d.addEventListener('close',()=>d.remove());frame.addEventListener('load',()=>{try{frame.contentDocument.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close.click();}});}catch{}});d.append(frame,close);document.body.append(d);d.showModal();close.focus(); /* 11-05：焦点在里面的页面时 Esc 也能关 */},
 addBackButton(){const b=document.createElement('button');b.textContent='返回软件';b.id='native-back';b.style.cssText='position:fixed;right:22px;top:14px;z-index:1000;padding:8px 15px;border:1px solid #dce3eb;border-radius:7px;background:#fff;color:#263649;font:13px Microsoft YaHei UI;cursor:pointer';b.onclick=()=>root.NativeApp.navigate('software');document.body.appendChild(b);},
 async phoneInfo(){const d=document.createElement('dialog');d.className='native-phone-dialog';d.innerHTML='<h3>手机连接</h3><p>连接手套 Wi-Fi 后，系统会打开控制页或显示“登录此网络”。</p><img hidden alt="手机连接二维码"><strong>正在读取热点…</strong><div class="phone-actions"><button class="phone-fallback">没有自动弹出？</button><button class="phone-close">完成</button></div>';document.body.appendChild(d);d.querySelector('.phone-close').onclick=()=>{d.close();d.remove();};d.showModal();try{const info=await(await ready).phone_connection(),image=d.querySelector('img'),label=d.querySelector('strong');image.src=info.wifi_qr||info.page_qr;image.hidden=false;label.textContent=info.ssid?'扫码连接 '+info.ssid:'连接 PIANO_GLOVE_ 开头的手套 Wi-Fi';d.querySelector('.phone-fallback').onclick=()=>{image.src=info.page_qr;label.textContent='用手机扫码打开控制页，无需输入地址';};}catch{d.querySelector('strong').textContent='连接手套 Wi-Fi，点系统的“登录此网络”即可进入';}}
};
root.fetch=async(path,options={})=>{if(leaving)return new Promise(()=>{});const route=pathOf(path).split('?')[0],jsonText=route==='/api/software/check'||route==='/api/software/export';const reply=await dispatch(path,options,jsonText);const value=reply.binary?bytes64(reply.body):reply.body_encoding==='json-text'?reply.body:typeof reply.body==='object'?JSON.stringify(await preview(reply.body)):reply.body;const headers={...reply.headers};delete headers['content-length'];return new Response(value,{status:reply.status,headers});};
navigator.sendBeacon=(path,body)=>{if(!leaving)dispatch(path,{method:'POST',body,headers:{'Content-Type':body?.type||'application/x-www-form-urlencoded'}}).catch(()=>{});return true;};
document.addEventListener('click',event=>{
 const a=event.target.closest?.('a');if(!a||a.hasAttribute('download'))return;const href=a.getAttribute('href')||'';
 if(href.startsWith('#')){const target=document.getElementById(decodeURIComponent(href.slice(1)));if(target){event.preventDefault();target.scrollIntoView({behavior:'smooth',block:'start'});}return;} // 11-05：页内跳转在应用窗口里也能用
 if(href.startsWith('notices/')){event.preventDefault();root.NativeApp.notice(href).catch(error=>{a.textContent=error.message||'许可文件未能读取';});return;}
 let page;if(href.includes('web_piano_glove.html'))page='debug';else if(href.includes('software.html'))page='software';else if(href.includes('guide.html'))page=href.includes('#licenses')?'licenses':'guide';
 if(page==='guide'){event.preventDefault();root.NativeApp.showGuide();}else if(page){event.preventDefault();root.NativeApp.navigate(page);}else if(href.startsWith('assets/')){event.preventDefault();root.NativeApp.notice(href).catch(error=>{a.textContent=error.message||'文件未能读取';});}else if(href==='https://developer.microsoft.com/en-us/microsoft-edge/webview2/'){event.preventDefault();return ready.then(api=>api.open_runtime_download()).then(result=>{if(!result?.opened)throw Error('浏览器未能打开');}).catch(()=>{let hint=a.parentElement?.querySelector('[data-runtime-link-error]');if(!hint){hint=document.createElement('span');hint.dataset.runtimeLinkError='1';hint.setAttribute('role','status');a.after(hint);}hint.textContent=' 浏览器未能打开，请复制网址：'+href;});}else if(/^https?:\/\//.test(href)){event.preventDefault();if(href.includes('192.168.4.1'))root.NativeApp.phoneInfo();}
},true);
function hasFiles(event){return Array.from(event.dataTransfer?.types||[]).includes('Files')||Array.from(event.dataTransfer?.items||[]).some(item=>item.kind==='file');}
function editableDrop(event){return !!event.target?.closest?.('textarea,input:not([type="file"]),[contenteditable="true"]');}
document.addEventListener('dragover',event=>{const files=hasFiles(event),uri=Array.from(event.dataTransfer?.types||[]).includes('text/uri-list');if(editableDrop(event)&&!files&&!uri)return;event.preventDefault();if(event.dataTransfer)event.dataTransfer.dropEffect=files?'copy':'none';if(files&&document.body){let overlay=document.getElementById('native-drop-overlay');if(!overlay){overlay=document.createElement('div');overlay.id='native-drop-overlay';overlay.textContent='松开即可导入';overlay.hidden=true;document.body.appendChild(overlay);}overlay.hidden=false;}},true);
document.addEventListener('dragleave',event=>{if(!event.relatedTarget){const overlay=document.getElementById('native-drop-overlay');if(overlay)overlay.hidden=true;}},true);
document.addEventListener('drop',async event=>{const files=Array.from(event.dataTransfer?.files||[]),fileish=hasFiles(event)||files.length||Array.from(event.dataTransfer?.types||[]).includes('text/uri-list');if(!editableDrop(event)||fileish)event.preventDefault();const overlay=document.getElementById('native-drop-overlay');if(overlay)overlay.hidden=true;if(!files.length){if(fileish&&root.GloveWorkspace)root.GloveWorkspace.notice('未能读取拖入的文件，请再拖一次或点“选择 PDF”。',true);return;}try{if(root.GloveWorkspace?.importFiles){await root.GloveWorkspace.importFiles(files);}else{const staged=await Promise.all(files.map(async file=>({name:file.name,content:await as64(await file.arrayBuffer())})));await(await ready).stage_files(staged);await root.NativeApp.navigate('software');}}catch(error){if(root.GloveWorkspace)root.GloveWorkspace.notice(error.message||String(error),true);}},true);
// 11-05 用户：确认框要软件风格、屏幕中间弹出（系统确认框在最上面一条，难看也容易漏看）
root.AppConfirm=(text,{ok='确定',cancel='取消'}={})=>new Promise(resolve=>{
 const back=document.createElement('div');back.className='app-confirm-back';back.setAttribute('role','dialog');back.setAttribute('aria-modal','true');
 back.style.cssText='position:fixed;inset:0;z-index:2147483000;background:rgba(35,33,43,.35);display:flex;align-items:center;justify-content:center;font-family:"Microsoft YaHei UI","PingFang SC",sans-serif';
 const box=document.createElement('div');box.style.cssText='background:#fff;border:2px solid #23212b;border-radius:16px;box-shadow:5px 5px 0 #23212b;padding:26px 30px 22px;max-width:min(460px,86vw);text-align:center;color:#23212b';
 const msg=document.createElement('p');msg.textContent=text;msg.style.cssText='margin:0 0 20px;font-size:17px;line-height:1.6;font-weight:700';
 const row=document.createElement('div');row.style.cssText='display:flex;gap:12px;justify-content:center';
 const mk=(label,primary)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.style.cssText='min-width:110px;min-height:44px;padding:0 18px;border:2px solid #23212b;border-radius:12px;font-size:16px;font-weight:900;cursor:pointer;box-shadow:2px 2px 0 #23212b;'+(primary?'background:#E8B43A;color:#23212b':'background:#fff;color:#23212b');return b;};
 const no=mk(cancel,false),yes=mk(ok,true);row.append(no,yes);box.append(msg,row);back.append(box);
 const done=v=>{back.remove();document.removeEventListener('keydown',key,true);resolve(v);};
 const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();done(false);}else if(e.key==='Enter'){e.preventDefault();e.stopPropagation();done(true);}};
 no.onclick=()=>done(false);yes.onclick=()=>done(true);back.addEventListener('click',e=>{if(e.target===back)done(false);});
 document.addEventListener('keydown',key,true);(document.body||document.documentElement).append(back);yes.focus();
});
})(window);
