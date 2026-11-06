const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const host=path.resolve(__dirname,'..'),filename=path.join(host,'tests/software-ui.test.cjs'),text=fs.readFileSync(filename,'utf8'),prefix=text.slice(0,text.indexOf("\ntest('desktop initializes"));
const setup=new Module(filename,module);setup.filename=filename;setup.paths=Module._nodeModulePaths(path.dirname(filename));setup._compile(prefix+'\nmodule.exports=harness;\n',filename);const harness=setup.exports;
function original(){return {name:'independent native UI check',source_sha256:'a'.repeat(64),automatic_mode:true,selection:{},notes:[{id:'a',hand:'right',pitch:'C4',finger:2,beat:0,duration_beats:1,manual_fields:['finger']}]};}
function expose(h,check){h.context.NativeApp=h.context.window.NativeApp={checkProject:check,ready:Promise.resolve({save_workspace:async()=>({saved:true})})};}

test('software native path does not stringify the project and merges only validation/timing fields',async()=>{
 const h=harness({manualTimers:true});await h.flush();h.subject.loadReview(original());let received,options;
 expose(h,async(p,o)=>{received=p;options=o;return {ok:true,automatic:{ready:true},report:{ready:true},right_hand_timing:{version:1},notes:[{id:'a',automatic_ready:true,automatic_reasons:[],finger:5,pitch:'G9',duration_beats:99,beat:2,measure_beat:1}]}});
 h.context.__producerStringifies=0;vm.runInContext('const savedStringify=JSON.stringify;JSON.stringify=(...args)=>{globalThis.__producerStringifies++;return savedStringify(...args)};',h.context);
 assert.equal(await h.subject.checkCurrentReview(),true);assert.equal(received.page_previews,undefined);assert.equal(received.notes,h.subject.selection().notes);assert.equal(h.context.__producerStringifies,0);
 const note=h.subject.selection().notes[0];assert.equal(note.finger,2);assert.equal(note.pitch,'C4');assert.equal(note.duration_beats,1);assert.equal(note.beat,2);assert.equal(note.measure_beat,1);assert.ok(options.signal);assert.ok(options.headers['X-Piano-Controller']);assert.equal(h.sent.some(c=>c.path==='/api/software/check'),false);
});

test('native late result cannot undo a later edit or a newly opened source',async()=>{
 const h=harness({manualTimers:true});await h.flush();h.subject.loadReview(original());const requests=[];
 expose(h,(p,o)=>new Promise(resolve=>requests.push({snapshot:JSON.parse(JSON.stringify(p)),resolve})));
 const first=h.subject.checkCurrentReview();h.subject.selection().notes[0].finger=3;h.subject.reviewChanged();const second=h.subject.checkCurrentReview();
 assert.equal(requests[0].snapshot.notes[0].finger,2);assert.equal(requests[1].snapshot.notes[0].finger,3);
 requests[1].resolve({ok:true,automatic:{ready:true},notes:[{id:'a',automatic_ready:true,automatic_reasons:[]}]});await second;
 requests[0].resolve({ok:true,automatic:{ready:false},notes:[{id:'a',automatic_ready:false,automatic_reasons:['old']}]});assert.equal(await first,false);assert.equal(h.subject.selection().notes[0].finger,3);assert.equal(h.subject.selection().notes[0].automatic_ready,true);
 const third=h.subject.checkCurrentReview();h.subject.loadReview({...original(),source_sha256:'b'.repeat(64),notes:[{id:'b',hand:'right',pitch:'G4',finger:4,beat:3,duration_beats:1}]});
 requests[2].resolve({ok:true,automatic:{ready:false},notes:[{id:'a',automatic_ready:false}]});assert.equal(await third,false);assert.equal(h.subject.selection().source_sha256,'b'.repeat(64));assert.equal(h.subject.selection().notes[0].id,'b');
});

test('native validation keeps the same 90-second timeout and clears it after abort',async()=>{
 const h=harness({manualTimers:true});await h.flush();h.subject.loadReview(original());let expire,cleared=false,signal;
 const priorTimeout=h.context.setTimeout,priorClear=h.context.clearTimeout;
 h.context.setTimeout=(fn,ms)=>{if(ms===90000){expire=fn;return 'native-validation-timeout'}return priorTimeout(fn,ms)};
 h.context.clearTimeout=id=>{if(id==='native-validation-timeout')cleared=true;else priorClear(id)};
 expose(h,(p,o)=>new Promise((resolve,reject)=>{signal=o.signal;signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true})}));
 const checking=h.subject.checkCurrentReview();assert.ok(expire);expire();assert.equal(await checking,false);assert.equal(signal.aborted,true);assert.equal(cleared,true);assert.equal(h.subject.selection().validation_error,'检查暂未完成，导出时会再次校验');assert.equal(h.subject.selection().notes[0].finger,2);
});

test('native shared validator failure leaves source values and an explicit retry state',async()=>{
 const h=harness({manualTimers:true});await h.flush();h.subject.loadReview(original());expose(h,async()=>{throw Error('shared failure')});assert.equal(await h.subject.checkCurrentReview(),false);assert.equal(h.subject.selection().validation_pending,false);assert.equal(h.subject.selection().validation_error,'检查暂未完成，导出时会再次校验');assert.equal(h.subject.selection().notes[0].finger,2);assert.equal(h.sent.some(c=>c.path==='/api/train'||c.path==='/api/play'),false);
});
