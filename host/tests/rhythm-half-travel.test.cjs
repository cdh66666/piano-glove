const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../web_piano_glove.html'),'utf8'),a=html.indexOf('function actionKV('),b=html.indexOf("const section=document.querySelector('#p-play');",a),Executor=vm.runInNewContext(html.slice(a,b)+'\nStrictActionExecutor',{setTimeout,clearTimeout});
const roles=['latch','press','press','press','press','press'];
function setup({profile='SCS',benchFeedback=false,keep=false,travelMs=0,slow=false,escape=false,rateValid=true,noisy=false,stall=false,latency=0}={}){
 let clock=0,armed=false,benchActive=false,benchDeadline=0,rate=false,depth=0,polls=0;const sent=[],progress=[],pos=Array(6).fill(100),goals=Array(6).fill(100),origin=Array(6).fill(100),goalAt=Array(6).fill(0);
 const move=(i,target)=>{if(stall)return;origin[i]=pos[i];goalAt[i]=clock;goals[i]=target;};
 const io={safe:async()=>{sent.push('SAFE');armed=false;benchActive=false;},send:async c=>{sent.push(c);clock+=latency;
 if(travelMs)for(let i=0;i<6;i++)pos[i]=Math.round(origin[i]+(goals[i]-origin[i])*Math.min(1,(clock-goalAt[i])/travelMs));
 if(benchFeedback&&benchActive&&clock>=benchDeadline){armed=false;benchActive=false;}
 if(c==='INFO')return[`OK INFO fw=PIANO_GLOVE_2 ver=2.2.4 profile=${profile} range=${profile==='SCS'?1023:4095} calibrated=1 armed=${+armed} online=6 auto_active=0 enroll_active=0 sweep=0 bench_group=1 bench_feedback=${+benchFeedback} bench_keep=${+keep}`];
 if(c==='STATUS_ALL')return [...pos.map((p,s)=>`SLOT slot=${s} id=${s+1} min=100 max=${profile==='STS'?600:350} standby=100 pos=${p} online=1 valid=1 press=max`),'OK STATUS_ALL'];
 if(c==='ARM CHECK')return [...pos.map((p,s)=>`ARM_CHECK_SLOT slot=${s} id=${s+1} ok=1 torque=0 pos=${p} min=20 max=1003`),'OK ARM CHECK'];
 if(c==='ARM'){armed=true;return['OK ARM armed=1'];}
 if(c==='POSALL'){polls++;if(!travelMs)for(let i=0;i<6;i++)pos[i]=slow?pos[i]+Math.sign(goals[i]-pos[i])*Math.min(5,Math.abs(goals[i]-pos[i])):goals[i];if(noisy&&!armed)pos[2]=100+(polls%2)*20;return ['OK POSALL '+(escape?[999,...pos.slice(1)]:pos).join(' ')+(benchFeedback?` armed=${+armed} bench_active=${+benchActive}`:'')];}
 if(c==='BENCH KEEP'){if(!armed||!benchActive)return ['ERR BENCH KEEP inactive_or_expired'];benchDeadline=clock+1200;return ['OK BENCH KEEP active=1 armed=1 cutoff_ms=1200'];}
 if(c.startsWith('BENCH GROUP ')){const x=c.split(' '),mask=parseInt(x[2]);for(let id=1;id<=6;id++)if(mask&(1<<(id-1)))move(id-1,+x[id+2]);benchActive=true;benchDeadline=clock+1200;return [`OK BENCH GROUP mask=${x[2]} speed=${x[9]} readback=1 count=${Array.from({length:6},(_,i)=>!!(mask&(1<<i))).filter(Boolean).length} cutoff_ms=1200`+(benchFeedback?' armed=1 bench_active=1':'')];}
 if(c.startsWith('MOVE ')||c.startsWith('BENCH MOVE ')){const [,id,p]=(c.startsWith('BENCH ')?c.slice(6):c).split(' ');move(+id-1,+p);if(c.startsWith('BENCH ')){benchActive=true;benchDeadline=clock+1200;}return['OK MOVE'];}
 if(c.startsWith('RATE ')){rate=true;depth=+c.split(' ')[4];return['OK RATE_START'];}
 if(c==='RATE'){if(rate){rate=false;return[`OK RATE active=0 done=3/3 half_ms=50 full_ms=100 hz=${depth/10} lost=0 valid=${+rateValid}`];}return['OK RATE active=0 done=0/0'];}throw Error(c);}};
 return {io,sent,progress,executor:new Executor(io,{now:()=>clock,sleep:async m=>{clock+=m},progress:p=>progress.push(p)})};}

function stsSetup({travelMs=0,stall=false,missingKeep=false,released=false}={}){
 const f=setup({profile:'STS',benchFeedback:true,travelMs,stall,latency:5}),base=f.io.send;
 f.io.send=async cmd=>{if(cmd==='BENCH KEEP'){f.sent.push(cmd);if(released)return ['OK BENCH KEEP active=0 armed=0'];await base('BENCH GROUP 0x0 100 100 100 100 100 100 200');return ['OK BENCH KEEP active=1 armed=1 cutoff_ms=1200'];}const lines=await base(cmd);if(cmd==='INFO')return lines.map(l=>l+' bench_sts=1 bench_fullstroke=1 motion_speed_unit=counts_per_s bench_speed_max=8000 bench_default_speed=1000 bench_keep='+Number(!missingKeep));if(cmd.startsWith('BENCH GROUP '))return lines.map(l=>l+' actual_speed='+cmd.split(' ').at(-1));if(cmd.startsWith('BENCH MOVE '))return ['OK BENCH MOVE actual_speed='+cmd.split(' ').at(-1)+' readback=1 armed=1 bench_active=1'];return lines;};return f;
}

function halfFixture(profile, fraction, fault='') {
 const f=profile==='STS'?stsSetup():setup({benchFeedback:true,latency:5}),send=f.io.send;
 let snapshot=Array(6).fill(100),song=false,commands=0;
 f.io.send=async cmd=>{
   const lines=await send(cmd);
   if(cmd.startsWith('BENCH GROUP ')&&!cmd.startsWith('BENCH GROUP 0x3f ')){
     const x=cmd.split(' '),mask=parseInt(x[2]);song=true;commands++;
     snapshot=snapshot.map((p,i)=>mask&(1<<i)?p+Math.sign(+x[i+3]-p)*Math.ceil(Math.abs(+x[i+3]-p)*(fault==='stall-return'&&commands>1?0:fraction)):p);
   }
   if(cmd==='POSALL'){
     if(!song)snapshot=lines[0].split(/\s+/).slice(2,8).map(Number);
     if(song){const p=[...snapshot];if(fault==='missing')p[1]=-1;if(fault==='escape')p[1]=999;return ['OK POSALL '+p.join(' ')+' armed=1 bench_active=1'];}
   }
   return lines;
 };
 return f;
}
const plan={rhythmDemo:true,quickDemo:true,fullStroke:true,benchQuick:true,holdThumbSide:true,duration_ms:800,events:[{slot:1,t_ms:0,duration_ms:400,amplitude:1}]};
for(const profile of ['SCS','STS']){
 test(profile+' song accepts half of actual press and release travel, then SAFE without strict final reach',async()=>{
  const f=halfFixture(profile,.5),r=await f.executor.run(plan,roles,{internalSlots:true});
  assert(r.completed);assert.equal(r.minimumTravelFraction,.5);assert.equal(f.sent.at(-1),'SAFE');
  assert.equal(f.sent.filter(c=>c.startsWith('BENCH GROUP 0x3f ')).length,1);
  assert.equal(f.sent.filter(c=>c.startsWith('BENCH GROUP 0x2 ')).length,2);
 });
 for(const [fraction,fault,pattern]of [[.49,'',/上一动作未到位/],[0,'',/上一动作未到位/],[.5,'stall-return',/节奏动作未到位/],[.5,'missing',/反馈丢失/],[.5,'escape',/校准范围/]]){
  test(profile+' song rejects '+fraction+' '+fault,async()=>{const f=halfFixture(profile,fraction,fault);await assert.rejects(f.executor.run(plan,roles,{internalSlots:true}),pattern);assert.equal(f.sent.at(-1),'SAFE');});
 }
 test(profile+' speed measurement retains strict endpoint tolerance',async()=>{const f=halfFixture(profile,.5);await assert.rejects(f.executor.runSpeedTest({},roles),/未到位/);assert.equal(f.sent.at(-1),'SAFE');});
}

for(const profile of ['SCS','STS'])test(profile+' all five final releases accept partial travel without midpoint or another motion command',async()=>{
 const f=halfFixture(profile,.5),events=Array.from({length:5},(_,i)=>({slot:i+1,t_ms:0,duration_ms:400,amplitude:1}));
 const r=await f.executor.run({...plan,events},roles,{internalSlots:true});assert(r.completed);
 const commands=f.sent.filter(c=>c.startsWith('BENCH GROUP '));assert.equal(commands.length,3);
 const lift=profile==='SCS'?106:125,press=profile==='SCS'?344:575;
 assert.equal(parseInt(commands[1].split(' ')[2]),0x3e);assert.equal(parseInt(commands[2].split(' ')[2]),0x3e);
 assert.deepEqual(commands[1].split(' ').slice(4,9).map(Number),Array(5).fill(press));
 assert.deepEqual(commands[2].split(' ').slice(4,9).map(Number),Array(5).fill(lift));
 const firstSafe=f.sent.indexOf('SAFE');assert.equal(f.sent[firstSafe-1],'POSALL');assert(f.sent.slice(firstSafe).every(c=>c==='SAFE'));
});

for(const profile of ['SCS','STS'])test(profile+' partial final release waits for fresh stable frames without more targets',async()=>{
 const f=halfFixture(profile,.5),r=await f.executor.run(plan,roles,{internalSlots:true});
 assert(r.settled);assert(r.settle_elapsed_ms>=40&&r.settle_elapsed_ms<=200);assert(f.progress.filter(p=>p.settling).length>=2);
 assert.equal(f.sent.filter(c=>c.startsWith('BENCH GROUP ')).length,3);
});
test('final settling stops on lost fresh feedback',async()=>{
 const f=halfFixture('STS',.5),send=f.io.send;let reads=0;
 f.io.send=async cmd=>{const lines=await send(cmd);if(cmd==='POSALL'&&f.sent.filter(c=>c.startsWith('BENCH GROUP 0x2 ')).length===2&&++reads>=2)return ['OK POSALL -1 -1 -1 -1 -1 -1 armed=1 bench_active=1'];return lines;};
 await assert.rejects(f.executor.run(plan,roles,{internalSlots:true}),/反馈丢失/);assert.equal(f.sent.at(-1),'SAFE');
});
test('final settling time is bounded even while feedback keeps moving',async()=>{
 const f=halfFixture('SCS',.5),send=f.io.send;let reads=0;
 f.io.send=async cmd=>{const lines=await send(cmd);if(cmd==='POSALL'&&f.sent.filter(c=>c.startsWith('BENCH GROUP 0x2 ')).length===2&&++reads>=2)return ['OK POSALL 106 '+(reads%2?200:240)+' 106 106 106 106 armed=1 bench_active=1'];return lines;};
 const r=await f.executor.run(plan,roles,{internalSlots:true});assert(!r.settled);assert(r.settle_elapsed_ms<=205);assert.equal(f.sent.at(-1),'SAFE');assert.equal(f.sent.filter(c=>c.startsWith('BENCH GROUP ')).length,3);
});
