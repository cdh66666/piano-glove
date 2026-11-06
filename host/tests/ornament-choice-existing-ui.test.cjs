const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module');
const HOST=path.resolve(__dirname,'..');
function harness(project){const file=path.join(HOST,'tests/software-review.test.cjs'),source=fs.readFileSync(file,'utf8'),prefix=source.slice(0,source.indexOf('\ntest(')),body=source.slice(source.indexOf('class Node{'),source.indexOf('\nconst project=notes=>')),originalRequire=createRequire(file),candidatePath=path.join(HOST,'software-review.js'),candidate=require(candidatePath),localFs={...fs,readFileSync:(file,...args)=>fs.readFileSync(path.resolve(file)===path.join(HOST,'software-review.js')?candidatePath:file,...args)};const module={exports:{}},context={module,require:id=>id==='node:fs'?localFs:id==='../software-review.js'?candidate:originalRequire(id),__dirname:path.dirname(file),console,setTimeout,clearTimeout};vm.runInNewContext(prefix+body+'\nmodule.exports={harness};',context);return module.exports.harness(project);}
function find(root,id){if(root?.id===id)return root;for(const n of root?.children||[]){const r=find(n,id);if(r)return r;}return null;}
function checkedHarness(data){const p=data.project,n=p.notes[0];
 Object.assign(n,data.check.notes[0],{bbox:[100,100,110,110]});Object.assign(p,{automatic_mode:true,performance:data.check.performance,pages:[{page:1,width:600,height:800}],automatic:data.check.automatic});
 return {p,n,h:harness(p)};}
test('candidate choice appears in existing editor and writes only practice override',()=>{
 const data=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/ornament_conflict_r23.json'),'utf8')),{p,n,h}=checkedHarness(data),source=JSON.stringify(n.performance_marks),select=find(h.nodes['review-duration-section'],'review-performance-interpretation');
 assert.equal(select.hidden,false);assert.equal(select.disabled,false);
 assert.ok(select.children.some(o=>o.value==='trill'));assert.ok(select.children.some(o=>o.value==='mordent_lower'));
 select.value='mordent_lower';select.onchange();
 assert.equal(n.performance_override.kind,'mordent_lower');assert.equal(n.performance_override.reviewed,false);
 assert.equal(JSON.stringify(n.performance_marks),source);assert.equal(n.pitch,'C4');assert.equal(n.finger,1);assert.equal(n.duration_beats,1);
});
test('resolved lower mordent can switch back to trill without restoring or changing raw marks',()=>{
 const data=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/ornament_conflict_r23.json'),'utf8')).choices.mordent_lower,{n,h}=checkedHarness(data),select=find(h.nodes['review-duration-section'],'review-performance-interpretation'),source=JSON.stringify(n.performance_marks);
 assert.equal(data.check.automatic.ready,true);assert.equal(select.hidden,false);select.value='trill';select.onchange();
 assert.equal(n.performance_override.kind,'trill');assert.equal(JSON.stringify(n.performance_marks),source);
});
