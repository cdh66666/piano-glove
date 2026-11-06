const test=require('node:test'),assert=require('node:assert/strict');
const {assetPath,assetLoader,collectInputs,restoreInputs,leaveDebug}=require('../desktop-debug.js');

test('debug image paths accept bundled excerpts and reject traversal or remote images',()=>{
 assert.equal(assetPath('assets/score-excerpts/polka.png'),'/assets/score-excerpts/polka.png');
 assert.equal(assetPath('/assets/score-excerpts/pumpkin-boogie.png?v=2'),'/assets/score-excerpts/pumpkin-boogie.png');
 for(const path of ['https://example.com/polka.png','assets/../polka.png','assets/score-excerpts/../../x.png','file:///native/polka.png','blob:preview','data:image/png;base64,a'])assert.equal(assetPath(path),null);
});
test('leaving idle debug goes straight to the app without device writes',async()=>{
 const calls=[];await leaveDebug({deliveryDemoBusy:()=>false,deliveryDemoStop:async()=>{throw Error('unexpected stop');}},async page=>calls.push(page));assert.deepEqual(calls,['software']);
});
test('returning during a debug run cancels it before changing page',async()=>{
 const calls=[];await leaveDebug({deliveryDemoBusy:()=>true,deliveryDemoStop:async()=>calls.push('stop')},async page=>calls.push(page));assert.deepEqual(calls,['stop','software']);
});
test('failed debug stop stays visible instead of pretending the run ended',async()=>{
 let changed=false;await assert.rejects(leaveDebug({deliveryDemoBusy:()=>true,deliveryDemoStop:async()=>{throw Error('stop failed');}},async()=>changed=true),/stop failed/);assert.equal(changed,false);
});
test('native excerpt loading uses the five-argument in-process GET and caches identical requests',async()=>{
 const requests=[],created=[];let release;
 const load=assetLoader(Promise.resolve({request(...args){requests.push(args);return new Promise(resolve=>release=resolve);}}),base64=>{created.push(base64);return 'blob:score';});
 const first=load('assets/score-excerpts/polka.png'),second=load('/assets/score-excerpts/polka.png');await Promise.resolve();assert.equal(requests.length,1);assert.deepEqual(requests[0],['/assets/score-excerpts/polka.png','GET',null,false,{}]);
 release({status:200,binary:true,body:'iVBORw0KGgo-real-png'});assert.equal(await first,'blob:score');assert.equal(await second,'blob:score');assert.equal(await load('assets/score-excerpts/polka.png'),'blob:score');assert.equal(created.length,1);
});
test('a failed image request is reported and a later selection can retry',async()=>{
 let requests=0;const load=assetLoader(Promise.resolve({async request(){requests++;return requests===1?{status:404,binary:false,body:'missing'}:{status:200,binary:true,body:'iVBORw0KGgo-valid'};}}),()=> 'blob:restored');
 await assert.rejects(load('assets/score-excerpts/arabesque.png'),/未能读取/);assert.equal(await load('assets/score-excerpts/arabesque.png'),'blob:restored');assert.equal(requests,2);
});
test('debug preferences restore input choices without firing hardware-affecting handlers',()=>{
 const nodes={speed:{id:'speed',value:'100',type:'range',onchange(){throw Error('must not dispatch');}},speedLabel:{},fDepth:{id:'fDepth',value:'100',type:'range'},fDepthLabel:{},demoOne:{id:'demoOne',tagName:'SELECT',value:'1',options:[{value:'1'},{value:'3'}]},rawCmd:{id:'rawCmd',type:'text',value:''},closedLoop:{id:'closedLoop',type:'checkbox',checked:true},dangerousMotorTarget:{id:'dangerousMotorTarget',value:'2000'}};
 const choices=[{value:'1',checked:true},{value:'3',checked:true}],document={getElementById:id=>nodes[id],querySelectorAll:()=>choices};
 restoreInputs(document,{speed:'155',fDepth:'75',demoOne:'3',rawCmd:'INFO',closedLoop:false,dangerousMotorTarget:'4000',combination:[{value:'3',checked:false}]});
 assert.equal(nodes.speed.value,'155');assert.equal(nodes.speedLabel.textContent,'155%');assert.equal(nodes.fDepthLabel.textContent,'75%');assert.equal(nodes.demoOne.value,'3');assert.equal(nodes.closedLoop.checked,false);assert.equal(nodes.rawCmd.value,'INFO');assert.equal(nodes.dangerousMotorTarget.value,'2000');assert.equal(choices[1].checked,false);
 const saved=collectInputs(document);assert.equal(saved.speed,'155');assert.equal(saved.closedLoop,false);assert.equal(saved.dangerousMotorTarget,undefined);
 restoreInputs(document,{demoOne:'9',closedLoop:'true'});assert.equal(nodes.demoOne.value,'3');assert.equal(nodes.closedLoop.checked,false);
});
