/* Native file selection, with an honest fallback for hotspot login WebViews. */
(function(root,factory){'use strict';const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else{root.GloveUploadHelper=api;api.attach(root.document?.getElementById('pgl'));}})(typeof globalThis==='object'?globalThis:this,function(root){
'use strict';
const PHONE_URL='http://192.168.4.1/software.html';
function describeFile(file){
 if(!file)return '';
 const size=Number(file.size),bytes=Number.isFinite(size)&&size>=0?size:0;
 return file.name+' · '+(bytes<1024?bytes+' B':(bytes/1024).toFixed(bytes<10240?1:0)+' KB');
}
function attach(input){
 if(!input||input.dataset.uploadHelper==='1')return null;
 const doc=input.ownerDocument,win=doc.defaultView||root,host=input.parentElement;
 input.dataset.uploadHelper='1';input.classList.add('score-file-native');
 // Unknown score extensions can otherwise leave Android's document provider
 // with no matching file type. Actual PGL/pack validation belongs to uploadScore.
 input.removeAttribute('accept');input.setAttribute('aria-label','选择曲谱文件');
 const area=doc.createElement('div');area.className='score-file-help-area';
 const status=doc.createElement('p');status.className='score-file-selection';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
 const details=doc.createElement('details');details.className='score-file-help';
 const summary=doc.createElement('summary');summary.textContent='选文件没反应？';details.appendChild(summary);
 const explanation=doc.createElement('p');explanation.textContent='系统自动弹出的热点登录窗口可能不支持选择文件。请在手机自带浏览器中打开下面的地址，再选择 .pgl 或 .pglpack。';details.appendChild(explanation);
 const address=doc.createElement('input');address.className='score-browser-address';address.type='url';address.readOnly=true;address.value=PHONE_URL;address.setAttribute('aria-label','手机浏览器地址');details.appendChild(address);
 const actions=doc.createElement('div');actions.className='score-browser-actions';
 const copy=doc.createElement('button');copy.type='button';copy.textContent='复制地址';
 const open=doc.createElement('a');open.href=PHONE_URL;open.target='_blank';open.rel='noopener';open.textContent='尝试在浏览器打开';
 actions.appendChild(copy);actions.appendChild(open);details.appendChild(actions);
 const helpStatus=doc.createElement('p');helpStatus.className='score-browser-copy-status';helpStatus.setAttribute('role','status');helpStatus.textContent='如果仍在热点登录小窗中，请复制地址到手机浏览器。';details.appendChild(helpStatus);
 area.appendChild(status);area.appendChild(details);host.appendChild(area);
 // The desktop program has a real file dialog; the hotspot advice only applies to phones.
 details.addEventListener('toggle',()=>{
  if(!details.open||!(win.NativeApp||doc.body?.classList.contains('native-app')))return;
  explanation.textContent='点【选择文件】后会弹出一个找文件的窗口（可能藏在软件窗口后面，看一下任务栏）。曲谱文件一般在“下载”文件夹或你导出时选的位置，名字以 .pglpack 或 .pgl 结尾。识谱完的曲子不用导出：在【PDF 识谱】页直接点【送到手套，开始弹】更省事。';
  address.hidden=true;actions.hidden=true;helpStatus.hidden=true;
 });
 let pending=false,selection='empty';
 input.addEventListener('click',()=>{
  // A cancelled second selection must not leave the previous file ready to upload.
  input.value='';pending=true;selection='awaiting';
  status.textContent='请选择曲谱；如果没有弹出选择窗口，点“选文件没反应？”';
 });
 input.addEventListener('change',()=>{
  pending=false;const file=input.files?.[0];selection=file?'selected':'empty';
  status.textContent=file?'已选择：'+describeFile(file):'未选中文件';
 });
 input.addEventListener('cancel',()=>{pending=false;selection='cancelled';input.value='';status.textContent='已取消选择；需要上传时请重新选择文件。';});
 win.addEventListener('focus',()=>{
  if(pending&&!input.files?.length){pending=false;selection='empty';status.textContent='未选中文件；如果刚才没有弹出选择窗口，点“选文件没反应？”';}
 });
 copy.addEventListener('click',async()=>{
  let copied=false;
  try{if(win.isSecureContext&&win.navigator?.clipboard){await win.navigator.clipboard.writeText(PHONE_URL);copied=true;}}catch{}
  if(!copied){address.focus();address.select();try{copied=!!doc.execCommand?.('copy');}catch{}}
  helpStatus.textContent=copied?'地址已复制，请粘贴到手机浏览器打开。':'请长按上面的地址复制，再粘贴到手机浏览器打开。';
 });
 return {getState:()=>selection,showHelp:()=>{details.open=true;},status,details,address};
}
return {PHONE_URL,describeFile,attach};
});
