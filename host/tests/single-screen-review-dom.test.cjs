/* Ordinary review must fit without page, source or dock scrolling. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const host=path.resolve(__dirname,'..');
let pw;try{pw=require('playwright');}catch{try{pw=require(path.join(process.env.USERPROFILE||'', '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));}catch{}}
const edge=path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe');
const executable=pw&&(fs.existsSync(pw.chromium.executablePath())?pw.chromium.executablePath():fs.existsSync(edge)?edge:null);
const evidenceBase=process.env.PIANO_REVIEW_DOM_EVIDENCE_DIR||path.resolve(host,'../../evidence/exclude-next-r20-20261028');

async function singleScreenChecks(t,noRenderFrames){
 const evidence=noRenderFrames?path.join(evidenceBase,'no-render-frames'):evidenceBase;
 if(!pw||!executable){t.skip('No local headless browser');return;}
 const browser=await pw.chromium.launch({headless:true,executablePath:executable,args:['--disable-background-networking']});t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width:1280,height:680}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const html=fs.readFileSync(path.join(host,'software.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
 await page.route('http://piano-review.test/',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:html}));
 await page.goto('http://piano-review.test/');
 for(const file of ['software.css','software-review.css','desktop-ui.css','desktop-catalog.css'])await page.addStyleTag({content:fs.readFileSync(path.join(host,file),'utf8')});
 await page.evaluate(()=>{
  document.body.classList.add('review-view','native-app');document.querySelector('#convert').hidden=false;for(const e of document.querySelector('main').children)if(e.id!=='convert'&&e.tagName!=='FOOTER')e.style.display='none';
  window.NativeApp={ready:Promise.resolve({catalog_list:async()=>({builtins:[],imports:[]}),restore_workspace:async()=>({project:{}}),take_staged_files:async()=>[]})};
  window.GloveWorkspace={show(){},openProject(){},async flush(){return true},restore(){window.__catalogReady=true},queueSave(){},notice(){},importReview(){}};
 });
 for(const file of ['software-review.js','desktop-shell.js','native-catalog.js'])await page.addScriptTag({path:path.join(host,file)});
 await page.waitForFunction(()=>window.__catalogReady);
 await page.evaluate(noRenderFrames=>{
  const fixture={project:null,changes:0},canvas=document.createElement('canvas');canvas.width=1200;canvas.height=450;const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,1200,450);ctx.strokeStyle='black';for(let i=0;i<5;i++){ctx.beginPath();ctx.moveTo(35,170+i*12);ctx.lineTo(1160,170+i*12);ctx.stroke();}fixture.preview=canvas.toDataURL('image/png');
  if(noRenderFrames){window.__renderFramesSuppressed=true;window.requestAnimationFrame=()=>0;window.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};}
  fixture.controller=GloveReview.create({project:()=>fixture.project,page:()=>fixture.page||0,previews:()=>fixture.previews||[{page:1,data:fixture.preview}],setPage(p){fixture.page=p},changed(){fixture.changes++},notice(){}});
  fixture.load=(kind,count=24)=>{const notes=Array.from({length:count},(_,i)=>{const group=Math.floor(i/4),x=70+group*1080/Math.max(1,Math.ceil(count/4)-1),y=173+(i%4)*12;return {id:'n'+i,page:1,system:1,measure:group+1,staff:'s',hand:'right',pitch:['G5','E5','C5','A4'][i%4],finger:i%5+1,beat:group,measure_start_beat:group,measure_beat:0,meter_beats:4,duration_beats:1,bbox:[x,y,x+11,y+8],finger_bbox:[x-2,132-(i%4)*6,x+12,141-(i%4)*6],automatic_reasons:[],automatic_ready:true};});
   if(kind==='overlap')notes[0].automatic_reasons=['同一手指重叠，请核对指法与音长'];
   if(kind==='finger'||kind==='dense')Object.assign(notes[0],{finger:null,automatic_reasons:['选择指法']});
   if(kind==='duration')Object.assign(notes[0],{duration_beats:null,automatic_reasons:['选择音值']});
   if(kind==='timing')Object.assign(notes[0],{timing_estimated:false,timing_warning:'起拍估计，请核对开始位置'});
   if(kind==='unknown-start')Object.assign(notes[0],{beat:null,measure_start_beat:null,measure_beat:null,timing_warning:'起拍待确定',automatic_reasons:['确定开始位置']});
   if(kind==='all')Object.assign(notes[0],{pitch:null,finger:null,duration_beats:null,timing_estimated:true,timing_warning:'起拍估计，请核对开始位置',automatic_reasons:['选择音高','选择指法','选择音值']});
   if(kind==='gray')for(const n of notes)Object.assign(n,{finger:null,source_fingering_state:'unmarked'});
   if(kind==='dense')Object.assign(notes.at(-1),{pitch:null,automatic_reasons:['选择音高']});
   ctx.fillStyle='white';ctx.fillRect(0,0,1200,450);ctx.strokeStyle='black';ctx.fillStyle='black';ctx.lineWidth=1;for(let i=0;i<5;i++){ctx.beginPath();ctx.moveTo(35,170+i*12);ctx.lineTo(1160,170+i*12);ctx.stroke();}ctx.font='17px sans-serif';for(const n of notes){const b=n.bbox;ctx.beginPath();ctx.ellipse(b[0]+5.5,b[1]+4,6,4,-.25,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.moveTo(b[0]+11,b[1]+4);ctx.lineTo(b[0]+11,b[1]-25);ctx.stroke();ctx.fillText(String(n.finger||'?'),n.finger_bbox[0],n.finger_bbox[3]);}fixture.preview=canvas.toDataURL('image/png');
   fixture.page=0;fixture.previews=null;fixture.project={name:'通用单屏测试',notes,staves:[{id:'s',page:1,system:1,hand:'right',bbox:[35,170,1160,218]}],pages:[{page:1,width:1200,height:450}],selection:{},automatic_mode:true,automatic:{attention_notes:kind==='gray'?0:1},right_hand_timing:{version:2}};
   document.getElementById('review-workspace').hidden=false;document.getElementById('native-drop-blank').hidden=true;document.getElementById('review-export').hidden=false;document.getElementById('range-reviewed').closest('label').hidden=true;fixture.controller.render();
   // 没有要查的音时编辑框不自动打开（11-03 用户要求）；这里模拟用户点第一个音再量版面。
   if(kind==='gray')fixture.controller.select(notes[0].id,false);
  };
  window.__singleScreen=fixture;
 },noRenderFrames);
 const click=selector=>noRenderFrames?page.evaluate(s=>{const e=document.querySelector(s);e.focus();e.click()},selector):page.click(selector);
 const getLayout=()=>page.evaluate(()=>{
  const el=id=>document.getElementById(id),rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
  const ids=['review-score-region','review-inspector','review-row-panel','review-row-canvas','review-row-annotations','review-edit-instruction','review-finger-1','review-note-values','review-local-beat','review-local-confirm','review-exclude-note','review-next-problem','review-export-preset','export'];
  const out={width:innerWidth,height:innerHeight,document:{client:document.documentElement.clientHeight,scroll:document.documentElement.scrollHeight},fields:{},labels:[],selected:__singleScreen.controller.current()?.id,staffGap:Number(el('review-row-canvas').dataset.staffGap),fragmentCount:Number(el('review-row-canvas').dataset.fragments),instruction:el('review-edit-instruction').textContent};
  for(const id of ids){const e=el(id);out.fields[id]={...rect(e),visible:!!e.getClientRects().length,client:e.clientHeight,scroll:e.scrollHeight,font:Number.parseFloat(getComputedStyle(e).fontSize)};}
  out.labels=[...document.querySelectorAll('#review-row-annotations .review-row-label')].filter(e=>!e.hidden).map(e=>{const hit=[...el('review-row-hits').querySelectorAll('[data-note-id]')].find(h=>h.dataset.noteId===e.dataset.noteId),link=[...el('review-row-annotations').querySelectorAll('.review-row-link')].find(h=>h.dataset.noteId===e.dataset.noteId),h=hit?.getBoundingClientRect();return {id:e.dataset.noteId,...rect(e),font:parseFloat(getComputedStyle(e.querySelector('small')).fontSize),sourceCenter:h?(h.left+h.right)/2:null,linkVisible:!!link?.getClientRects().length,compact:e.dataset.compact==='true'};});return out;
 });
 const settled=()=>page.evaluate(()=>window.__renderFramesSuppressed?Promise.resolve().then(()=>Promise.resolve()):new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const layouts=[];fs.mkdirSync(evidence,{recursive:true});
 for(const viewport of [{width:960,height:680},{width:1280,height:680},{width:1280,height:800}]){
  await page.setViewportSize(viewport);
  for(const kind of ['overlap','finger','duration','timing','unknown-start','all','gray','dense']){
   await page.evaluate(([k,c])=>__singleScreen.load(k,c),[kind,kind==='dense'?92:24]);
   await settled();
   const s=await getLayout(),why=kind+' '+JSON.stringify(s);layouts.push({kind,...s});
   assert.ok(s.document.scroll<=s.document.client+1,why);assert.ok(s.staffGap>=(viewport.height>=800?5.49:4.4),why); /* 11-05 用户：指法框一列最多 5 个全部露出、不滚动；很矮的窗口谱子会稍小 */
   /* 11-05 用户：谱子区域里指法框多了可以上下滑，只要求下面的校对框不滚 */assert.ok(s.fields['review-inspector'].scroll<=s.fields['review-inspector'].client+1,why);
   for(const [id,r]of Object.entries(s.fields))assert.ok(r.visible&&r.left>=-1&&r.top>=-1&&r.right<=viewport.width+1&&r.bottom<=viewport.height+1,id+' '+why);
   for(const r of s.labels)assert.ok(r.width>=23.95&&r.height>=24&&r.font>=11&&r.left>=s.fields['review-row-annotations'].left-1&&r.right<=s.fields['review-row-annotations'].right+1&&r.top>=s.fields['review-row-annotations'].top-1&&r.bottom<=s.fields['review-row-annotations'].bottom+1,why);
   for(const r of s.labels){assert.equal(r.compact,false,'No unrelated equal-spacing strip: '+why);assert.equal(r.linkVisible,true,'Keep each source-note guide: '+why);assert.ok(Math.abs((r.left+r.right)/2-r.sourceCenter)<=r.width/2,'Finger stays directly below its original note: '+JSON.stringify(r)); /* 11-05 用户：一个和弦一列，框对准这组音的中间，盖住每个音的中心线 */}
   if(kind==='dense'){const chord=s.labels.filter(n=>['n0','n1','n2','n3'].includes(n.id)).sort((a,b)=>Number(a.id.slice(1))-Number(b.id.slice(1)));for(let i=1;i<chord.length;i++)assert.ok(chord[i].top>chord[i-1].top,'Chord order follows the printed upper/lower notes');}
   assert.ok(s.labels.some(n=>n.id===s.selected),why);assert.equal(s.fields['review-finger-1'].height>=32,true,why);assert.equal(s.fields['review-finger-1'].font>=14,true,why);
   if(kind==='overlap')assert.match(s.instruction,/数字|指法/);
   if((kind==='overlap'&&viewport.width===960)||(kind==='all'&&viewport.width===1280&&viewport.height===680)||(kind==='dense'&&viewport.width===1280&&viewport.height===800))await page.screenshot({path:path.join(evidence,`dom-${kind}-${viewport.width}x${viewport.height}.png`)});
   if(kind==='dense'){
    const ids=new Set(s.labels.map(n=>n.id));for(let i=1;i<s.fragmentCount;i++){await click('#review-fragment-next');const next=await getLayout();assert.ok(next.labels.some(n=>n.id===next.selected));for(const n of next.labels){assert.equal(ids.has(n.id),false);ids.add(n.id);}}
    assert.equal(ids.size,92);
    if(s.fragmentCount>1)await click('#review-fragment-prev');await page.evaluate(()=>__singleScreen.controller.focusIssue('n0'));await click('#review-next-problem');const issue=await getLayout();assert.equal(issue.selected,'n91');assert.ok(issue.labels.some(n=>n.id==='n91'));
   }
  }
 }
 const transitions=[];
 for(const viewport of [{width:1280,height:680},{width:960,height:680},{width:1280,height:800}]){
  await page.setViewportSize(viewport);await page.evaluate(()=>__singleScreen.load('timing'));await settled();
  for(const kind of ['finger','all','unknown-start','gray','dense']){
   await page.evaluate(k=>__singleScreen.load(k,k==='dense'?92:24),kind);await settled();const s=await getLayout();
   for(const id of ['review-inspector'])assert.ok(s.fields[id].scroll<=s.fields[id].client+1,kind+' after timing '+JSON.stringify(s));
   transitions.push({kind,viewport,score:s.fields['review-score-region'],dock:s.fields['review-inspector']});
  }
  // A completed validation can lengthen guidance without calling renderRow.
  await page.evaluate(()=>{__singleScreen.load('finger');});await settled();
  const before=await getLayout();
  const draft=await page.evaluate(()=>{const f=__singleScreen,input=document.getElementById('review-local-beat'),n=f.controller.current();input.focus();input.value='1.125';n.timing_warning='本小节超过4拍，请核对音长和休止，'+('也请核对前后音之间的开始位置和音长，').repeat(10);f.controller.refreshValidation();return {changes:f.changes,beat:n.beat,id:n.id};});
  await settled();const after=await getLayout();assert.ok(after.fields['review-inspector'].height>before.fields['review-inspector'].height);
  for(const id of ['review-inspector'])assert.ok(after.fields[id].scroll<=after.fields[id].client+1,JSON.stringify(after));
  assert.ok(after.labels.some(r=>r.top>=after.fields['review-score-region'].top-1&&r.bottom<=after.fields['review-score-region'].bottom+1),JSON.stringify(after)); /* 11-05 用户：指法框多了在谱子下面上下滑，不要求一屏全看见 */
  const preserved=await page.evaluate(()=>({active:document.activeElement.id,value:document.getElementById('review-local-beat').value,changes:__singleScreen.changes,beat:__singleScreen.controller.current().beat,id:__singleScreen.controller.current().id}));
  assert.deepEqual(preserved,{active:'review-local-beat',value:'1.125',...draft});
  await page.evaluate(()=>document.activeElement.blur());
 }
 // Replanning a dense row must keep the selected last note in its new fragment.
 await page.evaluate(()=>{__singleScreen.load('dense',92);__singleScreen.controller.focusIssue('n91');});await settled();
 for(const viewport of [{width:960,height:680},{width:1280,height:800},{width:1280,height:680}]){
  await page.setViewportSize(viewport);if(noRenderFrames)await page.evaluate(()=>window.dispatchEvent(new Event('resize')));await settled();const s=await getLayout();assert.equal(s.selected,'n91');assert.ok(s.labels.some(n=>n.id==='n91'));for(const id of ['review-inspector'])assert.ok(s.fields[id].scroll<=s.fields[id].client+1,JSON.stringify(s));
 }
 // Complete and exclude successive synthetic notes exclusively in the lower dock.
 await page.setViewportSize({width:960,height:680});
 await page.evaluate(()=>{const f=__singleScreen;f.load('dense',92);const p=f.project,a=p.notes[4],w=p.notes[8];Object.assign(a,{duration_beats:null,automatic_reasons:['选择音值']});Object.assign(w,{timing_warning:'起拍估计，请核对开始位置',timing_estimated:false});p.pages.push({page:2,width:1200,height:450});p.staves.push({id:'s2',page:2,system:1,hand:'right',bbox:[35,170,1160,218]});p.notes.push({...p.notes[0],id:'later-page',page:2,staff:'s2',pitch:'C5',finger:null,duration_beats:1,beat:60,measure_start_beat:60,measure_beat:0,bbox:[150,175,161,183],finger_bbox:[145,132,160,141],automatic_reasons:['选择指法']});f.previews=[{page:1,data:f.preview},{page:2,data:f.preview}];f.controller.render();});await settled();
 assert.equal(await page.locator('#review-auto-next').isChecked(),true);
 await click('#review-finger-2');await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n4'); // 11-04：改指法不等整首检查，直接跳下一处
 await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.project.validation_pending=true;f.controller.refreshValidation();});assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n4');
 await page.evaluate(()=>{const f=__singleScreen;f.project.validation_pending=false;f.project.validation_error='校验错误';f.controller.refreshValidation();});assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n4');
 await page.evaluate(()=>{const f=__singleScreen;f.project.validation_error='';f.controller.refreshValidation();});await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n4');
 const beforeModifier=await page.evaluate(()=>({changes:__singleScreen.changes,duration:__singleScreen.controller.current().duration_beats}));await click('#review-value-dotted');
 assert.deepEqual(await page.evaluate(()=>({changes:__singleScreen.changes,duration:__singleScreen.controller.current().duration_beats})),beforeModifier);assert.match(await page.locator('#review-value-caption').textContent(),/已选附点.*音长保存/);
 const pendingLayout=await getLayout();for(const id of ['review-inspector'])assert.ok(pendingLayout.fields[id].scroll<=pendingLayout.fields[id].client+1,JSON.stringify(pendingLayout));
 await click('#review-note-values .review-note-value:nth-child(3)');assert.equal(await page.evaluate(()=>__singleScreen.controller.current().duration_beats),1.5);await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n8','timing source precedes a later missing pitch');
 await click('#review-local-confirm');await page.evaluate(()=>{const f=__singleScreen,n=f.controller.current();n.validation_pending=false;n.timing_warning=null;f.controller.refreshValidation();});await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n91');
 await click('#review-exclude-note');assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n91');assert.equal(await page.locator('#review-exclude-note').textContent(),'恢复这个音');assert.equal(await page.locator('#review-exclude-note').isDisabled(),true);await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'later-page');assert.equal(await page.evaluate(()=>__singleScreen.page),1);
 await click('#review-exclude-note');await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'later-page');assert.equal(await page.locator('#review-inspector-content').isVisible(),false);await page.evaluate(()=>__singleScreen.controller.select('later-page',false));assert.equal(await page.locator('#review-inspector-content').isVisible(),true);assert.equal(await page.locator('#review-exclude-note').isDisabled(),false);assert.equal(await page.locator('#review-exclude-note').textContent(),'恢复这个音');
 await click('#review-exclude-note');await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});assert.equal(await page.locator('#review-exclude-note').textContent(),'不要这个音');await click('#review-finger-3');await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});assert.equal(await page.locator('#review-next-problem').textContent(),'已检查完');
 // Invalid local input must survive a normal blur-before-click button action.
 await page.evaluate(()=>__singleScreen.load('finger'));await page.fill('#review-local-beat','5');const invalidBefore=await page.evaluate(()=>__singleScreen.changes);await click('#review-exclude-note');assert.equal(await page.evaluate(()=>__singleScreen.controller.current().excluded===true),false);assert.equal(await page.locator('#review-local-beat').inputValue(),'5');assert.equal(await page.evaluate(()=>__singleScreen.changes),invalidBefore);
 await page.fill('#review-local-beat','1');await click('#review-local-confirm');await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});
 // Explicit saved off remains off on a new score; completing a field does not jump.
 await click('#review-auto-next');await page.evaluate(()=>__singleScreen.load('dense',92));assert.equal(await page.locator('#review-auto-next').isChecked(),false);await click('#review-finger-4');await page.evaluate(()=>{const f=__singleScreen;f.controller.current().validation_pending=false;f.controller.refreshValidation();});assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n0');await click('#review-auto-next');await settled();assert.equal(await page.evaluate(()=>__singleScreen.controller.current().id),'n91');
 await page.evaluate(()=>__singleScreen.load('finger'));
 await click('#review-tools-toggle');assert.equal(await page.locator('#review-workspace').isVisible(),false);assert.equal(await page.locator('#native-score-catalog').isVisible(),true);assert.equal(await page.locator('#save-review').isVisible(),true);assert.equal(await page.locator('#native-score-catalog').evaluate(e=>e.parentElement.id),'review-tools-panel');assert.equal(await page.locator('#review-tools-panel').evaluate(e=>getComputedStyle(e).position),'static');
 await click('#review-tools-back');assert.equal(await page.locator('#review-workspace').isVisible(),true);
 await click('#review-more-toggle');assert.equal(await page.locator('#review-score-region').isVisible(),false);assert.equal(await page.locator('#review-advanced-back').isVisible(),true);assert.equal(await page.locator('#review-beat').isVisible(),true);assert.equal(await page.locator('#review-editor-more').evaluate(e=>getComputedStyle(e).position),'static');
 await click('#review-advanced-back');assert.equal(await page.locator('#review-score-region').isVisible(),true);assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(evidence,'dom-layout-results.json'),JSON.stringify({ok:true,noRenderFrames,cases:layouts.length,layouts,transitions,validationGrowthCases:3,lastSelectedResizeCases:3,bottomOnlyWorkflow:true,exclusionAcrossFragmentAndPage:true,restoreLastExcludedNote:true,invalidLocalDraftPreserved:true,durationComboSingleCommit:true,explicitOffPreserved:true},null,2));
}
test('ordinary single-screen review exposes the current note, actions and every visible fragment label without scrolling',t=>singleScreenChecks(t,false));
test('known editor changes reflow without animation-frame or resize-observer callbacks and preserve the draft input',t=>singleScreenChecks(t,true));
