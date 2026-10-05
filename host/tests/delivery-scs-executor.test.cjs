const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../web_piano_glove.html'),'utf8');
const start=html.indexOf('function actionKV('),end=html.indexOf("const section=document.querySelector('#p-play');",start);
const Executor=vm.runInNewContext(html.slice(start,end)+'\nStrictActionExecutor');
function fixture(profile,invalid=false,clip=false){let armed=false,clock=0;const sent=[],positions=Array(6).fill(100),range=profile==='SCS'?1023:4095;
const io={safe:async()=>{sent.push('SAFE');armed=false;},send:async cmd=>{sent.push(cmd);if(cmd==='INFO')return [`OK INFO fw=PIANO_GLOVE_2 ver=2.2.4 profile=${profile} range=${range} calibrated=1 armed=${+armed} online=6 auto_active=0 enroll_active=0 sweep=0`];if(cmd==='STATUS_ALL')return [...positions.map((pos,slot)=>clip&&slot===4?`SLOT slot=4 id=5 min=10 standby=248 max=249 pos=${pos} valid=1 online=1 press=min`:`SLOT slot=${slot} id=${slot+1} min=100 standby=100 max=800 pos=${pos} valid=1 online=1 press=max`),'OK STATUS_ALL'];if(cmd==='ARM CHECK')return [...positions.map((pos,slot)=>`ARM_CHECK_SLOT slot=${slot} id=${slot+1} ok=1 torque=0 pos=${pos} min=20 max=${range===1023?1003:4095}`),'OK ARM CHECK armed=0 read_only=1'];if(cmd==='RATE')return ['OK RATE active=0'];if(cmd==='ARM'){armed=true;return ['OK ARM armed=1'];}if(cmd==='POSALL')return ['OK POSALL '+(invalid?[1024,...positions.slice(1)]:positions).join(' ')];if(cmd.startsWith('MOVE ')){const [,id,pos]=cmd.split(' ');positions[Number(id)-1]=Number(pos);return ['OK MOVE'];}throw Error(cmd);}};
return {sent,executor:new Executor(io,{now:()=>clock,sleep:async ms=>{clock+=ms;}})};}
for(const profile of ['SCS','STS'])test(profile+' executor keeps timing and sends family speed',async()=>{const {executor,sent}=fixture(profile);await executor.run({events:[{finger:1,t_ms:0,duration_ms:160}],duration_ms:160},['latch','press','press','press','press','press']);const moves=sent.filter(c=>c.startsWith('MOVE'));assert.equal(moves.length,8);assert(moves.every(c=>c.endsWith(profile==='SCS'?' 200 30':' 1200 30')));assert.equal(sent.at(-1),'SAFE');});
test('SCS feedback above1023 aborts before MOVE and always SAFE',async()=>{const {executor,sent}=fixture('SCS',true);await assert.rejects(executor.run({events:[{finger:1,t_ms:0,duration_ms:160}],duration_ms:160},['latch','press','press','press','press','press']),/位置反馈丢失/);assert(!sent.some(c=>c.startsWith('MOVE')));assert.equal(sent.at(-1),'SAFE');});
test('small spans have proportionate arrival tolerance; wrapped intervals use circular membership',()=>{
 const a=html.indexOf('function actionKV('),b=html.indexOf('class StrictActionExecutor',a),gate=vm.runInNewContext(html.slice(a,b)+'\nactionGate');
 const info={fw:'PIANO_GLOVE_2',ver:'2.2.4',profile:'STS',range:4095,calibrated:'1',armed:'0',online:6,auto_active:'0',enroll_active:'0',sweep:'0'},roles=['latch','press','press','press','press','press'];
 const rows=Array.from({length:6},(_,slot)=>({slot,id:slot+1,min:100,max:101,standby:100,pos:100,valid:'1',online:'1',press:'max'}));
 assert.throws(()=>gate(info,rows,roles),/活动幅度不足/);
 const wrapped=rows.map(r=>({...r,min:4094,max:1,standby:4094,pos:0}));assert.throws(()=>gate(info,wrapped,roles),/跨零动作路径尚未实测/);
 assert.throws(()=>gate({...info,profile:'SCS',range:1023},rows.map(r=>({...r,min:1022,max:1,standby:1022,pos:0})),roles),/跨零动作路径尚未实测/);
});

test('stored calibration remains valid while resting fingers outside bounds request only affected repairs',()=>{
 const a=html.indexOf('function actionKV('),b=html.indexOf('class StrictActionExecutor',a),gate=vm.runInNewContext(html.slice(a,b)+'\nactionGate');
 const info={fw:'PIANO_GLOVE_2',ver:'2.2.4',profile:'SCS',range:1023,calibrated:'1',armed:'0',online:6,auto_active:'0',enroll_active:'0',sweep:'0'},roles=['latch','press','press','press','press','press'];
 const values=[[328,504,504,465,'min'],[798,885,885,845,'min'],[550,550,718,995,'max'],[750,828,914,831,'max'],[50,95,205,108,'max'],[717,717,877,708,'max']];
 const rows=values.map(([min,standby,max,pos,press],slot)=>({slot,id:slot+1,min,standby,max,pos,press,valid:'1',online:'1'}));
 assert.throws(()=>gate(info,rows,roles),e=>{assert.equal(e.code,'CAL_POSITION_OUTSIDE');assert.deepEqual(Array.from(e.repairSlots),[2]);assert.match(e.message,/食指/);assert.doesNotMatch(e.message,/小指/);assert.doesNotMatch(e.message,/校准无效/);return true;});
 assert.equal(gate(info,rows.map(r=>({...r,pos:r.standby})),roles).length,6);
 assert.throws(()=>gate(info,rows.map(r=>({...r,pos:r.standby,valid:r.slot===2?'0':'1'})),roles),/校准无效/);
});
test('ID5 imported score alternates inset endpoints26 and243 instead of midpoint standby248',async()=>{const {executor,sent}=fixture('SCS',false,true);await executor.run({events:[{finger:4,t_ms:0,duration_ms:160}],duration_ms:160},['latch','press','press','press','press','press']);assert(sent.includes('MOVE 5 26 200 30'));assert(sent.includes('MOVE 5 243 200 30'));assert(!sent.includes('MOVE 5 10 200 30'));assert.equal(sent.at(-1),'SAFE');});
