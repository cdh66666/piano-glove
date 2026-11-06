'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module');
const HERE=__dirname,HOST=path.resolve(HERE,'..'),originalTest=path.join(HOST,'tests/software-ui.test.cjs');
const software=path.join(HOST,'software.js'),live=fs.readFileSync(software,'utf8');
const selected=live;
const clone=x=>JSON.parse(JSON.stringify(x));
function harness(){
 const prefix=fs.readFileSync(originalTest,'utf8').split('\ntest(')[0],original=createRequire(originalTest);
 const localFs={...fs,readFileSync:(p,...args)=>path.resolve(p)===software?selected:fs.readFileSync(p,...args)};
 const module={exports:{}},context={require:id=>id==='node:fs'?localFs:original(id),__dirname:path.dirname(originalTest),module,console,setImmediate,setTimeout,clearTimeout,URL,URLSearchParams,Blob,Uint8Array,TextEncoder,TextDecoder,DataView,AbortController,atob,btoa};
 vm.runInNewContext(prefix+'\nmodule.exports={harness};',context);return module.exports.harness({manualTimers:true});
}
function fixture(oldCount=3,insertedCount=1){
 const note=(id,x,page=1)=>({id,page,origin:[x,100],bbox:[x-2,96,x+8,104],hand:'right',pitch:'C4',finger:1,beat:x/30-1,duration_beats:1});
 const old=Array.from({length:oldCount},(_,i)=>note('n'+(i+1),30*(i+1)));
 old[0].finger=4;old[0].beat=.25;old[0].duration_beats=1.5;old[0].tie_to=old[1].id;old[0].tie_reviewed=true;old[0].confirmed=true;
 old[0].manual_fields=['finger','beat','duration_beats','tie_to','tie_reviewed'];
 const freshNotes=[...Array.from({length:insertedCount},(_,i)=>note('',4+i*6)),...old.map((n,i)=>note('',n.origin[0]))];
 freshNotes.forEach((n,i)=>n.id='n'+(i+1));
 const prior={name:'prior',source_sha256:'a'.repeat(64),automatic_mode:true,notes:old,selection:{bpm:100}};
 const fresh={name:'fresh',source_sha256:prior.source_sha256,automatic_mode:true,notes:freshNotes,selection:{bpm:120}};
 return {prior,fresh,sourceX:old[0].origin[0],targetX:old[1].origin[0]};
}
async function merge(f){const h=harness();await h.flush();h.subject.setOriginal(f.prior);const before=JSON.stringify(f.prior);h.subject.acceptRecognized({project:f.fresh});assert.equal(JSON.stringify(f.prior),before,'the remembered review is immutable');return {h,out:h.subject.selection()};}
const at=(out,x)=>out.notes.find(n=>n.origin?.[0]===x);
function unresolved(out,f){const source=at(out,f.sourceX);assert.equal(source.tie_to,undefined);assert.equal(source.tie_reviewed,false);assert.equal(source.confirmed,false);assert.ok(out.unmatched_review_notes.some(n=>n.review_merge_issue==='manual_tie_target_unresolved'&&n.tie_to===f.prior.notes[0].tie_to));}

