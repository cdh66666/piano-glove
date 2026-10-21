"""Actual expanded C++ hotspot state vs compact C++/real bridge decoder.

The same payloads are consumed by the real JS DeviceClock. No hardware I/O.
"""
from pathlib import Path
import ast
import json
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
repo=root.parent.parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
expanded=source[source.index('static String state(){'):source.index('static String compactState(){')]
compact=source[source.index('static String compactState(){'):source.index('static bool writeLimit(')]
hold_tree=ast.parse((root/'test_library_hold_state.py').read_text(encoding='utf-8'))
prefix=ast.literal_eval(next(node.value for node in hold_tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='prefix' for target in node.targets)))
prefix='#include <algorithm>\nusing std::min;using std::max;\n'+prefix
prefix=prefix.replace('uint32_t elapsed(){return 3200;}','uint32_t mockElapsed=3200;uint32_t elapsed(){return mockElapsed;}')
cpp=root/'library_public_state_generated.cpp';exe=root/'library_public_state_generated.exe'
cpp.write_text(prefix+expanded+compact+r'''
void snapshot(){std::cout<<state().c_str()<<"\n"<<compactState().c_str()<<"\n";}
int main(){
 snapshot();
 scs::pf.family=scs::Family::SCS;scs::pf.range=1023;healthValidMask=0;positionValidMask=0;offhandTestMode=true;owner="wifi";
 for(int i=0;i<6;++i){glove::slots[i].lo=100;glove::slots[i].hi=800;actual[i]=400+i;poseTargets[i]=450+i;}
 snapshot();
 positionValidMask=63;training=true;patternRunning=true;tempo=0;patternSequence.begin(2,3,0,1000);snapshot();
 patternRunning=false;training=false;tempo=200;scoreClock.start(0);scoreClock.desired(1600,200);snapshot();
 running=false;failure="completed";playedEventCount=count;mockElapsed=0;snapshot();
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
values=[json.loads(line) for line in subprocess.check_output([str(exe)],text=True).splitlines()]
assert len(values)==10

# Compile only the real static decoder method, avoiding bridge module startup
# and unrelated optional desktop dependencies.
bridge_tree=ast.parse((repo/'host/bridge.py').read_text(encoding='utf-8'))
console=next(node for node in bridge_tree.body if isinstance(node,ast.ClassDef) and node.name=='SoftwareConsole')
decoder=next(node for node in console.body if isinstance(node,ast.FunctionDef) and node.name=='expand_state')
decoder.decorator_list=[]
namespace={}
exec(compile(ast.fix_missing_locations(ast.Module(body=[decoder],type_ignores=[])),str(repo/'host/bridge.py'),'exec'),namespace)
fields=['score_clock','calibration_advisory','active','initializing','mode','slot','elapsed_ms','duration_ms','tempo','mask','hold','hold_variable','owner','error','device_ms','moving_mask','pattern','pattern_step','pattern_total','fastest','clock_paused','clock_limit_ms','encoder_range','feedback','score_index','score_total']
states=[]
for index in range(0,10,2):
    hotspot=values[index];serial_public=namespace['expand_state'](values[index+1])
    assert hotspot['score_clock']=='continuous-v1' and hotspot['calibration_advisory'] is True
    assert hotspot['clock_paused'] is False and hotspot['clock_limit_ms'] is None
    assert 'a' not in hotspot and 'v' not in hotspot
    for key in fields:
        assert key in hotspot and hotspot[key]==serial_public[key],(index,key,hotspot.get(key),serial_public.get(key))
    assert type(hotspot['active']) is bool and type(hotspot['elapsed_ms']) is int and type(hotspot['tempo']) is int
    assert len(hotspot['feedback'])==6
    for axis in hotspot['feedback']:
        assert type(axis['position_valid']) is bool and type(axis['sample_age_ms']) is int
    states.append(hotspot)

# Exercise the actual JS clock with the actual expanded payload shape.
node=shutil.which('node');assert node
clock_test=r'''
const assert=require('node:assert/strict'),{DeviceClock}=require(process.argv[1]);
const states=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
for(const s of states){const c=new DeviceClock();c.sync(s,90,110);assert.equal(c.rate,(Number(s.tempo)||100)/100);assert.equal(c.paused,!s.active||s.initializing||s.clock_paused);if(c.paused)assert.equal(c.position(150),s.elapsed_ms);else assert.equal(c.position(150),s.elapsed_ms+50*c.rate);}
assert.equal(states[4].score_index,states[4].score_total);assert.equal(states[4].error,'completed');
'''
subprocess.run([node,'-e',clock_test,str(repo/'host/software-audio.js')],input=json.dumps(states),text=True,check=True)
print('PASS actual hotspot expanded state == actual USB compact/bridge decode: boolean activity, clock/tempo/masks/events, six calibrated feedback objects with exact validity/ages; STS/SC09, fastest pattern, continuous/advisory capabilities, completed; actual JS DeviceClock consumes all payloads')
