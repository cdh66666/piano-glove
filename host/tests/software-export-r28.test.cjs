const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const filename=path.join(__dirname,'software-ui.test.cjs'),text=fs.readFileSync(filename,'utf8'),prefix=text.slice(0,text.indexOf("\ntest('desktop initializes"));
const setup=new Module(filename,module);setup.filename=filename;setup.paths=Module._nodeModulePaths(path.dirname(filename));setup._compile(prefix+'\nmodule.exports=harness;\n',filename);const harness=setup.exports;

test('adding an unfinished manual note schedules validation and exposes partial export without a failed normal export',async()=>{
 const h=harness({visualReview:true,manualTimers:true});await h.flush();const previous=h.context.fetch;
 h.context.fetch=async(url,options)=>{
  if(url!=='/api/software/check')return previous(url,options);
  const p=JSON.parse(options.body).project,missing=p.notes.filter(n=>!n.pitch||!n.finger||n.beat==null||n.duration_beats==null);
  return {ok:true,json:async()=>({ok:true,automatic:{ready:!missing.length,attention_notes:missing.length,attention_note_ids:missing.map(n=>n.id)},report:{},scope:{},notes:p.notes.map(n=>({id:n.id,automatic_ready:!missing.includes(n),automatic_reasons:missing.includes(n)?['补齐音符字段']:[],in_export_scope:true}))})};
 };
 h.subject.loadReview({name:'通用补录流程',automatic_mode:true,notes:[{id:'source',page:1,system:1,measure:1,hand:'right',pitch:'C4',finger:1,beat:0,duration_beats:1}],pages:[{page:1,width:100,height:100}],selection:{bpm:120}});
 await h.subject.checkCurrentReview();assert.equal(h.nodes['review-export-skip-pending'].hidden,true);h.timers.length=0;
 h.subject.addNote();assert.equal(h.subject.selection().validation_pending,true);
 const check=h.timers.find(t=>t.ms===150);assert.ok(check,'new manual note must queue the ordinary debounced check');await check.f();
 assert.equal(h.nodes['review-export-skip-pending'].hidden,false);assert.equal(h.nodes['review-export-skip-pending'].disabled,false);assert.match(h.nodes['review-export-skip-pending'].textContent,/预计 1/);
 const p=h.subject.selection();assert.equal(p.notes.length,2);assert.equal(p.notes[1].pitch,null);assert.notEqual(p.notes[1].excluded,true);assert.equal(p.notes[0].finger,1);assert.equal(p.notes[0].beat,0);
 assert.equal(h.sent.some(r=>r.path==='/api/software/export'),false);assert.equal(h.sent.some(r=>r.path==='/api/train'||r.path==='/api/play'),false);
});

test('normal software sends full hold despite a legacy hidden50 value without changing chosen tempo or amplitude',async()=>{
 const h=harness();await h.flush();h.nodes.hold.value='50';h.nodes.tempo.value='80';h.nodes.amplitude.value='100';await h.subject.train(1);
 const body=Object.fromEntries(new URLSearchParams(h.sent.find(r=>r.path==='/api/train').body));assert.equal(Number(body.hold),100);assert.equal(Number(body.amplitude),100);assert.equal(Number(body.tempo),80);
});

test('workspace restoration ignores legacy hold while retaining user tempo and amplitude preferences',async()=>{
 const h=harness({manualTimers:true});await h.flush();h.nodes.hold.value='100';h.nodes['hold-label'].textContent='100%';
 h.context.window.GloveWorkspace.restore({ui:{tab:'train',settings:{tempo:'75',amplitude:'80',hold:'50'}}});
 assert.equal(h.nodes.hold.value,'100');assert.equal(h.nodes['hold-label'].textContent,'100%');assert.equal(h.nodes.tempo.value,'75');assert.equal(h.nodes.amplitude.value,'80');
});