for(const [oldCount,insertedCount] of [[3,1],[3,4],[4,1],[4,4]])test(`${oldCount} old heads + ${insertedCount} insertions keep edits and remap the manual tie`,async()=>{
 const f=fixture(oldCount,insertedCount),{out}=await merge(f),source=at(out,f.sourceX),target=at(out,f.targetX);
 assert.equal(source.finger,4);assert.equal(source.duration_beats,1.5);assert.equal(source.beat,.25);assert.equal(source.tie_to,target.id);assert.equal(source.tie_reviewed,true);assert.equal(source.confirmed,true);
 assert.notEqual(source.tie_to,source.id);assert.equal(out.unmatched_review_notes.length,0);
 for(const n of out.notes.filter(n=>n.origin[0]<30))assert.equal(n.finger,1);
});
test('a missing fresh target does not follow the reused old ID and keeps visible evidence',async()=>{
 const f=fixture();f.fresh.notes=f.fresh.notes.filter(n=>n.origin[0]!==f.targetX);const {h,out}=await merge(f);unresolved(out,f);
 assert.match(h.nodes.report.textContent,/旧修改未能对应/);const saved=out.unmatched_review_notes.find(n=>n.review_merge_issue);
 assert.deepEqual(clone(saved.review_merge_tie_target.origin),f.prior.notes[1].origin);
});
test('two fresh targets at the old geometry stay unresolved even when an ID matches',async()=>{
 const f=fixture();const target=f.fresh.notes.find(n=>n.origin[0]===f.targetX);f.fresh.notes.push({...clone(target),id:'duplicate-target'});
 const {out}=await merge(f);unresolved(out,f);
});
test('a missing old target geometry cannot be inferred from a same ID in the fresh result',async()=>{
 const f=fixture();f.prior.notes=f.prior.notes.filter(n=>n.origin[0]!==f.targetX);const {out}=await merge(f);unresolved(out,f);
});
test('ambiguous old target IDs do not select an arbitrary target',async()=>{
 const f=fixture();f.prior.notes.push({...clone(f.prior.notes[1]),origin:[145,100]});const {out}=await merge(f);unresolved(out,f);
});
test('an ambiguous source position preserves the prior edit without changing either fresh head',async()=>{
 const f=fixture();const source=f.fresh.notes.find(n=>n.origin[0]===f.sourceX);f.fresh.notes.push({...clone(source),id:'duplicate-source'});
 const {out}=await merge(f);assert.ok(out.unmatched_review_notes.length);for(const n of out.notes.filter(n=>n.origin[0]===f.sourceX)){assert.equal(n.finger,1);assert.notEqual(n.tie_reviewed,true);}
});
test('the target page is part of geometry identity',async()=>{
 const f=fixture();f.prior.notes[1].page=2;const {out}=await merge(f);unresolved(out,f);
});
test('an old self tie is not restored as a reviewed fresh self tie',async()=>{
 const f=fixture();f.prior.notes[0].tie_to=f.prior.notes[0].id;const {out}=await merge(f);unresolved(out,f);
});
test('different source SHA does not restore any old fields or target references',async()=>{
 const f=fixture();f.fresh.source_sha256='b'.repeat(64);const {out}=await merge(f);const source=at(out,f.sourceX);assert.equal(source.finger,1);assert.notEqual(source.tie_reviewed,true);assert.equal(source.tie_to,undefined);
});
test('an explicit manual tie removal remains a removal',async()=>{
 const f=fixture();f.prior.notes[0].tie_to=null;const {out}=await merge(f);assert.equal(at(out,f.sourceX).tie_to,null);assert.equal(out.unmatched_review_notes.length,0);
});
test('legacy bbox geometry maps sources and targets without relying on IDs',async()=>{
 const f=fixture();for(const n of [...f.prior.notes,...f.fresh.notes])delete n.origin;
 const {out}=await merge(f);const source=out.notes.find(n=>n.bbox[0]===28),target=out.notes.find(n=>n.bbox[0]===58);assert.equal(source.finger,4);assert.equal(source.tie_to,target.id);
});
test('a target restored on a later refresh recovers from the stored old geometry',async()=>{
 const f=fixture(),originalFresh=clone(f.fresh);f.fresh.notes=f.fresh.notes.filter(n=>n.origin[0]!==f.targetX);const {out:first}=await merge(f);unresolved(first,f);
 const second={prior:clone(first),fresh:originalFresh,sourceX:f.sourceX,targetX:f.targetX};const {out}=await merge(second);
 assert.equal(at(out,f.sourceX).tie_to,at(out,f.targetX).id);assert.equal(at(out,f.sourceX).tie_reviewed,true);assert.equal(out.unmatched_review_notes.length,0);
});
test('a manually added source remaps its reference to a newly numbered printed target',async()=>{
 const f=fixture();const manual={...clone(f.prior.notes[0]),id:'manual-added',origin:[160,100],bbox:[158,96,168,104]};f.prior.notes[0].manual_fields=[];f.prior.notes[0].confirmed=false;delete f.prior.notes[0].tie_to;delete f.prior.notes[0].tie_reviewed;f.prior.notes.push(manual);
 const {out}=await merge(f),added=out.notes.find(n=>n.id==='manual-added');assert.equal(added.tie_to,at(out,f.targetX).id);assert.equal(added.tie_reviewed,true);
});
test('a manually added target is available before restored tie references are applied',async()=>{
 const f=fixture();const manual={...clone(f.prior.notes[1]),id:'manual-target',origin:[160,100],bbox:[158,96,168,104]};f.prior.notes.push(manual);f.prior.notes[0].tie_to=manual.id;
 const {out}=await merge(f);assert.equal(at(out,f.sourceX).tie_to,'manual-target');assert.equal(at(out,f.sourceX).tie_reviewed,true);
});
