const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const Review=require('../software-review.js');
const note=(extra={})=>({id:'one',page:1,system:1,measure:1,hand:'right',pitch:'C4',finger:1,beat:0,duration_beats:1,confirmed:false,bbox:[100,100,110,110],finger_bbox:[103,80,107,88],...extra});
test('plain finger and second labels keep musical data intact and handle unknown values honestly',()=>{const n=note({pitch:'F#5',finger:4,duration_beats:.25}),before=JSON.stringify(n);assert.equal(Review.fingerLabel(n),'4 无名指');assert.equal(Review.holdLabel(n,120),'按 0.125 秒');assert.equal(Review.holdLabel(n,60),'按 0.25 秒');assert.equal(Review.holdLabel(n,0),'时长待补');assert.equal(Review.holdLabel(note({duration_beats:null}),120),'时长待补');assert.equal(Review.fingerLabel(note({finger:null})),'? 待补指法');assert.equal(JSON.stringify(n),before);});
test('all four fields must be genuine valid values before a note can be confirmed',()=>{assert.deepEqual(Review.missingFields(note()),[]);for(const pitch of ['C4','F#4','Bb4','F##4','Gbb4'])assert.equal(Review.validPitch(pitch),true);for(const pitch of ['C','1','H4','C99','<script>'])assert.equal(Review.validPitch(pitch),false);assert.deepEqual(Review.missingFields(note({pitch:null,finger:null,beat:null,duration_beats:null,hand:null})),['音高','指法','开始','时长','左右手']);assert.ok(Review.missingFields(note({finger:1.5,beat:-1,duration_beats:0})).length===3);});
test('source crop includes printed fingering and clamps to real page geometry',()=>{const page={width:600,height:800};assert.deepEqual(Review.boxFor(note(),page),{x:100,y:100,width:10,height:10});const crop=Review.cropFor(note(),page);assert.ok(crop.x<=100&&crop.y<=80&&crop.x+crop.width>=110&&crop.y+crop.height>=110);const edge=Review.cropFor(note({bbox:[590,795,610,810]}),page);assert.ok(edge.x>=0&&edge.y>=0&&edge.x+edge.width<=600&&edge.y+edge.height<=800);for(const bbox of [null,[1,2,NaN,4],[2,3,1,4]])assert.equal(Review.boxFor(note({bbox}),page),null);assert.equal(Review.cropFor(note(),{width:0,height:800}),null);});
test('timeline preserves rests, chord simultaneity and rhythm rather than evenly spacing notes',()=>{const notes=[note(),note({id:'chord',pitch:'E4',finger:3}),note({id:'late',beat:3,duration_beats:.5}),note({id:'unknown',beat:null}),note({id:'excluded',beat:2,excluded:true}),note({id:'left',beat:1,hand:'left'})];const timeline=Review.timelineFor(notes,notes[0]);assert.equal(timeline.start,0);assert.equal(timeline.end,4);assert.deepEqual(timeline.notes.map(n=>[n.id,n.beat,n.duration_beats]),[['one',0,1],['chord',0,1],['late',3,.5],['excluded',2,1]]);assert.equal(Review.timelineFor(notes,notes[3]),null);});
test('every named reference pitch is on its correct treble staff line or space',()=>{let checked=0;for(const lesson of Review.notationReferences){const heads=[...lesson.art.matchAll(/<ellipse data-pitch="([^"]+)" cx="([\d.]+)" cy="([\d.]+)"/g)];if(!heads.length)continue;assert.match(lesson.art,/data-clef="treble"/);const top=Number(lesson.art.match(/data-staff-top="([\d.]+)"/)[1]),gap=Number(lesson.art.match(/data-staff-gap="([\d.]+)"/)[1]);for(const [,pitch,,y] of heads){const [,letter,,octave]=/^([A-G])(#|b|)(\d+)$/.exec(pitch);const diatonic=Number(octave)*7+'CDEFGAB'.indexOf(letter),topF5=5*7+3;assert.equal(Number(y),top+(topF5-diatonic)*gap/2,lesson.title+' '+pitch);assert.ok(lesson.art.includes('>'+pitch+'<')||lesson.art.includes('>'+pitch+'　'),pitch+' has a matching visible label');checked++;}}assert.equal(checked,14);});
test('accidentals align with their own noteheads, including F4 space and B4 line',()=>{const art=Review.notationReferences[3].art,accidentals=[...art.matchAll(/data-accidental="([^"]+)" data-center-y="([\d.]+)"/g)].map(m=>[m[1],Number(m[2])]),heads=[...art.matchAll(/data-pitch="([^"]+)" cx="[\d.]+" cy="([\d.]+)"/g)].map(m=>[m[1],Number(m[2])]);assert.deepEqual(accidentals,[['sharp',106],['flat',88],['natural',106]]);assert.deepEqual(heads,[['F#4',106],['Bb4',88],['F4',106]]);});
test('whole rest hangs below its reference line, half rest sits above and whole-bar time follows meter',()=>{const lesson=Review.notationReferences[6],groups=[...lesson.art.matchAll(/<g data-rest="([^"]+)">([\s\S]*?)<\/g>/g)];assert.equal(groups.length,2);for(const [,kind,body] of groups){const reference=Number(body.match(/data-reference-line="(\d+)"/)[1]),[,y,height]=body.match(/<rect x="\d+" y="(\d+)" width="\d+" height="(\d+)"/);assert.equal(kind==='whole'?Number(y):Number(y)+Number(height),reference);}assert.match(lesson.body,/全休止表示整小节时按拍号/);assert.match(lesson.body,/2\/4 中是 2 拍/);assert.doesNotMatch(lesson.art,/>休 4 拍</);});
test('closing repeat belongs to ending one and ending two begins after it',()=>{const art=Review.notationReferences[9].art,closing=Number(art.match(/data-repeat="end" d="M(\d+)/)[1]),firstEnd=Number(art.match(/data-ending="1" d="M\d+ \d+V\d+H(\d+)/)[1]),secondStart=Number(art.match(/data-ending="2" d="M(\d+)/)[1]);assert.equal(closing,firstEnd);assert.ok(secondStart>closing);});
test('tie examples use identical staff positions and slur examples use different positions',()=>{const art=Review.notationReferences[8].art,heads=[...art.matchAll(/<ellipse cx="\d+" cy="(\d+)"/g)].map(m=>Number(m[1]));assert.equal(heads.length,4);assert.equal(heads[0],heads[1]);assert.notEqual(heads[2],heads[3]);assert.match(Review.notationReferences[2].tip,/上方 8va 高八度，下方 8vb 低八度/);});
class Node{
 constructor(id=''){this.id=id;this.value='';this.hidden=false;this.children=[];this.style={setProperty(k,v){this[k]=v;}};this.dataset={};this.className='';this.classes=new Set();this.classList={toggle:(name,value)=>value?this.classes.add(name):this.classes.delete(name),add:name=>this.classes.add(name),remove:name=>this.classes.delete(name),contains:name=>this.classes.has(name)};this.attrs={};}
 set innerHTML(value){this.html=value;}get innerHTML(){return this.html;}
 appendChild(n){this.children.push(n);return n;}append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
 setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k];}querySelector(){return null;}addEventListener(name,fn){this['on'+name]=fn;}focus(){this.focused=true;}
}
function harness(project,previews=[{page:1,data:'data:image/png;base64,AAAA'}]){
 const nodes={};for(const [,id]of fs.readFileSync(path.join(__dirname,'../software.html'),'utf8').matchAll(/id="([^"]+)"/g))nodes[id]=new Node(id);
 nodes['original-zoom'].value='100';nodes.bpm.value='120';
 let page=0,changes=0,notice='',now=0,nextTimer=1,deferAudioResume=false,skipExports=0;const timers=new Map(),oscillators=[],externalCalls=[],pendingResumes=[];
 const schedule=(fn,delay,interval=false)=>{const id=nextTimer++;timers.set(id,{fn,at:now+Math.max(0,Number(delay)||0),interval:interval?Math.max(1,Number(delay)||1):0});return id;};
 function advance(ms){const end=now+ms;let turns=0;while(true){const entry=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];if(!entry)break;assert.ok(turns++<10000,'tutorial timer loop must be bounded');const [id,t]=entry;now=t.at;if(t.interval)t.at+=t.interval;else timers.delete(id);t.fn();}now=end;}
 const forbid=kind=>(...args)=>{externalCalls.push([kind,...args]);throw new Error('tutorial must not access '+kind);};
 const parameter=()=>({value:0,setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){},setTargetAtTime(){},cancelScheduledValues(){}});
 class AudioContext{
  constructor(){this.state='suspended';this.destination={};}get currentTime(){return now/1000;}resume(){if(deferAudioResume)return new Promise(resolve=>pendingResumes.push(()=>{this.state='running';resolve();}));this.state='running';return Promise.resolve();}suspend(){this.state='suspended';return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}
  createGain(){return {gain:parameter(),connect(){},disconnect(){}};}
  createOscillator(){const oscillator={frequency:parameter(),started:false,stopped:false,connect(){},disconnect(){},start(){this.started=true;},stop(){this.stopped=true;}};oscillators.push(oscillator);return oscillator;}
 }
 const documentListeners=new Map(),storage=new Map();
 const context={document:{getElementById:id=>nodes[id],createElement:()=>new Node(),hidden:false,addEventListener:(name,fn)=>documentListeners.set(name,fn)},addEventListener(){},localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v))},console,setTimeout:(fn,delay)=>schedule(fn,delay),clearTimeout:id=>timers.delete(id),setInterval:(fn,delay)=>schedule(fn,delay,true),clearInterval:id=>timers.delete(id),performance:{now:()=>now},AudioContext,fetch:forbid('fetch'),WebSocket:class{constructor(...args){forbid('WebSocket')(...args);}},navigator:{serial:{requestPort:forbid('serial'),getPorts:forbid('serial')}}};
 context.window=context;context.globalThis=context;
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../software-review.js'),'utf8'),context);
 const controller=context.GloveReview.create({project:()=>project,page:()=>page,previews:()=>previews,setPage:n=>page=n,changed:()=>{changes++;project.selection={...project.selection,range_reviewed:false,ties_reviewed:false,repeats_reviewed:false};},notice:t=>notice=t,exportSkippingPending:()=>{skipExports++;}});controller.render();
 return {nodes,controller,document:context.document,get page(){return page;},get changes(){return changes;},get notice(){return notice;},get skipExports(){return skipExports;},project,timers,oscillators,externalCalls,advance,focusOutDocument:()=>documentListeners.get('focusout')?.(),hideDocument:()=>{context.document.hidden=true;documentListeners.get('visibilitychange')?.();},deferAudio:()=>{deferAudioResume=true;},resolveAudio:()=>{deferAudioResume=false;for(const resume of pendingResumes.splice(0))resume();},changeProject:p=>project=p,changePreviews:p=>previews=p};
}
const project=notes=>({source_sha256:'verified-source',notes,pages:[{page:1,width:600,height:800},{page:2,width:600,height:800}],selection:{range_reviewed:true}});

test('estimated timing warns at its source while dependent notes stay ready and unmarked',()=>{
 const source=note({id:'source',beat:.25,measure_beat:.25,measure_start_beat:0,meter_beats:4,timing_warning:'起首位置按右手节奏估计',timing_estimated:true,timing_source_id:'source'}),following=note({id:'following',beat:1.25,measure_beat:1.25,measure_start_beat:0,meter_beats:4,bbox:[150,100,160,110],timing_estimated:true,timing_source_id:'source'});
 const h=harness({...project([source,following]),automatic_mode:true,right_hand_timing:{version:1}});
 const labels=()=>h.nodes['review-row-annotations'].children.filter(x=>x.className.startsWith('review-row-label'));
 assert.equal(Review.noteConcern(source,true),false);assert.equal(Review.hasTimingWarning(source),true);assert.equal(Review.hasTimingWarning(following),false);
 assert.equal(labels().find(x=>x.dataset.noteId==='source').classes.has('timing-warning'),true);assert.equal(labels().find(x=>x.dataset.noteId==='following').classes.has('attention'),false);
 assert.equal(h.nodes['review-count'].textContent,'可处理 2 · 需检查 0');assert.match(h.nodes['review-pending-count'].textContent,/时间提醒 1 处/);
 h.controller.select('source',false);assert.match(h.nodes['review-note-warning'].textContent,/估计/);assert.match(h.nodes['review-time-toggle'].textContent,/本小节第 1.25 拍/);assert.equal(h.nodes['review-time-control'].hidden,false);assert.match(h.nodes['review-local-help'].textContent,/后续未固定的音会跟随/);assert.match(h.nodes['review-local-help'].textContent,/仅设置一次/);
 h.nodes['review-filter'].value='pending';h.nodes['review-filter'].onchange();assert.deepEqual(labels().filter(x=>!x.hidden).map(x=>x.dataset.noteId),[]); // 11-04：猜的位置不进待查
});

test('timing estimates do not hide a genuine missing duration or finger conflict',()=>{
 const source=note({timing_warning:'起拍估计',timing_estimated:true,duration_beats:null,automatic_reasons:['同指重叠']});
 const h=harness({...project([source]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select(source.id,false);
 assert.match(h.nodes['review-count'].textContent,/需检查 1/);assert.match(h.nodes['review-note-warning'].textContent,/时长/);assert.match(h.nodes['review-note-warning'].textContent,/起拍估计/);assert.match(h.nodes['review-note-warning'].textContent,/同指重叠/);
 source.duration_beats=1;h.controller.refreshValidation();assert.match(h.nodes['review-note-warning'].textContent,/同指重叠/);
});

test('clicking an issue shows its cause and relevant controls immediately without duplicating the warning',()=>{
 const source=note({id:'problem',pitch:null,duration_beats:null,measure_start_beat:296.25,measure_beat:0,beat:296.25,meter_beats:4,
   timing_source_id:'problem',timing_estimated:true,timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。',
   automatic_reasons:['选择音高','同一手指的两个音重叠，请检查指法或时值']});
 const h=harness({...project([source]),automatic_mode:true,right_hand_timing:{version:1}});
 const hit=h.nodes['review-row-hits'].children[0],label=h.nodes['review-row-annotations'].children.find(e=>e.className.includes('review-row-label'));
 assert.ok(hit.classes.has('attention'));assert.ok(label.classes.has('attention'));hit.onclick();
 const warning=h.nodes['review-note-warning'].textContent;assert.match(warning,/音高/);assert.match(warning,/时长/);assert.match(warning,/同一手指/);assert.match(warning,/开始位置是估计/);assert.doesNotMatch(warning,/296\.25/);
 assert.equal(h.nodes['review-note-detail-warning'],undefined);assert.equal(h.nodes['review-pitch-settings'].hidden,false);assert.equal(h.nodes['review-duration-picker'].hidden,false);assert.equal(h.nodes['review-time-control'].hidden,false);assert.equal(h.nodes['review-local-beat'].value,'1');
});

test('same estimated position is confirmed only by an explicit action, without clearing separate rhythm issues',()=>{
 const source=note({id:'source',beat:296.25,measure_start_beat:296.25,measure_beat:0,meter_beats:4,duration_beats:null,
  timing_estimated:true,timing_source_id:'source',timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。；小音符用途请核对；音值已按同梁几何恢复',issues:['small_notated_note_requires_review']});
 const h=harness({...project([source]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select(source.id,false);
 const local=h.nodes['review-local-beat'];local.tagName='INPUT';local.blur=()=>{h.document.activeElement=null;};h.nodes['review-inspector'].contains=n=>n===local;h.document.activeElement=local;
 assert.equal(h.controller.commitPendingEdits(),true);assert.equal(h.changes,0);assert.equal(source.manual_fields,undefined);assert.equal(source.beat,296.25);
 h.nodes['review-local-confirm'].onclick();assert.equal(h.changes,1);assert.deepEqual(Array.from(source.manual_fields),['beat']);assert.equal(source.timing_anchor_scope,'measure');assert.equal(source.measure_beat,0);assert.equal(source.beat,296.25);assert.equal(source.duration_beats,null);assert.ok(source.issues.includes('small_notated_note_requires_review'));assert.match(source.timing_warning,/小音符用途/);
 const second=note({id:'second',beat:296.25,measure_start_beat:296.25,measure_beat:0,meter_beats:4,timing_estimated:true,timing_source_id:'second',timing_warning:'起拍估计'});
 const h2=harness({...project([second]),automatic_mode:true,right_hand_timing:{version:1}});h2.controller.select(second.id,false);h2.nodes['review-onset-start'].onclick();assert.deepEqual(Array.from(second.manual_fields),['beat']);assert.equal(second.timing_anchor_scope,'measure');assert.equal(second.measure_beat,0);assert.equal(second.beat,296.25);
});

test('missing onset opens its controls and never treats an empty value as a confirmed start',()=>{
 const unknown=note({id:'missing-start',beat:null,measure_start_beat:null,measure_beat:null,automatic_reasons:['确定开始位置']});
 const h=harness({...project([unknown]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select(unknown.id,false);
 assert.equal(h.nodes['review-time-control'].hidden,false);assert.equal(h.nodes['review-local-beat'].disabled,true);assert.equal(h.nodes['review-local-confirm'].disabled,true);assert.match(h.nodes['review-local-help'].textContent,/小节位置未知/);
 assert.equal(h.nodes['review-local-beat'].value,'');assert.equal(h.nodes['review-local-confirm'].onclick(),false);assert.equal(unknown.beat,null);assert.equal(unknown.manual_fields,undefined);assert.equal(h.changes,0);
 const valid=note({id:'reason-only',beat:0,measure_start_beat:0,measure_beat:0,automatic_reasons:['确定开始位置']});
 const h2=harness({...project([valid]),automatic_mode:true,right_hand_timing:{version:1}});h2.controller.select(valid.id,false);assert.equal(h2.nodes['review-time-control'].hidden,false);assert.match(h2.nodes['review-time-toggle'].textContent,/待确认/);
});

test('measure overflow opens the control for its actual cause; a small-note warning does not imply an onset problem',()=>{
 for(const [warning,expectTime,expectDuration] of [
  ['本小节超过4拍，请核对音长和末尾休止。',false,true],
  ['本小节超过4拍，请核对开始位置和末尾休止。',true,false],
  ['小音符用途请核对；音值已按同梁几何恢复',false,false]]){
  const n=note({id:'source',beat:1,measure_start_beat:0,measure_beat:1,meter_beats:4,timing_estimated:false,timing_source_id:'source',timing_warning:warning});
  const h=harness({...project([n]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select('source',false);
  assert.equal(h.nodes['review-time-control'].hidden,false,warning);assert.equal(h.nodes['review-duration-picker'].hidden,false,warning);assert.equal(h.nodes['review-time-section'].classes.has('review-needs-action'),expectTime,warning);assert.equal(h.nodes['review-duration-section'].classes.has('review-needs-action'),expectDuration,warning);assert.match(h.nodes['review-note-warning'].textContent,/核对/);
 }
});

test('reading a fractional local beat does not round or mutate it on blur or explicit same-value confirmation',()=>{
 const source=note({id:'fraction',beat:296.333333,measure_start_beat:296,measure_beat:.333333,meter_beats:4,timing_estimated:true,timing_source_id:'fraction',timing_warning:'起拍估计'});
 const h=harness({...project([source]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select(source.id,false);
 const local=h.nodes['review-local-beat'];assert.equal(local.value,'1.333333');local.tagName='INPUT';local.blur=()=>{h.document.activeElement=null;};h.nodes['review-inspector'].contains=n=>n===local;h.document.activeElement=local;
 assert.equal(h.controller.commitPendingEdits(),true);assert.equal(h.changes,0);assert.equal(source.beat,296.333333);assert.equal(source.manual_fields,undefined);
 h.nodes['review-local-confirm'].onclick();assert.equal(source.beat,296.333333);assert.equal(source.measure_beat,.333333);assert.equal(source.timing_anchor_scope,'measure');assert.equal(h.changes,1);assert.deepEqual(Array.from(source.manual_fields),['beat']);
 local.value='1.333334';assert.equal(local.onchange(),true);assert.ok(Math.abs(source.beat-296.333334)<1e-10);assert.equal(source.measure_beat,.333334);assert.equal(h.changes,2);
});

test('local beat edits and current-onset shortcuts set measure anchors, while advanced absolute edits clear them',()=>{
 const first=note({id:'first',beat:296,measure_start_beat:296,measure_beat:0,meter_beats:4,bbox:[100,100,110,110]}),
   second=note({id:'second',beat:297,measure_start_beat:296,measure_beat:1,meter_beats:4,bbox:[150,100,160,110]});
 const h=harness({...project([first,second]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select('first',false);
 h.nodes['review-local-beat'].value='1.25';assert.equal(h.nodes['review-local-beat'].onchange(),true);assert.equal(first.beat,296.25);assert.equal(first.measure_beat,.25);assert.equal(first.timing_anchor_scope,'measure');
 h.nodes['review-finger-3'].onclick();assert.equal(first.timing_anchor_scope,'measure');assert.equal(first.measure_beat,.25);
 h.nodes['review-beat'].value='296.75';h.nodes['review-beat'].onchange();assert.equal(first.beat,296.75);assert.equal(first.timing_anchor_scope,undefined);
 first.validation_pending=false;h.controller.select('second',false);h.nodes['review-onset-after'].onclick();assert.equal(second.beat,297.75);assert.equal(second.measure_beat,1.75);assert.equal(second.timing_anchor_scope,'measure');assert.match(h.nodes['review-onset-after'].title,/设置一次/);
});

test('local shortcut is unavailable when its measure base is unknown and does not invent an anchor',()=>{
 const before=note({id:'before',beat:0,measure_start_beat:null,measure_beat:null,bbox:[100,100,110,110]}),
   target=note({id:'target',beat:null,measure_start_beat:null,measure_beat:null,bbox:[150,100,160,110]});
 const h=harness({...project([before,target]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select('target',false);
 assert.equal(h.nodes['review-onset-after'].disabled,true);assert.equal(h.nodes['review-onset-simultaneous'].disabled,true);
 assert.equal(h.nodes['review-onset-after'].onclick(),false);assert.equal(target.beat,null);assert.equal(target.timing_anchor_scope,undefined);assert.equal(target.manual_fields,undefined);
});

test('explicit local confirmation can switch a pending absolute anchor to measure scope without changing its value',()=>{
 const source=note({beat:296.25,measure_start_beat:296,measure_beat:.25,meter_beats:4,manual_fields:['beat'],validation_pending:true});
 const h=harness({...project([source]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select('one',false);
 h.nodes['review-local-confirm'].onclick();assert.equal(source.timing_anchor_scope,'measure');assert.equal(source.beat,296.25);assert.equal(source.measure_beat,.25);assert.equal(h.changes,1);
});

test('misclassified left note can be recovered through the secondary entry without showing a hand selector normally',()=>{
 const left=note({id:'left',hand:'left',bbox:[140,100,150,110]}),right=note({id:'right'}),h=harness({...project([right,left]),automatic_mode:true});
 h.nodes['review-show-all-notes'].onclick();assert.equal(h.nodes['review-filter'].value,'all');
 h.nodes['review-overlay'].children.find(e=>e.dataset.noteId==='left').onclick();assert.equal(h.nodes['review-hand-repair'].hidden,false);
 h.nodes['review-hand-repair'].onclick();assert.equal(left.hand,'right');assert.ok(left.manual_fields.includes('hand'));assert.equal(h.nodes['review-filter'].value,'right');assert.deepEqual(h.externalCalls,[]);
});

test('timing refresh updates derived positions while preserving a focused draft',()=>{
 const source=note({id:'source'}),following=note({id:'following',beat:1,measure_start_beat:0,measure_beat:1,meter_beats:4,bbox:[150,100,160,110]});
 const h=harness({...project([source,following]),automatic_mode:true,right_hand_timing:{version:1}});h.controller.select('following',false);
 following.beat=3;following.measure_beat=3;h.controller.refreshTiming();assert.equal(h.nodes['review-beat'].value,3);assert.equal(h.nodes['review-local-beat'].value,'4');
 const input=h.nodes['review-pitch'];input.tagName='INPUT';input.value='F#';h.document.activeElement=input;h.nodes['review-inspector'].contains=n=>n===input;
 following.beat=3.5;following.measure_beat=3.5;h.controller.refreshTiming();assert.equal(input.value,'F#');assert.equal(h.nodes['review-beat'].value,3.5);assert.equal(following.pitch,'C4');
 assert.equal(h.changes,0);assert.deepEqual(h.externalCalls,[]);
});
test('pointing at a source box opens the compact editor without a duplicate crop or mutation',()=>{const h=harness(project([note(),note({id:'two',pitch:'D4',finger:2,bbox:[150,100,160,110]})]));h.nodes['review-overlay'].children[1].onclick();assert.equal(h.controller.current().id,'two');assert.equal(h.nodes['review-pitch'].value,'D4');assert.equal(h.nodes['review-finger'].value,2);assert.match(h.nodes['review-row-image'].innerHTML,/data:image/);assert.equal(h.nodes['review-crop'],undefined);assert.equal(h.nodes['review-confirm'],undefined);assert.equal(h.changes,0);});
test('filters preserve the currently read source and left-hand notes do not count as issues',()=>{const h=harness(project([note({id:'left',hand:'left'}),note({id:'done',confirmed:true}),note({id:'pending',page:2})]),[{page:1,data:'data:image/png;base64,AAAA'},{page:2,data:'data:image/png;base64,BBBB'}]);assert.equal(h.controller.current().id,'done');assert.equal(h.page,0);assert.equal(h.nodes['review-count'].textContent,'可处理 2 · 需检查 0');h.nodes['review-filter'].value='all';h.nodes['review-filter'].onchange();assert.equal(h.controller.current().id,'done');assert.equal(h.page,0);assert.equal(Review.noteConcern(h.project.notes[0]),false);});
test('unfingered unmeasured grace matches backend readiness and becomes incomplete after setting a finger',()=>{for(const kind of ['slashed','unmeasured_prefix','unmeasured']){const n=note({finger:null,source_fingering_state:'unmarked',grace_kind:kind,duration_beats:null}),h=harness(project([n]));assert.equal(Review.noteConcern(n),false);assert.match(h.nodes['review-count'].textContent,/可处理 1 · 需检查 0/);h.controller.select(n.id,false);assert.match(h.nodes['review-note-warning'].textContent,/补号后可设置时值/);n.finger=2;n.finger_source='manual';h.controller.render();assert.equal(Review.noteConcern(n),true);assert.match(h.nodes['review-count'].textContent,/需检查 1/);}});
test('a duration-only grace warning does not call a known onset an estimate',()=>{const n=note({finger:null,source_fingering_state:'unmarked',grace_kind:'slashed',duration_beats:null,timing_estimated:false,timing_warning:'装饰音无固定时值，主拍位置保留'}),h=harness(project([n]));h.controller.select(n.id,false);assert.match(h.nodes['review-note-warning'].textContent,/装饰音/);assert.doesNotMatch(h.nodes['review-note-warning'].textContent,/起拍约/);});
test('edits persist field provenance without filling an unknown onset or requiring approval',()=>{const n=note({confirmed:true,beat:null,written_beat:7.25}),h=harness(project([n]));h.controller.select('one',false);assert.equal(h.nodes['review-beat'].value,'');assert.equal(h.nodes['review-beat'].placeholder,'候选 7.25');h.nodes['review-pitch'].value='D4';h.nodes['review-pitch'].onchange();assert.equal(n.pitch,'D4');assert.equal(n.confirmed,false);assert.equal(n.beat,null);assert.equal(n.validation_pending,true);assert.deepEqual(Array.from(n.manual_fields),['pitch']);assert.equal(h.project.selection.range_reviewed,false);assert.equal(h.project.selection.ties_reviewed,false);assert.equal(h.project.selection.repeats_reviewed,false);});
test('a valid digit saves immediately without confirming this or any neighboring note',()=>{const a=note(),b=note({id:'two',finger:null}),h=harness(project([a,b]));h.controller.select('two',false);h.nodes['review-finger-2'].onclick();assert.equal(b.finger,2);assert.equal(b.confirmed,false);assert.equal(a.confirmed,false);assert.deepEqual(Array.from(b.manual_fields),['finger']);assert.equal(Review.noteConcern(b),false);assert.equal(h.nodes['review-confirm'],undefined);assert.equal(h.controller.confirmCurrent,undefined);});
test('right click toggles exclusion on the retained note while keeping its lower editor open',()=>{const a=note(),h=harness(project([a])),label=h.nodes['review-row-annotations'].children.find(e=>e.className.startsWith('review-row-label'));const event={preventDefault(){},stopPropagation(){}};label.oncontextmenu(event);assert.equal(a.excluded,true);assert.equal(a.excluded_manual,true);assert.equal(a.confirmed,false);assert.equal(label.classList.contains('excluded'),true);assert.match(h.nodes['review-pending-count'].textContent,/已忽略 1/);assert.ok(h.nodes['review-row-annotations'].children.includes(label));assert.equal(h.nodes['review-inspector'].classList.contains('quick-open'),false);label.oncontextmenu(event);assert.equal(a.excluded,false);assert.equal(a.excluded_manual,true);assert.equal(a.confirmed,false);assert.equal(label.classList.contains('excluded'),false);assert.ok(h.nodes['review-row-annotations'].children.includes(label));});
test('missing verified original never displays imported arbitrary data as the real score',()=>{const h=harness({...project([note()]),page_previews:[{page:1,data:'https://untrusted.invalid/source.png'}]},[]);assert.match(h.nodes['review-row-image'].innerHTML,/对应 PDF/);assert.equal(h.nodes['review-overlay'].children.length,0);assert.doesNotMatch(h.nodes['review-row-image'].innerHTML,/untrusted/);h.changePreviews([{page:1,data:'javascript:alert(1)'}]);h.controller.render();assert.doesNotMatch(h.nodes['review-row-image'].innerHTML,/javascript/);});
test('tutorial stays progressive, offline and leaves the original notes unchanged',()=>{
 const h=harness(project([note()])),before=JSON.stringify(h.project);h.nodes['review-help'].onclick();
 assert.equal(h.nodes['score-guide'].hidden,false);assert.equal(h.nodes['guide-count'].textContent,'1 / '+Review.lessons.length);
 for(let i=1;i<Review.lessons.length;i++)h.nodes['guide-next'].onclick();
 assert.equal(h.nodes['guide-count'].textContent,Review.lessons.length+' / '+Review.lessons.length);
 assert.match(h.nodes['guide-body'].textContent,/反复/);h.nodes['guide-next'].onclick();
 assert.equal(h.nodes['score-guide'].hidden,true);assert.equal(h.changes,0);assert.equal(JSON.stringify(h.project),before);
 for(const lesson of Review.lessons)for(const frame of lesson.frames){assert.match(frame.art,/<svg/);assert.doesNotMatch(frame.art,/<script|(?:href|src)="https?:/);assert.match(frame.art,/非原谱/);}
 assert.match(Review.notationReferences[4].tip,/1.5/);assert.deepEqual(h.externalCalls,[]);assert.equal(h.timers.size,0);
});
const lessonById=id=>{const lesson=Review.lessons.find(x=>x.id===id);assert.ok(lesson,'missing tutorial lesson '+id);return lesson;};
const lessonIndex=id=>Review.lessons.indexOf(lessonById(id));
const flushAudio=async()=>{await Promise.resolve();await Promise.resolve();};
test('beginner lessons start with concrete keyboard examples and keep specialist theory in references',()=>{
 assert.equal(new Set(Review.lessons.map(x=>x.id)).size,Review.lessons.length);assert.equal(Review.lessons.length,12);
 for(const lesson of Review.lessons){assert.ok(lesson.frames.length>=(['right-hand','fingers'].includes(lesson.id)?1:2),lesson.id+' needs a visible sequence');for(const frame of lesson.frames){assert.ok(frame.label&&frame.text,lesson.id+' explains the current action');assert.ok(Number.isFinite(frame.ms)&&frame.ms>0,lesson.id+' has a timed action');assert.ok(Array.isArray(frame.tones));assert.ok(frame.tones.every(m=>Number.isInteger(m)&&m>=0&&m<=127));}}
 for(const id of ['find-do','pitch-step']){const lesson=lessonById(id),basic=[lesson.title,lesson.body,...lesson.frames.map(x=>x.text)].join(' ');assert.doesNotMatch(basic,/8va|8vb|BPM|八度|四分音符|三连音/);assert.match(basic,/键/);}
 const doLesson=lessonById('find-do');assert.ok(doLesson.frames.some(x=>x.tones.includes(60)),'central Do has an audible middle-C example');
 const advanced=Review.notationReferences.map(x=>x.body+' '+x.tip).join(' ');assert.match(advanced,/6\/8/);assert.match(advanced,/三连音/);assert.match(advanced,/8va/);assert.match(advanced,/不按音高猜/);
});
test('sounding tutorial notes light the matching keys and use truthful treble-staff pitches',()=>{
 const toMidi=pitch=>{const [,letter,accidental,octave]=/^([A-G])(#|b|)(\d+)$/.exec(pitch);return (Number(octave)+1)*12+{C:0,D:2,E:4,F:5,G:7,A:9,B:11}[letter]+({'#':1,b:-1,'':0}[accidental]);};let matched=0;
 for(const lesson of Review.lessons)for(const frame of lesson.frames){
  for(const tone of frame.tones)assert.match(frame.art,new RegExp('data-key="'+tone+'" data-pressed="true"'),lesson.id+' '+frame.label+' lights its sounding key');
  const heads=[...frame.art.matchAll(/<ellipse data-pitch="([^"]+)" cx="([\d.]+)" cy="([\d.]+)"/g)];if(!heads.length)continue;
  assert.match(frame.art,/data-clef="treble"/);const top=Number(frame.art.match(/data-staff-top="([\d.]+)"/)[1]),gap=Number(frame.art.match(/data-staff-gap="([\d.]+)"/)[1]);
  for(const [,pitch,,y]of heads){const [,letter,,octave]=/^([A-G])(#|b|)(\d+)$/.exec(pitch);assert.equal(Number(y),top+(38-(Number(octave)*7+'CDEFGAB'.indexOf(letter)))*gap/2,lesson.id+' '+pitch+' belongs at this staff height');}
  for(const tone of frame.tones){assert.ok(heads.some(h=>toMidi(h[1])===tone),lesson.id+' '+frame.label+' score agrees with sounding key');matched++;}
 }
 assert.ok(matched>=10,'keyboard and staff mapping is exercised across concrete examples');
});
test('rest, chords, ties and repeat demonstrations preserve their musical meaning',()=>{
 const rest=lessonById('rest').frames;assert.ok(rest.some(x=>x.tones.length===0&&/等|松|休/.test(x.text)), 'rest shows real silence and waiting');assert.ok(rest.some(x=>x.tones.length>0));
 assert.ok(lessonById('chord').frames.some(x=>new Set(x.tones).size>=2),'chord includes simultaneous distinct notes');
 const tie=lessonById('tie').frames,held=tie.findIndex(x=>x.sustain);assert.ok(held>0,'tie has a continued held note');assert.deepEqual(tie[held].tones,tie[held-1].tones);assert.ok(tie[held].tones.length>0);assert.deepEqual(tie.at(-1).tones,[],'tie ends by releasing the key');
 const slur=lessonById('slur').frames.filter(x=>x.tones.length);assert.ok(slur.length>=2,'slur retains both note events');assert.notDeepEqual(slur[0].tones,slur[1].tones);assert.ok(!slur[1].sustain,'different slurred notes must trigger a changed pitch');
 assert.deepEqual(lessonById('repeat').frames.filter(x=>x.part).map(x=>x.part),['A','B','A','C']);
});
test('changing lesson or closing a running demonstration cancels timers and releases sound',async()=>{
 const h=harness(project([note()])),before=JSON.stringify(h.project);h.nodes['guide-sound'].checked=true;h.controller.showGuide(lessonIndex('tie'));
 await h.nodes['guide-play'].onclick();await flushAudio();assert.ok(h.timers.size>0);assert.ok(h.oscillators.some(x=>x.started&&!x.stopped),'demo actually started sound');
 const staleCallbacks=[...h.timers.values()].map(x=>x.fn);h.controller.showGuide(lessonIndex('rest'));
 assert.equal(h.timers.size,0);assert.ok(h.oscillators.every(x=>!x.started||x.stopped));const changedPicture=h.nodes['guide-picture'].innerHTML;
 for(const run of staleCallbacks)run();assert.equal(h.nodes['guide-picture'].innerHTML,changedPicture,'stale callbacks cannot redraw an earlier lesson');assert.equal(h.timers.size,0);
 await h.nodes['guide-play'].onclick();await flushAudio();assert.ok(h.timers.size>0);h.nodes['guide-close'].onclick();
 assert.equal(h.nodes['score-guide'].hidden,true);assert.equal(h.timers.size,0);assert.ok(h.oscillators.every(x=>!x.started||x.stopped));h.advance(60000);
 assert.equal(JSON.stringify(h.project),before);assert.equal(h.changes,0);assert.deepEqual(h.externalCalls,[]);
});
test('a tied note continues through the second frame without another key attack',async()=>{
 const h=harness(project([note()])),frames=lessonById('tie').frames;h.nodes['guide-sound'].checked=true;h.controller.showGuide(lessonIndex('tie'));
 await h.nodes['guide-play'].onclick();await flushAudio();const attacks=()=>h.oscillators.filter(x=>x.started).length,firstAttacks=attacks();assert.ok(firstAttacks>0);
 h.advance(frames[0].ms);await flushAudio();assert.equal(attacks(),firstAttacks,'continued tied note does not retrigger audio');assert.ok(h.oscillators.some(x=>x.started&&!x.stopped));
 h.advance(frames[1].ms);await flushAudio();assert.ok(h.oscillators.every(x=>!x.started||x.stopped),'release frame stops sound');h.nodes['guide-close'].onclick();
});
test('the rest demonstration is silent while waiting and releases everything when it finishes',async()=>{
 const h=harness(project([note()])),frames=lessonById('rest').frames;h.nodes['guide-sound'].checked=true;h.controller.showGuide(lessonIndex('rest'));
 await h.nodes['guide-play'].onclick();await flushAudio();assert.ok(h.oscillators.some(x=>x.started&&!x.stopped));
 h.advance(frames[0].ms);await flushAudio();assert.ok(h.oscillators.every(x=>!x.started||x.stopped),'the rest is silent for the entire waiting frame');const attacks=h.oscillators.filter(x=>x.started).length;
 h.advance(frames[1].ms-1);await flushAudio();assert.equal(h.oscillators.filter(x=>x.started).length,attacks,'the next note must not start early');
 h.advance(1);await flushAudio();assert.ok(h.oscillators.some(x=>x.started&&!x.stopped),'the next note starts only after the full rest');
 h.advance(frames[2].ms);await flushAudio();assert.equal(h.timers.size,0);assert.ok(h.oscillators.every(x=>!x.started||x.stopped));assert.deepEqual(h.externalCalls,[]);assert.equal(h.changes,0);
});
test('late audio permission resolution cannot restart a closed tutorial',async()=>{
 const h=harness(project([note()]));h.deferAudio();h.nodes['guide-sound'].checked=true;h.controller.showGuide(lessonIndex('tie'));
 const starting=h.nodes['guide-play'].onclick();h.nodes['guide-close'].onclick();h.resolveAudio();await starting;await flushAudio();
 assert.equal(h.timers.size,0);assert.ok(h.oscillators.every(x=>!x.started||x.stopped));assert.equal(h.nodes['score-guide'].hidden,true);assert.deepEqual(h.externalCalls,[]);assert.equal(h.changes,0);
});
test('whole-row crop covers the real staff start, rests, printed finger and stem without using note-only bounds',()=>{const p=project([note({bbox:[104.358,196.302,114.539,203.301],finger_bbox:[105.631,184.343,110.82,191.02],rhythm_evidence:{stem:[105.955,199.799,221.434]}})]);p.staves=[{page:1,system:1,hand:'right',bbox:[47.728,193.436,550.454,218.889]}];const row=Review.rowsFor(p)[0],crop=Review.rowCropFor(row,p.pages[0]);assert.ok(crop.x<47.728&&crop.x+crop.width>550.454);assert.ok(crop.y<184.343&&crop.y+crop.height>221.434);assert.ok(crop.width>500);const h=harness(p);assert.match(h.nodes['review-row-image'].innerHTML,/原 PDF 第 1 页第 1 行右手整行/);assert.match(h.nodes['review-row-image'].innerHTML,/data:image\/png;base64,AAAA/);assert.equal(h.nodes.original.hidden,true);h.nodes['review-row-mode'].onclick();assert.equal(h.nodes.original.hidden,false);assert.equal(h.nodes['review-row-panel'].hidden,true);});
test('dense sixteenth notes and chord labels keep true horizontal anchors and never overlap within a lane',()=>{const notes=Array.from({length:30},(_,i)=>note({id:'n'+i,bbox:[50+Math.floor(i/2)*12,100+(i%2)*8,57+Math.floor(i/2)*12,107+(i%2)*8]})),crop={x:30,y:60,width:500,height:100},layout=Review.rowAnnotationLayout(notes,crop,640);assert.equal(layout.items.length,30);assert.ok(layout.lanes>1);for(const item of layout.items){assert.equal(item.anchor,((item.note.bbox[0]+item.note.bbox[2])/2-crop.x)/crop.width*640);assert.ok(item.left>=0&&item.left+item.width<=640);for(const other of layout.items)if(other!==item&&other.lane===item.lane)assert.ok(item.left+item.width+4<=other.left||other.left+other.width+4<=item.left);}assert.equal(layout.items[0].anchor,layout.items[1].anchor);});
test('batch confirmation touches only complete right-hand notes from this exact page and system',()=>{const a=note(),b=note({id:'b',finger:null}),c=note({id:'c',hand:null}),left=note({id:'left',hand:'left'}),next=note({id:'next',system:2}),page2=note({id:'page2',page:2}),excluded=note({id:'excluded',excluded:true}),withIssue=note({id:'issue',issues:['tie_or_slur_requires_review']});const h=harness(project([a,b,c,left,next,page2,excluded,withIssue]));h.nodes['review-row-confirm'].onclick();assert.equal(a.confirmed,true);assert.equal(withIssue.confirmed,true);for(const untouched of [b,c,left,next,page2,excluded])assert.equal(untouched.confirmed,false,untouched.id);assert.equal(h.project.selection.range_reviewed,false);assert.equal(h.project.selection.ties_reviewed,false);assert.equal(h.project.selection.repeats_reviewed,false);assert.match(h.nodes['review-row-status'].textContent,/2 待处理/);h.controller.select('one',false);h.nodes['review-pitch'].value='D4';h.nodes['review-pitch'].onchange();assert.equal(a.confirmed,false);});
test('row annotations retain note membership in issue-only mode and return to all labels',()=>{const a=note(),b=note({id:'b',automatic_reasons:['节奏需检查']}),c=note({id:'c',confirmed:true,issues:['reviewed_issue']});const h=harness(project([a,b,c]));const labels=()=>h.nodes['review-row-annotations'].children.filter(n=>n.className.startsWith('review-row-label')&&!n.hidden);assert.equal(labels().length,3);assert.ok(labels().find(n=>n.className.includes('confirmed')));h.nodes['review-filter'].value='pending';h.nodes['review-filter'].onchange();assert.equal(labels().length,1);assert.equal(labels()[0].classList.contains('uncertain'),false);assert.equal(labels()[0].classList.contains('attention'),true);labels()[0].onclick();assert.equal(h.controller.current().id,'b');assert.ok(h.nodes['review-workspace'].classes.has('row-editing'));h.nodes['review-editor-close'].onclick();assert.equal(h.nodes['review-workspace'].classes.has('row-editing'),false);h.nodes['review-filter'].value='right';h.nodes['review-filter'].onchange();assert.equal(labels().length,3);});
test('row navigation and external page changes keep the crop and current note on the same original page',()=>{const p=project([note(),note({id:'row2',system:2}),note({id:'page2',page:2})]),h=harness(p,[{page:1,data:'data:image/png;base64,AAAA'},{page:2,data:'data:image/png;base64,BBBB'}]);h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'row2');h.nodes['review-row-next'].onclick();assert.equal(h.page,1);assert.equal(h.controller.current().id,'page2');assert.match(h.nodes['review-row-image'].innerHTML,/BBBB/);h.controller.pageChanged();assert.equal(h.controller.current().id,'page2');h.nodes['review-row-prev'].onclick();assert.equal(h.page,0);assert.equal(h.controller.current().id,'row2');assert.match(h.nodes['review-row-label'].textContent,/第 1 页 · 第 2 行/);});
test('confirming visible issues never confirms the normal notes hidden by that filter',()=>{const normal=note(),issue=note({id:'issue',automatic_reasons:['需检查']}),missing=note({id:'missing',finger:null}),h=harness(project([normal,issue,missing]));h.nodes['review-filter'].value='pending';h.nodes['review-filter'].onchange();assert.equal(h.nodes['review-row-confirm'].textContent,'确认本行 · 1 音');h.nodes['review-row-confirm'].onclick();assert.equal(issue.confirmed,true);assert.equal(normal.confirmed,false);assert.equal(missing.confirmed,false);assert.equal(h.nodes['review-row-confirm'].disabled,true);h.nodes['review-filter'].value='right';h.nodes['review-filter'].onchange();assert.equal(h.nodes['review-row-confirm'].textContent,'确认本行 · 1 音');h.nodes['review-row-confirm'].onclick();assert.equal(normal.confirmed,true);assert.equal(missing.confirmed,false);});
test('unlocated notes are not batch-approved but remain editable with explicit field provenance',()=>{const valid=note(),notes=[valid,...[undefined,[5,5,4,8],[5,5,8,5],[1,2,NaN,4],[900,100,910,110]].map((bbox,i)=>note({id:'invalid-'+i,bbox}))],h=harness(project(notes));const labels=()=>h.nodes['review-row-annotations'].children.filter(n=>n.className.startsWith('review-row-label')&&!n.hidden);assert.equal(labels().length,1);h.nodes['review-row-confirm'].onclick();assert.equal(valid.confirmed,true);for(const n of notes.slice(1))assert.equal(n.confirmed,false,n.id);h.controller.select('invalid-0',false);h.nodes['review-finger-2'].onclick();assert.equal(notes[1].finger,2);assert.equal(notes[1].confirmed,false);assert.deepEqual(Array.from(notes[1].manual_fields),['finger']);assert.equal(notes[2].finger,1);});
const twoPagePreviews=[{page:1,data:'data:image/png;base64,AAAA'},{page:2,data:'data:image/png;base64,BBBB'}];
const useIssueRows=h=>{h.nodes['review-filter'].value='pending';h.nodes['review-filter'].onchange();};
test('row boundaries follow page and system order, show total position and never wrap',()=>{
 const h=harness(project([note({id:'last',page:2,system:2}),note({id:'first'}),note({id:'third',page:2,system:1}),note({id:'second',system:3})]),twoPagePreviews);
 h.controller.select('first',false);assert.equal(h.nodes['review-row-prev'].disabled,true);assert.equal(h.nodes['review-row-next'].disabled,false);assert.match(h.nodes['review-row-position'].textContent,/1\s*\/\s*4\s*行/);
 h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'first','first row has no previous row');
 for(const id of ['second','third','last']){h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,id);}
 assert.equal(h.page,1);assert.equal(h.nodes['review-row-prev'].disabled,false);assert.equal(h.nodes['review-row-next'].disabled,true);assert.match(h.nodes['review-row-position'].textContent,/4\s*\/\s*4\s*行/);assert.match(h.nodes['review-row-boundary'].textContent,/最后一行/);
 h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'last','last row does not wrap to the first');assert.equal(h.page,1);assert.equal(h.changes,0);
 h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'third');h.nodes['review-row-prev'].onclick();assert.equal(h.page,0);assert.equal(h.controller.current().id,'second');
});
test('single-row score disables both directions without losing its selected source',()=>{
 const h=harness(project([note()]));assert.equal(h.nodes['review-row-prev'].disabled,true);assert.equal(h.nodes['review-row-next'].disabled,true);assert.match(h.nodes['review-row-position'].textContent,/1\s*\/\s*1\s*行/);
 h.nodes['review-row-next'].onclick();h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'one');assert.equal(h.page,0);assert.equal(h.changes,0);
});
test('row chooser jumps across pages and remains usable to return from the final row',()=>{
 const h=harness(project([note({id:'first'}),note({id:'second',system:2}),note({id:'last',page:2,system:3})]),twoPagePreviews);
 h.nodes['review-row-select'].value='2:3';h.nodes['review-row-select'].onchange();assert.equal(h.controller.current().id,'last');assert.equal(h.page,1);assert.match(h.nodes['review-row-image'].innerHTML,/BBBB/);assert.match(h.nodes['review-row-label'].textContent,/第 2 页 · 第 3 行/);assert.match(h.nodes['review-row-position'].textContent,/3\s*\/\s*3\s*行/);assert.equal(h.nodes['review-row-next'].disabled,true);
 h.nodes['review-row-select'].value='1:1';h.nodes['review-row-select'].onchange();assert.equal(h.controller.current().id,'first');assert.equal(h.page,0);assert.match(h.nodes['review-row-image'].innerHTML,/AAAA/);assert.equal(h.nodes['review-row-prev'].disabled,true);assert.equal(h.changes,0);
});
test('issue navigation starts from a normal middle row and finds its true neighbors',()=>{
 const h=harness(project([note({id:'before',automatic_reasons:['需检查']}),note({id:'normal',system:2}),note({id:'after',system:3,automatic_reasons:['需检查']}),note({id:'next-page',page:2,automatic_reasons:['需检查']})]),twoPagePreviews);
 h.controller.select('normal',false);useIssueRows(h);assert.equal(h.controller.current().id,'normal','enabling the filter keeps the row being read');assert.equal(h.nodes['review-row-prev'].disabled,false);assert.equal(h.nodes['review-row-next'].disabled,false);
 h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'after','next issue is after the current normal row');h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'before');assert.equal(h.nodes['review-row-prev'].disabled,true);
 h.controller.select('normal',false);h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'before');assert.equal(h.changes,0);
});
test('needs-check navigation excludes ignored notes while the ignored filter restores them',()=>{
 const h=harness(project([note({id:'normal-before'}),note({id:'first-issue',system:2,automatic_reasons:['需检查']}),note({id:'normal-middle',system:3}),note({id:'last-issue',page:2,system:1,automatic_reasons:['需检查']}),note({id:'excluded',page:2,system:3,excluded:true}),note({id:'normal-after',page:2,system:4})]),twoPagePreviews);
 h.controller.select('first-issue',false);useIssueRows(h);h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'last-issue');assert.equal(h.nodes['review-row-next'].disabled,true);
 h.nodes['review-filter'].value='excluded';h.nodes['review-filter'].onchange();h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'excluded');assert.equal(h.nodes['review-row-next'].disabled,true);
 h.controller.setExcluded(h.controller.current(),false);assert.equal(h.project.notes.find(n=>n.id==='excluded').excluded,false);assert.equal(h.nodes['review-row-annotations'].children.find(n=>n.dataset.noteId==='excluded').hidden,false,'restored target stays at its location until navigating away');
});

test('server validation refresh keeps note nodes and an in-progress input intact',()=>{
 const before=note({id:'before',automatic_reasons:['需检查']}),middle=note({id:'middle',system:2,automatic_reasons:['需检查']}),after=note({id:'after',page:2,automatic_reasons:['需检查']}),h=harness(project([before,middle,after]),twoPagePreviews);h.controller.select('middle',false);useIssueRows(h);const hit=h.nodes['review-row-hits'].children[0],image=h.nodes['review-row-image'].innerHTML;h.nodes['review-pitch'].value='D#4 typing';middle.automatic_reasons=[];middle.automatic_ready=true;middle.validation_pending=false;h.controller.refreshValidation();assert.equal(h.nodes['review-row-hits'].children[0],hit);assert.equal(h.nodes['review-row-image'].innerHTML,image);assert.equal(h.nodes['review-pitch'].value,'D#4 typing');assert.equal(h.controller.current().id,'middle');assert.equal(middle.confirmed,false);h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'after');h.controller.select('middle',false);h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'before');
});

test('resolving first or last issue disables the exhausted side without wrapping',()=>{
 for(const selected of ['first','last']){const first=note({id:'first',automatic_reasons:['需检查']}),last=note({id:'last',page:2,system:2,automatic_reasons:['需检查']}),h=harness(project([first,last]),twoPagePreviews);h.controller.select(selected,false);useIssueRows(h);h.controller.current().automatic_reasons=[];h.controller.refreshValidation();assert.equal(h.nodes[selected==='first'?'review-row-prev':'review-row-next'].disabled,true);h.nodes[selected==='first'?'review-row-prev':'review-row-next'].onclick();assert.equal(h.controller.current().id,selected);h.nodes[selected==='first'?'review-row-next':'review-row-prev'].onclick();assert.equal(h.controller.current().id,selected==='first'?'last':'first');}
});

test('issue-free scores have no clickable dead-end navigation and retain access to every row',()=>{
 const h=harness(project([note(),note({id:'second',system:2}),note({id:'last',page:2,system:3,confirmed:true,issues:['reviewed']})]),twoPagePreviews);
 useIssueRows(h);assert.equal(h.nodes['review-row-prev'].disabled,true);assert.equal(h.nodes['review-row-next'].disabled,true);assert.match(h.nodes['review-row-boundary'].textContent,/没有待查音符/);
 h.nodes['review-row-prev'].onclick();h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'one');assert.equal(h.changes,0);
 h.nodes['review-filter'].value='right';h.nodes['review-filter'].onchange();h.nodes['review-row-select'].value='2:3';h.nodes['review-row-select'].onchange();assert.equal(h.controller.current().id,'last','all-right filter restores access to every row');assert.equal(h.page,1);assert.match(h.nodes['review-row-position'].textContent,/3\s*\/\s*3\s*行/);
 assert.equal(h.nodes['review-row-prev'].disabled,false);h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'second');
});
test('missing fields keep their row reachable after validation resolves other notes',()=>{
 const missing=note({id:'missing',system:2,finger:null}),complete=note({id:'complete',system:2,automatic_reasons:['需检查']}),later=note({id:'later',page:2,automatic_reasons:['需检查']}),h=harness(project([note(),missing,complete,later]),twoPagePreviews);h.controller.select('complete',false);useIssueRows(h);complete.automatic_reasons=[];h.controller.refreshValidation();assert.equal(complete.confirmed,false);h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'later');h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'missing');assert.equal(h.nodes['review-row-confirm'].disabled,true);
});


test('automatic review has no approval action and uses one real filter',()=>{
 const a=note({id:'ready'}),b=note({id:'missing',finger:null}),c=note({id:'ignored',excluded:true});const h=harness({...project([a,b,c]),automatic_mode:true});
 assert.equal(h.nodes['review-filter'].value,'right');assert.equal(h.nodes['review-row-problems'],undefined);assert.equal(h.nodes['review-row-confirm'].hidden,true);
 h.controller.confirmRow();assert.ok(h.project.notes.every(n=>!n.confirmed));
 h.nodes['review-filter'].value='pending';h.nodes['review-filter'].onchange();const visible=()=>h.nodes['review-row-annotations'].children.filter(e=>e.className.startsWith('review-row-label')&&!e.hidden).map(e=>e.dataset.noteId);assert.deepEqual(visible(),['missing']);
 h.nodes['review-filter'].value='excluded';h.nodes['review-filter'].onchange();assert.deepEqual(visible(),['ignored']);
});

test('direct issue navigation skips complete excluded and out-of-range notes across pages',()=>{
 const notes=[note({id:'ready'}),note({id:'first',finger:null,bbox:[120,100,130,110]}),note({id:'ignored',excluded:true,finger:null,bbox:[140,100,150,110]}),note({id:'outside',finger:null,in_export_scope:false,system:2}),note({id:'last',page:2,finger:null})];
 const h=harness({...project(notes),automatic_mode:true,selection:{end_page:1}},twoPagePreviews);
 assert.equal(h.controller.current().id,'first');h.nodes['review-issue-next'].onclick();assert.equal(h.controller.current().id,'last');assert.equal(h.page,1);assert.equal(h.nodes['review-issue-next'].disabled,true);h.nodes['review-issue-prev'].onclick();assert.equal(h.controller.current().id,'first');
 h.controller.focusIssue('outside');assert.equal(h.controller.current().id,'outside');assert.match(h.nodes['review-note-warning'].textContent,/范围外/);assert.match(h.nodes['review-count'].textContent,/所选范围/);
});

test('an explicit auto-next opt-out can be enabled and persists for the workspace',()=>{
 const ready=note({id:'ready'}),gray=note({id:'gray',finger:null,source_fingering_state:'unmarked',bbox:[120,100,130,110]}),ignored=note({id:'ignored',finger:null,excluded:true,bbox:[140,100,150,110]}),left=note({id:'left',finger:null,hand:'left',bbox:[160,100,170,110]}),bad=note({id:'bad',page:2,finger:null});
 const p={...project([ready,gray,ignored,left,bad]),automatic_mode:true,selection:{auto_skip_processed:false}},h=harness(p,twoPagePreviews);
 assert.equal(h.nodes['review-auto-next'].checked,false);assert.equal(h.controller.current().id,'bad');h.controller.select('ready',false);
 h.nodes['review-auto-next'].checked=true;h.nodes['review-auto-next'].onchange();
 assert.equal(h.controller.current().id,'bad');assert.equal(h.page,1);assert.equal(p.selection.auto_skip_processed,true);assert.equal(h.changes,0);
 const restored={...project([note()]),automatic_mode:true,selection:{auto_skip_processed:true}};h.changeProject(restored);h.controller.render();assert.equal(h.nodes['review-auto-next'].checked,true);
});

test('saved auto-next preference applies on a new score only after validation',()=>{
 const h=harness({...project([note()]),automatic_mode:true},twoPagePreviews);
 h.nodes['review-auto-next'].checked=true;h.nodes['review-auto-next'].onchange();
 const next={...project([note({id:'done'}),note({id:'bad',page:2,finger:null})]),automatic_mode:true,validation_pending:true};
 h.changeProject(next);h.controller.render();assert.equal(h.nodes['review-auto-next'].checked,true);assert.equal(h.controller.current().id,'done');
 h.controller.refreshValidation();assert.equal(h.controller.current().id,'done');next.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'bad');assert.equal(h.page,1);
});

test('auto-next follows score order through a timing warning before a later incomplete note and can return to earlier work',()=>{
 const done=note({id:'done'}),warning=note({id:'warning',bbox:[130,100,140,110],timing_warning:'起拍待核对',timing_estimated:false}),bad=note({id:'bad',page:2,finger:null});
 const h=harness({...project([done,warning,bad]),automatic_mode:true},twoPagePreviews);h.controller.select('done',false);
 h.nodes['review-auto-next'].checked=true;h.nodes['review-auto-next'].onchange();assert.equal(h.controller.current().id,'warning');
 h.nodes['review-auto-next'].checked=false;h.nodes['review-auto-next'].onchange();h.controller.select('bad',false);bad.finger=2;bad.automatic_reasons=[];
 h.nodes['review-auto-next'].checked=true;h.nodes['review-auto-next'].onchange();assert.equal(h.controller.current().id,'warning');
});

test('when enabled the next-row control skips completed and gray-only rows, but explicit gray filter remains usable',()=>{
 const first=note({id:'first',finger:null}),done=note({id:'done',system:2}),gray=note({id:'gray',system:3,finger:null,source_fingering_state:'unmarked'}),bad=note({id:'bad',page:2,finger:null});
 const p={...project([first,done,gray,bad]),automatic_mode:true},h=harness(p,twoPagePreviews);
 h.nodes['review-auto-next'].checked=true;h.nodes['review-auto-next'].onchange();assert.equal(h.controller.current().id,'first');
 /* 11-04 用户：上一行/下一行走遍整首，只跳要查的用「下一处」 */h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'done');h.nodes['review-row-next'].onclick();h.nodes['review-row-next'].onclick();assert.equal(h.controller.current().id,'bad');assert.equal(h.page,1);
 h.nodes['review-filter'].value='unfingered';h.nodes['review-filter'].onchange();h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'gray');
 h.nodes['review-auto-next'].checked=false;h.nodes['review-auto-next'].onchange();h.nodes['review-filter'].value='right';h.nodes['review-filter'].onchange();h.nodes['review-row-prev'].onclick();assert.equal(h.controller.current().id,'done');
});

test('auto-next waits for successful validation and advances across pages once',()=>{
 const a=note({id:'first',finger:null}),gray=note({id:'gray',finger:null,source_fingering_state:'unmarked',bbox:[140,100,150,110]}),b=note({id:'later',page:2,finger:null,pitch:'D4'});
 const p={...project([a,gray,b]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.controller.select('first',false);h.nodes['review-finger-2'].onclick();assert.equal(h.controller.current().id,'first');
 p.validation_pending=true;a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'first');
 p.validation_pending=false;p.validation_error='检查暂未完成';h.controller.refreshValidation();assert.equal(h.controller.current().id,'first');
 p.validation_error='';h.controller.refreshValidation();assert.equal(h.controller.current().id,'later');assert.equal(h.page,1);
 h.controller.refreshValidation();assert.equal(h.controller.current().id,'later');
});

test('auto-next leaves a partially corrected issue in place until all its real fields are resolved',()=>{
 const a=note({id:'first',finger:null,pitch:null}),b=note({id:'later',page:2,finger:null,pitch:'D4'});
 const p={...project([a,b]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.nodes['review-finger-2'].onclick();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'first');
 h.nodes['review-pitch'].value='E4';h.nodes['review-pitch'].onchange();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'later');
});

test('auto-next does not override a manual navigation or an actively edited input',()=>{
 const a=note({id:'first',finger:null}),b=note({id:'manual',system:2}),c=note({id:'later',page:2,finger:null});
 const p={...project([a,b,c]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.nodes['review-finger-2'].onclick();h.controller.select('manual',false);a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'manual');
 h.controller.select('later',false);h.nodes['review-finger-3'].onclick();const draft=h.nodes['review-pitch'];draft.tagName='INPUT';draft.value='F#';h.nodes['review-inspector'].contains=e=>e===draft;h.document.activeElement=draft;c.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'later');assert.equal(draft.value,'F#');
 h.document.activeElement=null;h.focusOutDocument();h.advance(0);assert.equal(h.controller.current().id,'later');assert.match(h.notice,/没有待处理|前面|都看完了/);
});

test('same missing finger on the same pitch and chord is fixed once for all',()=>{
 const a=note({id:'a',finger:null}),b=note({id:'b',finger:null,page:2}),c=note({id:'c',finger:null,beat:1,bbox:[130,100,140,110],pitch:'D4'}),p={...project([a,b,c]),automatic_mode:true},h=harness(p,twoPagePreviews);
 h.controller.select('a',false);h.nodes['review-finger-3'].onclick();assert.equal(a.finger,3);assert.equal(b.finger,3);assert.equal(c.finger,null);
});
test('auto-next waits for an external conversion text, number, textarea or select input to blur',()=>{
 for(const [tag,type] of [['INPUT','number'],['INPUT','text'],['TEXTAREA',''],['SELECT','']]){
  const a=note({id:'first',finger:null}),b=note({id:'later',page:2,finger:null,pitch:'D4'});
  const p={...project([a,b]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
  h.nodes['review-finger-2'].onclick();const draft=h.nodes.bpm;draft.tagName=tag;draft.type=type;draft.value='96';
  h.nodes.convert.contains=element=>element===draft;h.document.activeElement=draft;a.validation_pending=false;
  h.controller.refreshValidation();assert.equal(h.controller.current().id,'first');assert.equal(h.page,0);assert.equal(draft.value,'96');
  h.document.activeElement=null;h.focusOutDocument();h.advance(0);assert.equal(h.controller.current().id,'later');assert.equal(h.page,1);
 }
});

test('focusing the auto-next checkbox does not prevent its immediate jump',()=>{
 const done=note({id:'done'}),bad=note({id:'bad',page:2,finger:null});
 const p={...project([done,bad]),automatic_mode:true},h=harness(p,twoPagePreviews),box=h.nodes['review-auto-next'];
 box.tagName='INPUT';box.type='checkbox';h.nodes.convert.contains=element=>element===box;h.document.activeElement=box;
 box.checked=true;box.onchange();assert.equal(h.controller.current().id,'bad');assert.equal(h.page,1);
});

test('manual row selection while an external select is active cancels a delayed auto-next',()=>{
 const a=note({id:'first',finger:null}),manual=note({id:'manual',system:2,finger:null}),later=note({id:'later',page:2,finger:null});
 const p={...project([a,manual,later]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.nodes['review-finger-2'].onclick();const select=h.nodes['review-row-select'];select.tagName='SELECT';h.nodes.convert.contains=e=>e===select;h.document.activeElement=select;
 a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'first');
 select.value='1:2';select.onchange();assert.equal(h.controller.current().id,'manual');
 h.document.activeElement=null;h.focusOutDocument();h.advance(0);assert.equal(h.controller.current().id,'manual');
});

test('manual row change cancels a pending auto-next before delayed validation',()=>{
 const a=note({id:'first',finger:null}),b=note({id:'manual-row',system:2,automatic_reasons:['需检查']}),c=note({id:'later',page:2,finger:null});
 const p={...project([a,b,c]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.nodes['review-finger-2'].onclick();h.nodes['review-row-select'].value='1:2';h.nodes['review-row-select'].onchange();assert.equal(h.controller.current().id,'manual-row');
 a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'manual-row');
});

test('auto-next moves past inherited timing estimates without skipping their actual source warning',()=>{
 const source=note({id:'source',beat:0,measure_start_beat:0,measure_beat:0,timing_warning:'起拍待核对',timing_estimated:false});
 const follower=note({id:'follower',beat:1,bbox:[130,100,140,110],timing_estimated:true,timing_source_id:'source'}),bad=note({id:'bad',page:2,finger:null});
 const p={...project([source,follower,bad]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.nodes['review-beat'].value='0.5';h.nodes['review-beat'].onchange();assert.equal(h.controller.current().id,'source');
 source.validation_pending=false;source.timing_warning=null;h.controller.refreshValidation();assert.equal(h.controller.current().id,'bad');
});

test('auto-next returns to earlier pending work after the last issue, while explicit off leaves selection untouched',()=>{
 const a=note({id:'earlier',finger:null}),b=note({id:'last',page:2,finger:null,pitch:'D4'});
 const p={...project([a,b]),automatic_mode:true,selection:{auto_skip_processed:true}},h=harness(p,twoPagePreviews);
 h.controller.select('last',false);h.nodes['review-finger-4'].onclick();b.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'earlier');assert.equal(b.finger,4);
 h.nodes['review-auto-next'].checked=false;h.nodes['review-auto-next'].onchange();assert.equal(p.selection.auto_skip_processed,false);
 h.controller.select('earlier',false);h.nodes['review-finger-2'].onclick();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'earlier');
});

test('partial-export control is explicit and requires pending notes plus a ready action',()=>{
 const good=note({id:'ready',automatic_ready:true}),bad=note({id:'bad',finger:null,automatic_ready:false,automatic_reasons:['选择指法']});
 const p={...project([good,bad]),automatic_mode:true,automatic:{attention_notes:1}},h=harness(p);
 const button=h.nodes['review-export-skip-pending'];assert.equal(button.hidden,false);assert.equal(button.disabled,false);assert.match(button.textContent,/跳过待处理音导出（预计 1）/);assert.match(button.title,/预计跳过 1 个待处理音，导出时重新检查/);
 button.onclick();assert.equal(h.skipExports,1);p.validation_pending=true;h.controller.refreshValidation();assert.equal(button.disabled,true);button.onclick();assert.equal(h.skipExports,1);
 p.validation_pending=false;good.automatic_ready=false;h.controller.refreshValidation();assert.equal(button.disabled,true);p.automatic.attention_notes=0;h.controller.refreshValidation();assert.equal(button.hidden,true);
});

test('commit pending text before native actions and do not discard invalid local timing',()=>{
 const h=harness({...project([note({measure_start_beat:0,meter_beats:4})]),automatic_mode:true});h.controller.select('one',false);
 const input=h.nodes['review-pitch'];input.tagName='INPUT';h.nodes['review-inspector'].contains=e=>e===input||e===h.nodes['review-local-beat'];h.document.activeElement=input;input.value='F#4';input.blur=()=>{h.document.activeElement=null;};assert.equal(h.controller.commitPendingEdits(),true);assert.equal(h.project.notes[0].pitch,'F#4');assert.deepEqual(Array.from(h.project.notes[0].manual_fields),['pitch']);
 const local=h.nodes['review-local-beat'];local.tagName='INPUT';local.value='9';h.document.activeElement=local;local.blur=()=>{h.document.activeElement=null;};assert.equal(h.controller.commitPendingEdits(),false);assert.equal(h.project.notes[0].beat,0);assert.equal(local.value,'9');assert.match(h.notice,/超出/);h.document.activeElement=null;assert.equal(h.controller.commitPendingEdits(),false,'blur must not silently clear the invalid draft');h.document.activeElement=local;local.value='3';assert.equal(h.controller.commitPendingEdits(),true);assert.equal(h.project.notes[0].beat,2);
});


test('closing the editor explicitly cancels an invalid local position without changing the score',()=>{
 const h=harness({...project([note({measure_start_beat:0,meter_beats:4})]),automatic_mode:true});h.controller.select('one',false);const local=h.nodes['review-local-beat'];local.value='9';local.onchange();h.nodes['review-editor-close'].onclick();assert.equal(h.project.notes[0].beat,0);assert.equal(local.value,'1');assert.equal(h.controller.commitPendingEdits(),true);assert.match(h.notice,/未应用/);
});


test('changing originals resets expanded editor sections even when the first note ID is reused',()=>{
 for(const control of ['review-more-toggle','review-duration-toggle']){
  const h=harness({...project([note({id:'same'})]),automatic_mode:true});h.controller.select('same',false);h.nodes[control].onclick();assert.equal(h.nodes[control==='review-more-toggle'?'review-editor-more':'review-duration-picker'].hidden,false);
  h.changeProject({...project([note({id:'same',pitch:'G5'})]),automatic_mode:true,source_sha256:'another-original'});h.controller.render();h.controller.select('same',false);
  assert.equal(h.nodes['review-editor-more'].hidden,true,control);assert.equal(h.nodes['review-duration-picker'].hidden,false,control);assert.equal(h.nodes['review-more-toggle'].textContent,'其他设置');assert.equal(h.nodes['review-pitch'].value,'G5');
 }
});

test('programmatic issue focus updates a stable lower editor without popup coordinates',()=>{
 const h=harness({...project([note({id:'old'}),note({id:'new',finger:null,bbox:[700,300,710,310]})]),automatic_mode:true});
 h.document.documentElement={clientWidth:1200,clientHeight:800};h.nodes['review-inspector'].getBoundingClientRect=()=>({left:0,top:0,right:260,bottom:170});
 h.controller.select('old',false,{getBoundingClientRect:()=>({left:100,right:110,top:100,bottom:110})});
 const panel=h.nodes['review-inspector'];assert.equal(panel.style.left,'');assert.equal(panel.style.top,'');
 h.controller.focusIssue('new');assert.equal(h.controller.current().id,'new');assert.equal(panel.style.left,'');assert.equal(panel.style.top,'');assert.equal(panel.style.width,'');assert.ok(panel.classes.has('fixed-editor'));
 assert.match(h.nodes['review-selected-note'].textContent,/第 1 页/);assert.equal(h.nodes['review-editor-empty'].hidden,true);
});



test('source-unmarked empty fingering is ready data, while unresolved and legacy empty values stay questions',()=>{
 const gray=note({finger:null,source_fingering_state:'unmarked',unfingered:true});
 assert.equal(Review.unfingered(gray),true);assert.deepEqual(Review.missingFields(gray),[]);assert.equal(Review.fingerLabel(gray),'— 未设指法');assert.equal(Review.noteConcern(gray,true),false);
 for(const state of [undefined,'unresolved','printed']){const n=note({finger:null,source_fingering_state:state,unfingered:true});assert.equal(Review.unfingered(n),false);assert.deepEqual(Review.missingFields(n),['指法']);assert.equal(Review.noteConcern(n,true),true);}
 for(const finger of [0,6,1.5])assert.equal(Review.unfingered({...gray,finger}),false);
 assert.deepEqual(Review.missingFields({...gray,pitch:null,beat:null,duration_beats:null,hand:null}),['音高','开始','时长','左右手']);
});

test('gray unmarked note remains clickable, counted ready and separate from manual exclusion',()=>{
 const gray=note({id:'gray',finger:null,source_fingering_state:'unmarked',unfingered:true}),question=note({id:'question',finger:null,source_fingering_state:'unresolved',bbox:[140,100,150,110],beat:1});
 const h=harness({...project([gray,question]),automatic_mode:true});let button=h.nodes['review-row-annotations'].children.find(n=>n.className.includes('review-row-label')&&n.dataset.noteId==='gray');
 assert.ok(button.classes.has('unfingered'));assert.equal(button.classes.has('uncertain'),false);assert.equal(button.classes.has('excluded'),false);assert.equal(typeof button.onclick,'function');assert.equal(button.disabled,undefined);
 assert.match(button.title,/未设指法/);assert.match(button.title,/未标或未读到/);assert.match(h.nodes['review-count'].textContent,/可处理 1 · 需检查 1/);assert.match(h.nodes['review-pending-count'].textContent,/未设 1/);
 assert.match(h.nodes['review-row-status'].textContent,/未设指法 1/);assert.equal(gray.excluded,undefined);button.onclick();assert.equal(h.controller.current().id,'gray');assert.match(h.nodes['review-finger-source'].textContent,/未标\/未读到/);
 h.nodes['review-finger-3'].onclick();assert.equal(gray.finger,3);assert.equal(gray.finger_source,'manual');assert.ok(gray.manual_fields.includes('finger'));assert.equal(Review.unfingered(gray),false);assert.equal(gray.unfingered,false);
 gray.validation_pending=false;h.controller.refreshValidation();button=h.nodes['review-row-annotations'].children.find(n=>n.className.includes('review-row-label')&&n.dataset.noteId==='gray');assert.equal(button.classes.has('unfingered'),false);assert.equal(button.classes.has('uncertain'),false);
 h.nodes['review-finger'].value='';h.nodes['review-finger'].onchange();gray.validation_pending=false;h.controller.refreshValidation();assert.equal(gray.finger,null);assert.equal(gray.unfingered,true);assert.ok(button.classes.has('unfingered'));
});

test('gray missing pitch stays a visible problem instead of being approved by missing fingering state',()=>{
 const n=note({id:'gray-pitch',finger:null,source_fingering_state:'unmarked',unfingered:true,pitch:null});const h=harness({...project([n]),automatic_mode:true});
 const label=h.nodes['review-row-annotations'].children.find(x=>x.className.includes('review-row-label'));
 assert.ok(label.classes.has('unfingered'));assert.ok(label.classes.has('attention'));assert.equal(label.classes.has('uncertain'),false);assert.match(h.nodes['review-count'].textContent,/可处理 0 · 需检查 1/);h.controller.select(n.id);assert.match(h.nodes['review-note-warning'].textContent,/音高/);
});

test('unmarked filter and right-click exclusion keep their distinct meaning and preserve times',()=>{
 const gray=note({id:'gray',finger:null,source_fingering_state:'unmarked',unfingered:true}),ready=note({id:'ready',beat:2,bbox:[160,100,170,110]}),question=note({id:'question',finger:null,source_fingering_state:'unresolved',beat:3,bbox:[220,100,230,110]});
 const h=harness({...project([gray,ready,question]),automatic_mode:true});const times=JSON.stringify(h.project.notes.map(n=>[n.id,n.pitch,n.beat,n.duration_beats]));
 h.nodes['review-filter'].value='unfingered';h.nodes['review-filter'].onchange();let labels=h.nodes['review-row-annotations'].children.filter(x=>x.className.includes('review-row-label'));
 assert.equal(labels.find(x=>x.dataset.noteId==='gray').hidden,false);assert.equal(labels.find(x=>x.dataset.noteId==='ready').hidden,true);assert.equal(labels.find(x=>x.dataset.noteId==='question').hidden,true);
 h.controller.setExcluded(gray,true);gray.validation_pending=false;h.controller.refreshValidation();assert.equal(gray.excluded,true);assert.equal(gray.finger,null);
 h.nodes['review-filter'].value='excluded';h.nodes['review-filter'].onchange();labels=h.nodes['review-row-annotations'].children.filter(x=>x.className.includes('review-row-label'));assert.equal(labels.find(x=>x.dataset.noteId==='gray').hidden,false);
 h.controller.setExcluded(gray,false);gray.validation_pending=false;h.controller.refreshValidation();assert.equal(gray.excluded,false);assert.equal(gray.excluded_manual,true);assert.ok(labels.find(x=>x.dataset.noteId==='gray').classes.has('unfingered'));
 h.nodes['review-filter'].value='pending';h.nodes['review-filter'].onchange();labels=h.nodes['review-row-annotations'].children.filter(x=>x.className.includes('review-row-label'));assert.equal(labels.find(x=>x.dataset.noteId==='gray').hidden,true);assert.equal(labels.find(x=>x.dataset.noteId==='question').hidden,false);
 assert.equal(JSON.stringify(h.project.notes.map(n=>[n.id,n.pitch,n.beat,n.duration_beats])),times);
 gray.in_export_scope=false;h.controller.refreshValidation();assert.doesNotMatch(h.nodes['review-pending-count'].textContent,/未设 1/);h.controller.select('gray');assert.match(h.nodes['review-note-warning'].textContent,/范围外/);
});


test('fixed lower dock highlights only the fields needing attention and explains the action',()=>{
 const time=note({id:'time',measure_start_beat:0,measure_beat:0,meter_beats:4,timing_estimated:false,timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。'}),
   gray=note({id:'gray',beat:1,bbox:[130,100,140,110],finger:null,source_fingering_state:'unmarked'}),
   follower=note({id:'following',beat:2,bbox:[160,100,170,110],timing_estimated:true,timing_source_id:'time'}),
   missing=note({id:'missing',beat:3,bbox:[190,100,200,110],finger:null,pitch:null,duration_beats:null,automatic_reasons:['选择指法','选择音高','选择音值']});
 const h=harness({...project([time,gray,follower,missing]),automatic_mode:true,right_hand_timing:{version:2}});
 assert.equal(h.nodes['review-editor-empty'].hidden,true);assert.equal(h.nodes['review-inspector-content'].hidden,false);assert.equal(h.controller.current().id,'time');
 h.controller.select('time',false);assert.ok(h.nodes['review-time-section'].classes.has('review-needs-action'));assert.equal(h.nodes['review-finger-section'].classes.has('review-needs-action'),false);assert.equal(h.nodes['review-duration-section'].classes.has('review-needs-action'),false);
 assert.match(h.nodes['review-edit-instruction'].textContent,/位置是软件估的/);assert.match(fs.readFileSync(path.join(__dirname,'../software.html'),'utf8'),/id="review-time-action"[^>]*>[^<]*不要猜/);
 for(const id of ['gray','following']){h.controller.select(id,false);for(const field of ['finger','duration','time'])assert.equal(h.nodes['review-'+field+'-section'].classes.has('review-needs-action'),false,id+' '+field);assert.equal(h.nodes['review-pitch-settings'].classes.has('review-needs-action'),false,id);}
 h.controller.select('missing',false);for(const field of ['finger','duration'])assert.ok(h.nodes['review-'+field+'-section'].classes.has('review-needs-action'));assert.ok(h.nodes['review-pitch-settings'].classes.has('review-needs-action'));assert.equal(h.nodes['review-pitch-settings'].hidden,false);assert.match(h.nodes['review-edit-instruction'].textContent,/手指.*音长.*音高/);
 h.nodes['review-editor-close'].onclick();assert.equal(h.nodes['review-editor-empty'].hidden,false);assert.equal(h.nodes['review-inspector-content'].hidden,true);assert.equal(h.nodes['review-inspector'].style.left,'');assert.equal(missing.finger,null);assert.equal(missing.manual_fields,undefined);
});


test('a duration-only timing root highlights its real cause instead of asking for a second onset edit',()=>{
 const n=note({id:'duration-root',duration_beats:null,measure_start_beat:0,measure_beat:0,meter_beats:4,timing_estimated:true,timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。'});
 const p={...project([n]),automatic_mode:true,right_hand_timing:{version:2,basis:{measures:[{roots:[{id:n.id,kind:'duration'}]}]}}},h=harness(p);h.controller.select(n.id,false);
 assert.ok(h.nodes['review-duration-section'].classes.has('review-needs-action'));assert.equal(h.nodes['review-time-section'].classes.has('review-needs-action'),false);assert.equal(h.nodes['review-duration-picker'].hidden,false);assert.equal(h.nodes['review-time-control'].hidden,false);assert.match(h.nodes['review-edit-instruction'].textContent,/黄色音长/);assert.doesNotMatch(h.nodes['review-edit-instruction'].textContent,/黄色的音长、开始位置/);assert.match(h.nodes['review-note-warning'].textContent,/先核对黄色音长/);
 p.right_hand_timing.basis.measures[0].roots.push({id:n.id,kind:'onset'});h.controller.select(n.id,false);h.controller.refreshValidation();assert.ok(h.nodes['review-time-section'].classes.has('review-needs-action'));
});


test('fixed dock keeps overflow and conflicting manual onset reasons instead of relabeling them as estimates',()=>{
 for(const text of ['本小节超过4拍，请核对音长和末尾休止。','同组音的手动起拍不同，已保留输入，请核对。']){
  const n=note({timing_warning:text,timing_estimated:false,timing_source_id:'one',measure_start_beat:0,measure_beat:0,meter_beats:4});const h=harness({...project([n]),automatic_mode:true,right_hand_timing:{version:2}});h.controller.select('one',false);assert.match(h.nodes['review-edit-instruction'].textContent,text.includes('超过')?/小节超过4拍/:/手动起拍不同/);assert.doesNotMatch(h.nodes['review-edit-instruction'].textContent,/是估计/);
 }
});

test('new ordinary review opens the first actual problem without changing or approving its data',()=>{
 const done=note({id:'done'}),bad=note({id:'bad',finger:null,bbox:[150,100,160,110]}),p={...project([done,bad]),automatic_mode:true},before=JSON.stringify(p),h=harness(p);
 assert.equal(h.controller.current().id,'bad');assert.equal(h.nodes['review-inspector-content'].hidden,false);assert.equal(h.nodes['review-duration-picker'].hidden,false);assert.equal(h.nodes['review-time-control'].hidden,false);assert.equal(JSON.stringify(p),before);assert.equal(h.changes,0);
 const waiting={...project([note({id:'ready'}),note({id:'later',finger:null})]),automatic_mode:true,validation_pending:true},h2=harness(waiting);assert.equal(h2.controller.current().id,'ready');waiting.validation_pending=false;h2.controller.refreshValidation();assert.equal(h2.controller.current().id,'later');
});

test('the visible next-problem button returns to earlier issues and distinguishes one remaining issue from no issue',()=>{
 const a=note({id:'a',finger:null}),b=note({id:'b',finger:null,bbox:[150,100,160,110]}),h=harness({...project([a,b]),automatic_mode:true}),button=h.nodes['review-next-problem'];
 assert.equal(button.textContent,'下一处');button.onclick();assert.equal(h.controller.current().id,'b');assert.equal(button.textContent,'回到前面待查');button.onclick();assert.equal(h.controller.current().id,'a');
 b.finger=2;h.controller.refreshValidation();assert.equal(button.textContent,'仅此处待查');assert.equal(button.disabled,true);assert.equal(button.onclick(),false);assert.equal(a.finger,null);
 a.finger=1;h.controller.refreshValidation();assert.equal(button.textContent,'已检查完');assert.equal(button.disabled,true);assert.equal(h.changes,0);
});

test('narrow screens still show the whole row in one piece (user 11-04: no tiny fragments) without changing row membership or music',()=>{
 const notes=Array.from({length:92},(_,i)=>{const x=60+Math.floor(i/4)*46,y=175+(i%4)*12;return note({id:'n'+i,bbox:[x,y,x+10,y+8],finger_bbox:[x-2,120-i%4*5,x+10,130-i%4*5],glyph_bbox:[x-14,y-30,x+16,y+12]});}),row={key:'1:1',page:1,system:1,notes,staves:[{bbox:[30,170,1160,218]}]},page={width:1200,height:450},before=JSON.stringify(row),plan=Review.rowScreenPlan(row,page,460,220),ids=[];
 assert.equal(plan.fragments.length,1);for(const f of plan.fragments){assert.ok(Math.abs(f.renderWidth-460)<1e-6);for(const n of f.notes){ids.push(n.id);for(const b of [n.bbox,n.finger_bbox,n.glyph_bbox]){assert.ok(b[0]>=f.x&&b[2]<=f.x+f.width,n.id);assert.ok(b[1]>=f.y&&b[3]<=f.y+f.height,n.id);}}for(const item of f.layout.items)assert.ok(item.width>=24);}
 assert.equal(new Set(ids).size,92);assert.equal(ids.length,92);assert.equal(JSON.stringify(row),before);
});

test('screen fragments keep every fingering under the source head instead of re-spacing a compact list',()=>{
 const notes=Array.from({length:92},(_,i)=>{const x=60+Math.floor(i/4)*46,y=175+(i%4)*12;return note({id:'n'+i,bbox:[x,y,x+10,y+8],finger_bbox:[x-2,120-i%4*5,x+10,130-i%4*5],glyph_bbox:[x-14,y-30,x+16,y+12]});});
 const row={key:'1:1',page:1,system:1,notes,staves:[{bbox:[30,170,1160,218]}]},page={width:1200,height:450};
 for(const width of [460,920,1260])for(const height of [160,220,340])for(const f of Review.rowScreenPlan(row,page,width,height).fragments){
  assert.equal(f.layout.compact,undefined);
  for(const item of f.layout.items){const expected=((item.note.bbox[0]+item.note.bbox[2])/2-f.x)*f.scale;assert.ok(Math.abs(item.anchor-expected)<1e-7);assert.ok(Math.abs(item.left+item.width/2-expected)<=(item.width>=38?1:item.width));} /* 11-05 用户：一个和弦一列；太挤时整排变窄，再挤才略微错开（不超过一个框宽） */
 }
});

test('automatic review defaults to auto-next while explicit workspace and saved opt-outs and legacy manual mode are preserved',()=>{
 const h=harness({...project([note({finger:null})]),automatic_mode:true});assert.equal(h.nodes['review-auto-next'].checked,true);
 h.nodes['review-auto-next'].checked=false;h.nodes['review-auto-next'].onchange();
 const restored={...project([note({id:'restored',finger:null})]),automatic_mode:true};h.changeProject(restored);h.controller.render();assert.equal(h.nodes['review-auto-next'].checked,false,'explicit saved off is respected');
 h.changeProject({...project([note({id:'explicit'})]),automatic_mode:true,selection:{auto_skip_processed:true}});h.controller.render();assert.equal(h.nodes['review-auto-next'].checked,true,'workspace choice wins');
 assert.equal(harness({...project([note()]),automatic_mode:true,selection:{auto_skip_processed:false}}).nodes['review-auto-next'].checked,false);
 assert.equal(harness(project([note()])).nodes['review-auto-next'].checked,false,'legacy manual fallback stays off');
});

test('the lower unwanted-note action and right click write exactly the same exclusion business fields',()=>{
 const make=()=>({...project([note({finger:null,pitch:'D4',issues:['printed_issue'],finger_source:'printed'})]),automatic_mode:true}),p1=make(),p2=make(),a=harness(p1),b=harness(p2);
 assert.equal(a.nodes['review-exclude-note'].onclick(),true);b.nodes['review-row-annotations'].children.find(e=>e.className.startsWith('review-row-label')).oncontextmenu({preventDefault(){},stopPropagation(){}});
 assert.deepEqual(JSON.parse(JSON.stringify(p1.notes)),JSON.parse(JSON.stringify(p2.notes)));assert.equal(a.changes,1);assert.equal(b.changes,1);assert.equal(p1.notes[0].pitch,'D4');assert.equal(p1.notes[0].finger,null);assert.equal(p1.notes[0].beat,0);assert.equal(p1.notes[0].duration_beats,1);assert.equal(p1.notes[0].confirmed,false);assert.equal(p1.notes[0].excluded_manual,true);
});

test('excluding the current normal note waits for current validation then advances without excluding any other note',()=>{
 const ready=note({id:'ready'}),bad=note({id:'bad',finger:null,page:2}),p={...project([ready,bad]),automatic_mode:true},h=harness(p,twoPagePreviews);h.controller.select('ready',false);h.nodes['review-exclude-note'].onclick();assert.equal(h.controller.current().id,'ready');assert.equal(h.nodes['review-inspector-content'].hidden,false);
 ready.validation_pending=false;p.validation_pending=true;h.controller.refreshValidation();assert.equal(h.controller.current().id,'ready');p.validation_pending=false;p.validation_error='检查失败';h.controller.refreshValidation();assert.equal(h.controller.current().id,'ready');p.validation_error='';h.controller.refreshValidation();assert.equal(h.controller.current().id,'bad');assert.equal(h.page,1);assert.equal(bad.excluded,undefined);assert.equal(h.nodes['review-inspector-content'].hidden,false);
});

test('the final excluded note remains in the lower editor and can be restored without a source click',()=>{
 const a=note({finger:null}),p={...project([a]),automatic_mode:true},h=harness(p);h.nodes['review-exclude-note'].onclick();assert.equal(a.excluded,true);assert.equal(h.nodes['review-exclude-note'].textContent,'恢复这个音');assert.equal(h.nodes['review-exclude-note'].disabled,true);a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,a.id);assert.equal(h.nodes['review-inspector-content'].hidden,true);assert.match(h.notice,/都看完了/);h.controller.select(a.id);assert.equal(h.nodes['review-inspector-content'].hidden,false);assert.equal(h.nodes['review-exclude-note'].disabled,false);assert.equal(h.nodes['review-exclude-note'].attrs['aria-pressed'],'true');
 h.nodes['review-exclude-note'].onclick();assert.equal(a.excluded,false);a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,a.id);assert.equal(h.nodes['review-exclude-note'].textContent,'不要这个音');assert.equal(a.finger,null);assert.equal(h.nodes['review-inspector-content'].hidden,false);
});

test('several notes can be completed only from the lower fields and incomplete notes never advance',()=>{
 const a=note({id:'a',finger:null,pitch:null,duration_beats:null}),b=note({id:'b',finger:null,page:2}),p={...project([a,b]),automatic_mode:true},h=harness(p,twoPagePreviews);
 h.nodes['review-finger-2'].onclick();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'a');h.nodes['review-pitch'].value='E4';h.nodes['review-pitch'].onchange();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'a');
 h.nodes['review-note-values'].children[2].onclick();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'b');h.nodes['review-finger-4'].onclick();b.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'b');assert.equal(h.nodes['review-next-problem'].textContent,'已检查完');assert.equal(h.nodes['review-inspector-content'].hidden,true);assert.match(h.notice,/都看完了/);
});

test('an invalid local draft blocks unwanted-note exclusion and navigation without losing the typed value',()=>{
 const a=note({id:'a',finger:null,measure_start_beat:0,measure_beat:0,meter_beats:4}),b=note({id:'b',finger:null,page:2}),p={...project([a,b]),automatic_mode:true},h=harness(p,twoPagePreviews),input=h.nodes['review-local-beat'];input.tagName='INPUT';input.value='5';input.blur=()=>{h.document.activeElement=null;};h.nodes['review-inspector'].contains=e=>e===input;h.document.activeElement=input;
 assert.equal(h.nodes['review-exclude-note'].onclick(),false);assert.equal(a.excluded,undefined);assert.equal(h.changes,0);assert.equal(input.value,'5');h.document.activeElement=null;assert.equal(h.nodes['review-exclude-note'].onclick(),false);assert.equal(h.nodes['review-next-problem'].onclick(),false);assert.equal(h.controller.current().id,'a');assert.equal(input.value,'5');
});

test('duration modifiers are local drafts until one base-value click commits the final plain dotted or triplet value',()=>{
 for(const [mode,factor] of [['plain',1],['dotted',1.5],['triplet',2/3]])for(const oldValue of [null,1,3]){
  const a=note({id:'a',duration_beats:oldValue,automatic_reasons:['核对音长']}),b=note({id:'b',finger:null,page:2}),p={...project([a,b]),automatic_mode:true},h=harness(p,twoPagePreviews),before=JSON.stringify(a);h.nodes['review-value-'+mode].onclick();assert.equal(JSON.stringify(a),before);assert.equal(h.changes,0);h.controller.refreshValidation();assert.equal(h.controller.current().id,'a');assert.match(h.nodes['review-value-caption'].textContent,/已选.*请点音长保存/);
  h.nodes['review-note-values'].children[3].onclick();assert.ok(Math.abs(a.duration_beats-.5*factor)<1e-10);assert.equal(h.changes,1);assert.equal(h.controller.current().id,'a');a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'b');assert.equal(b.duration_beats,1);
 }
});

test('pending duration mode prevents a late validation jump and never leaks to another note project or exclusion undo',()=>{
 const a=note({id:'a',finger:null}),b=note({id:'b',finger:null,page:2,pitch:'D4'}),p={...project([a,b]),automatic_mode:true},h=harness(p,twoPagePreviews);h.nodes['review-finger-2'].onclick();h.nodes['review-value-dotted'].onclick();a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'a','unfinished duration choice retains the current note');h.nodes['review-note-values'].children[3].onclick();assert.equal(a.duration_beats,.75);assert.equal(h.changes,2);a.validation_pending=false;h.controller.refreshValidation();assert.equal(h.controller.current().id,'b');
 h.nodes['review-value-triplet'].onclick();h.controller.select('a',false);assert.doesNotMatch(h.nodes['review-value-caption'].textContent,/已选/);h.nodes['review-note-values'].children[2].onclick();assert.equal(a.duration_beats,1.5,'without a pending choice retain the existing dotted mode');
 const replacement={...project([note({id:'a',duration_beats:2,finger:null})]),automatic_mode:true};h.nodes['review-value-triplet'].onclick();h.changeProject(replacement);h.controller.render();assert.doesNotMatch(h.nodes['review-value-caption'].textContent,/已选/);h.nodes['review-note-values'].children[3].onclick();assert.equal(replacement.notes[0].duration_beats,.5);
 const one=note({duration_beats:null}),oneP={...project([one]),automatic_mode:true},x=harness(oneP);x.nodes['review-value-dotted'].onclick();x.nodes['review-exclude-note'].onclick();one.validation_pending=false;x.controller.refreshValidation();x.nodes['review-exclude-note'].onclick();one.validation_pending=false;x.controller.refreshValidation();assert.doesNotMatch(x.nodes['review-value-caption'].textContent,/已选/);x.nodes['review-note-values'].children[2].onclick();assert.equal(one.duration_beats,1);
});
