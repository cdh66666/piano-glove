/* Native startup must preserve the real compact editor DOM and its controls. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const host=path.resolve(__dirname,'..');
function loadPlaywright(){
 try{return require('playwright');}catch{}
 const home=process.env.USERPROFILE;
 if(home)try{return require(path.join(home,'.cache','codex-runtimes','codex-primary-runtime','dependencies','node','node_modules','playwright'));}catch{}
 return null;
}
const pw=loadPlaywright();
const edge=process.platform==='win32'?path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'):null;
const executable=pw&&(fs.existsSync(pw.chromium.executablePath())?pw.chromium.executablePath():(edge&&fs.existsSync(edge)?edge:null));

test('native catalog initialization keeps the issue editor intact and editable in a real DOM',async t=>{
 if(!pw||!executable){t.skip('No local headless browser available');return;}
 const browser=await pw.chromium.launch({headless:true,executablePath:executable,args:['--disable-background-networking']});
 t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width:1280,height:680}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 const html=fs.readFileSync(path.join(host,'software.html'),'utf8')
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
 await page.setContent(html,{waitUntil:'domcontentloaded'});
 await page.addStyleTag({content:fs.readFileSync(path.join(host,'software.css'),'utf8')});
 await page.addStyleTag({content:fs.readFileSync(path.join(host,'software-review.css'),'utf8')});
 await page.addStyleTag({content:fs.readFileSync(path.join(host,'desktop-ui.css'),'utf8')});
 await page.addStyleTag({content:fs.readFileSync(path.join(host,'desktop-catalog.css'),'utf8')});
 await page.evaluate(()=>{
  document.body.classList.add('review-view','native-app');document.querySelector('#convert').hidden=false;for(const e of document.querySelector('main').children)if(e.id!=='convert'&&e.tagName!=='FOOTER')e.style.display='none';
  const api={catalog_list:async()=>({builtins:[],imports:[]}),restore_workspace:async()=>({project:{}}),take_staged_files:async()=>[]};
  window.NativeApp={ready:Promise.resolve(api)};
  window.GloveWorkspace={show(){},openProject(){},async flush(){return true;},restore(){window.__nativeRestored=true;},queueSave(){},notice(){},importReview(){}};
 });
 await page.addScriptTag({path:path.join(host,'software-review.js')});
 await page.addScriptTag({path:path.join(host,'desktop-shell.js')});
 await page.addScriptTag({path:path.join(host,'native-catalog.js')});
 await page.waitForFunction(()=>window.__nativeRestored===true);
 const mounted=await page.evaluate(()=>({group:!!document.querySelector('#review-pitch-settings'),
  child:document.querySelector('#review-pitch')?.closest('#review-pitch-settings')?.id,
  summary:document.querySelector('#review-note-more summary')?.textContent}));
 assert.deepEqual(mounted,{group:true,child:'review-pitch-settings',summary:'排除此音'});
 const result=await page.evaluate(()=>{
  const note={id:'problem',page:1,system:1,measure:1,staff:'s',hand:'right',pitch:null,finger:2,beat:296.25,
   measure_start_beat:296.25,measure_beat:0,meter_beats:4,duration_beats:1,bbox:[100,100,110,110],
   timing_estimated:true,timing_source_id:'problem',timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。',
   automatic_reasons:['选择音高']};
  const other={...note,id:'other',bbox:[230,100,240,110],pitch:'D4',timing_warning:null,timing_estimated:true,timing_source_id:'problem',automatic_reasons:[]};
  const project={notes:[note,other],pages:[{page:1,width:600,height:800}],selection:{},automatic_mode:true,right_hand_timing:{version:1}};
  const host={project:()=>project,page:()=>0,previews:()=>[{page:1,data:'data:image/png;base64,AAAA'}],setPage(){},changed(){},notice(){}};
  document.querySelector('#review-workspace').hidden=false;document.querySelector('#native-drop-blank').hidden=true;
  const controller=GloveReview.create(host);window.__dockDOMFixture={controller,project,note};controller.render();controller.select('problem',false);
  const panel=document.querySelector('#review-inspector'),container=document.querySelector('#review-workspace'),flow=()=>panel.getBoundingClientRect().top+container.scrollTop;const beforeFlow=flow(),beforeBottom=panel.getBoundingClientRect().bottom;
  const before={major:[...document.body.querySelector('main').children].map(e=>({id:e.id||e.tagName,top:e.getBoundingClientRect().top,h:e.getBoundingClientRect().height,display:getComputedStyle(e).display})),convert:[...document.getElementById('convert').children].map(e=>({id:e.id||e.className,top:e.getBoundingClientRect().top,h:e.getBoundingClientRect().height,display:getComputedStyle(e).display})),header:[...document.body.children].slice(0,3).map(e=>({id:e.id||e.tagName,h:e.getBoundingClientRect().height})),layout:Object.fromEntries(['review-workspace','review-score-region','review-inspector'].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect(),c=getComputedStyle(e);return [id,{top:r.top,bottom:r.bottom,height:r.height,flex:c.flex,minHeight:c.minHeight,maxHeight:c.maxHeight,display:c.display}]})),sourceRect:(()=>{const r=panel.parentElement.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,children:[...panel.parentElement.children].map(e=>({id:e.id||e.className,h:e.getBoundingClientRect().height,hidden:e.hidden}))}})(),dockPosition:getComputedStyle(panel).position,dockParent:panel.parentElement.className,afterScore:panel.getBoundingClientRect().top>=document.querySelector('#review-score-region').getBoundingClientRect().bottom,
   dockBottom:panel.getBoundingClientRect().bottom,workspaceBottom:container.getBoundingClientRect().bottom,
   instructionInside:document.querySelector('#review-edit-instruction').getBoundingClientRect().bottom<=panel.getBoundingClientRect().bottom,
   timeInside:document.querySelector('#review-time-control').getBoundingClientRect().bottom<=panel.getBoundingClientRect().bottom,
   pitchInside:document.querySelector('#review-pitch').getBoundingClientRect().bottom<=panel.getBoundingClientRect().bottom,
   pitchYellow:document.querySelector('#review-pitch-settings').classList.contains('review-needs-action'),timeYellow:document.querySelector('#review-time-section').classList.contains('review-needs-action'),fingerYellow:document.querySelector('#review-finger-section').classList.contains('review-needs-action'),yellowColor:getComputedStyle(document.querySelector('#review-time-section')).backgroundColor,
   pitchGroup:!document.querySelector('#review-pitch-settings').hidden,
   pitchConnected:document.querySelector('#review-pitch').closest('#review-pitch-settings')?.id,
   warning:document.querySelector('#review-note-warning').textContent,
   timeOpen:!document.querySelector('#review-time-control').hidden,local:document.querySelector('#review-local-beat').value,
   advanced:document.querySelector('#review-editor-more').hidden};
  const input=document.querySelector('#review-pitch');input.value='C4';input.dispatchEvent(new Event('change',{bubbles:true}));
  controller.select('other',false);const afterFlow=flow(),afterBottom=panel.getBoundingClientRect().bottom;return {...before,changedPitch:note.pitch,manual:note.manual_fields||[],beforeFlow,afterFlow,beforeBottom,afterBottom,otherYellow:document.querySelectorAll('#review-inspector .review-edit-field.review-needs-action').length,inlineLeft:panel.style.left,inlineTop:panel.style.top};
 });
 assert.equal(result.dockPosition,'static');assert.match(result.dockParent,/review-source/);assert.equal(result.afterScore,true);assert.ok(result.dockBottom<=result.workspaceBottom+1,JSON.stringify(result));assert.equal(result.instructionInside,true,JSON.stringify(result));assert.equal(result.timeInside,true,JSON.stringify(result));assert.equal(result.pitchInside,true,JSON.stringify(result));assert.ok(result.pitchYellow&&result.timeYellow);assert.equal(result.fingerYellow,false);assert.equal(result.yellowColor,'rgb(255, 241, 174)');assert.ok(Math.abs(result.beforeBottom-result.afterBottom)<1);assert.equal(result.otherYellow,0);assert.equal(result.inlineLeft,'');assert.equal(result.inlineTop,'');
 assert.equal(result.pitchGroup,true);assert.equal(result.pitchConnected,'review-pitch-settings');
 assert.match(result.warning,/音高/);assert.match(result.warning,/估计/);assert.doesNotMatch(result.warning,/296\.25/);
 assert.equal(result.timeOpen,true);assert.equal(result.local,'1');assert.equal(result.advanced,true);
 assert.equal(result.changedPitch,'C4');assert.ok(result.manual.includes('pitch'));assert.deepEqual(errors,[]);
 for(const width of [1280,960]){
  await page.setViewportSize({width,height:680});
  const layout=await page.evaluate(()=>{
   const {controller,project,note}=__dockDOMFixture;note.pitch=null;note.finger=null;note.source_fingering_state='unresolved';note.duration_beats=null;note.automatic_reasons=['选择音高','选择指法','选择音值'];note.validation_pending=false;controller.select('other',false);controller.select('problem',false);
   const panel=document.getElementById('review-inspector'),workspace=document.getElementById('review-workspace'),score=document.getElementById('review-score-region'),r=panel.getBoundingClientRect();
   const controls=Object.fromEntries(['review-edit-instruction','review-finger-1','review-note-values','review-local-beat','review-local-confirm','review-pitch'].map(id=>{const e=document.getElementById(id),b=e.getBoundingClientRect();return [id,{top:b.top,bottom:b.bottom,left:b.left,right:b.right,visible:!!e.getClientRects().length}]}));
   return {panel:{top:r.top,bottom:r.bottom,left:r.left,right:r.right,client:panel.clientHeight,scroll:panel.scrollHeight,scrollTop:panel.scrollTop},workspaceBottom:workspace.getBoundingClientRect().bottom,scoreBottom:score.getBoundingClientRect().bottom,controls};
  });
  assert.ok(layout.panel.bottom<=layout.workspaceBottom+1,JSON.stringify(layout));assert.ok(layout.scoreBottom<=layout.panel.top+1,JSON.stringify(layout));assert.equal(layout.panel.scrollTop,0);
  for(const [id,r] of Object.entries(layout.controls))assert.ok(r.visible&&r.top>=layout.panel.top&&r.bottom<=layout.panel.bottom+1&&r.left>=layout.panel.left&&r.right<=layout.panel.right+1,width+' '+id+' '+JSON.stringify(layout));
 }

});
