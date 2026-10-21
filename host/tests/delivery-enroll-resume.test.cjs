const test=require('node:test'),assert=require('node:assert/strict');
const {enrollController,enrollFailureMessage}=require('../delivery-demo.js');
function fixture({supported=true,armed=0}={}){
 const commands=[];let phase='FAILED';
 const controller=enrollController({getState:()=>({connected:true,mode:'bridge',identity:'COM3:resume'}),send:async cmd=>{
  commands.push(cmd);
  if(cmd==='INFO')return [`OK INFO fw=PIANO_GLOVE_2 ver=2.2.4 enroll_flow=3 enroll_resume=${supported?1:0} armed=${armed} auto_active=0 sweep=0`];
  if(cmd==='ENROLL STATUS')return [`OK ENROLL STATUS active=${phase==='RECOVER_SCAN'?1:0} phase=${phase} count=5 enroll_flow=3`];
  if(cmd==='ENROLL RESUME'){phase='RECOVER_SCAN';return ['OK ENROLL RESUME active=1 phase=RECOVER_SCAN keep_wiring=1'];}
  throw Error(cmd);
 }});
 return {controller,commands};
}
test('resume preserves the attached bus and sends RESUME instead of START or RESET',async()=>{
 const {controller,commands}=fixture();const state=await controller.resume();
 assert.equal(state.phase,'RECOVER_SCAN');assert(commands.includes('ENROLL RESUME'));
 assert(!commands.some(c=>/START|RESET|SETID|MAP|MOVE|ARM/.test(c)));
});
test('resume requires current firmware support and stopped motion',async()=>{
 for(const options of [{supported:false},{armed:1}]){
  const {controller,commands}=fixture(options);await assert.rejects(controller.resume());
  assert(!commands.includes('ENROLL RESUME'));
 }
});
test('ID confirmation failure keeps wiring and points to explicit continuation',()=>{
 assert.match(enrollFailureMessage({reason:'new_id_missing',step:'verify_id',count:'5'}),/进度已保留.*继续编号/);
 assert.match(enrollFailureMessage({reason:'resume_layout_incomplete'}),/保持接线.*继续编号/);
});
