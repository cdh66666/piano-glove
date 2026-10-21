"""Native actual holding policy + compactState() serialization schema checks."""
from pathlib import Path
import json
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
compact=source[source.index('static String compactState(){'):source.index('static bool writeLimit(')]
prefix=r'''
#include "../src/library_hold.h"
#include "../src/library_pattern.h"
#include "../src/library_recovery.h"
#include "../src/library_score_clock.h"
#include <string>
#include <stdint.h>
#include <assert.h>
#include <iostream>
#include <initializer_list>
class String {
 std::string value;
public:
 String(){} String(const char*s):value(s){} String(const std::string&s):value(s){}
 String(int x):value(std::to_string(x)){} String(unsigned x):value(std::to_string(x)){}
 String(unsigned long x):value(std::to_string(x)){}
 String operator+(const String&other)const{return String(value+other.value);}
 friend String operator+(const char*a,const String&b){return String(std::string(a)+b.value);}
 String&operator+=(const String&other){value+=other.value;return *this;}
 bool operator==(const char*s)const{return value==s;}
 const char*c_str()const{return value.c_str();}
};
String escape(const String&s){return s;}
uint32_t millis(){return 1000;}uint32_t elapsed(){return 3200;}
namespace scs{enum class Family{STS,SCS};struct Profile{Family family=Family::STS;uint16_t range=4095;}pf;const Profile&profile(){return pf;}}
bool running=true,initializing=false,training=false,resistanceSupported=true,offhandTestMode=false;
bool patternRunning=false;librarypattern::Sequence patternSequence;
libraryclock::WallClock scoreClock;int scoreLimit(){return -1;}uint32_t playedEventCount=7,count=10;
void refreshIdlePositions(){}
namespace glove{struct Slot{uint16_t lo=1000,hi=2000;bool valid=true;}slots[6];const Slot&slot(int s){return slots[s];}}
bool calibrationValid(int s){return glove::slot(s).valid;}
int currentSlot=7;uint32_t duration=6000,lastStopAt=100,lastPrepareMs=200,lastPoseMs=1;
uint16_t tempo=150;uint8_t mask=9,hold=50,recoveryMask=0,movingMask=16,healthValidMask=63,positionValidMask=63;
String owner="usb",failure="none",lastStopReason="stopped";
int16_t actual[6]={2000,1800,1600,1400,1200,1000},currentRaw[6]={0,1,-2,3,4,5};
uint16_t poseTargets[6]={2100,1900,1700,1500,1300,1100},appliedLimit[6]={1000,1000,500,500,1000,500};
uint8_t volts[6]={50,50,50,50,50,50},temps[6]={32,32,32,32,32,32};
uint32_t positionSampleMs[6]={990,990,990,990,990,990},healthSampleMs[6]={800,900,500,600,700,800};
'''
harness=prefix+compact+r'''
int main(){
 for(int original:{100,500,1000})for(int hold:{0,20,50,100})for(int slot=0;slot<6;++slot){
  assert(libraryhold::limit(original,slot,false,true,hold)==original);
  assert(libraryhold::enabled(slot,false,true,hold));
  assert(libraryhold::limit(original,slot,true,false,hold)==original);
  if(slot==0)assert(libraryhold::limit(original,slot,false,false,hold)==original);
  else{int reduced=original*hold/100;assert(libraryhold::limit(original,slot,false,false,hold)==(reduced?reduced:1));assert(libraryhold::enabled(slot,false,false,hold)==(hold!=0));}
 }
 // Release in motion remains full; only verified static arrival reduces output.
 assert(libraryhold::limit(1000,4,false,true,50)==1000);
 assert(libraryhold::limit(1000,4,false,false,50)==500);
 std::cout<<compactState().c_str()<<"\n";
 scs::pf.family=scs::Family::SCS;scs::pf.range=1023;healthValidMask=0;positionValidMask=0;offhandTestMode=true;owner="wifi";
 std::cout<<compactState().c_str()<<"\n";
 patternRunning=true;patternSequence.begin(2,3,0,1000);
 std::cout<<compactState().c_str()<<"\n";
}
'''
cpp=root/'library_hold_state_generated.cpp';exe=root/'library_hold_state_generated.exe'
cpp.write_text(harness,encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
lines=subprocess.check_output([str(exe)],encoding='utf-8').splitlines();assert len(lines)==3
for index,line in enumerate(lines):
    state=json.loads(line)
    scs=index!=0
    assert state['v']==1 and state['p']==int(scs) and state['x']==int(scs)
    assert state['o']==(2 if scs else 1) and state['a']==1 and state['i']==0
    assert state['pv']==(0 if index else 63) and state['mm']==16
    for flag in ['a','i','r','x','p','pf','cp']:
        assert type(state[flag]) is int and state[flag] in [0,1]
    assert state['m']==(2 if index==2 else 0)
    assert state['er']==(1023 if scs else 4095)
    assert state['cp']==0 and state['cl']==-1 and state['si']==7 and state['sn']==10
    assert state['pt']==(2 if index==2 else 0) and state['ps']==0
    assert state['pc']==(12 if index==2 else 0) and state['pf']==int(index==2)
    assert len(state['b'])==6 and all(row==[1000,2000,150,1] for row in state['b'])
    assert len(state['f'])==6
    for row in state['f']:
        assert len(row)==9 and all(type(value) is int for value in row)
        assert row[2]==10 and row[-1]==(0 if index else 1)
    assert len(line.encode())<850
print('PASS actual holding policy: full return movement before static 50%/off; compact C++ schema two models + pattern mode, calibration bounds, nine-column frame, validity/ages; bytes='+','.join(str(len(line.encode())) for line in lines))
