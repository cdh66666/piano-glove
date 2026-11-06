"""Execute device-local pattern timing and actual idle read code without hardware."""
from pathlib import Path
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
idle=source[source.index('static void refreshIdlePositions(){'):source.index('static bool calibrationValid(')]
phase_ready=source[source.index('static bool patternPreparationReady(){'):source.index('static String state(){')]
cpp=root/'library_pattern_generated.cpp';exe=root/'library_pattern_generated.exe'
cpp.write_text(r'''
#include "../src/library_pattern.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <initializer_list>
#include <stdlib.h>
uint32_t now=1000;uint32_t millis(){return now;}
bool running=false,exclusiveBusy=false;uint8_t positionValidMask=0;
int16_t actual[6]={};uint32_t positionSampleMs[6]={};
int16_t actualSpeed[6]={};uint8_t actualMoving[6]={255,255,255,255,255,255};uint32_t axisPoseAt[6]={};
uint8_t patternChangedMask=0;int16_t poseFrom[6]={};uint16_t poseTargets[6]={};
uint16_t phaseDeadband[6]={6,6,6,6,6,6};
namespace glove{
struct Slot{uint8_t id=0;int last=-1;}slots[6];Slot&slot(int s){return slots[s];}
bool busy=false;bool autoActive(){return busy;}bool mountActive(){return false;}bool benchActive(){return false;}bool rateActive(){return false;}bool sweepActive(){return false;}
}
namespace scs{
enum class Family{STS,SCS};constexpr int BROADCAST_ID=254;struct Profile{int range=4095;Family family=Family::STS;}pf;const Profile&profile(){return pf;}
int calls=0,readCount=6,error=0;uint16_t samples[6]={501,502,503,504,505,506};
int positionReadBudget(int){return 20;}int lastError(){return error;}
int syncReadPos(const uint8_t*,int,uint16_t*out,int,int16_t*velocity=nullptr,uint8_t*moving=nullptr){++calls;for(int s=0;s<6;++s){out[s]=samples[s];if(velocity)velocity[s]=0;if(moving)moving[s]=0;}return readCount;}
}
''' + idle + phase_ready + r'''
int main(){
 librarypattern::Sequence sequence;
 for(int rate:{0,50,100,200,1000}){
  assert(sequence.begin(0,2,rate,1000));assert(sequence.total==20);
  for(int step=0;step<20;++step){
   assert(sequence.step==step);assert(sequence.mask()==(step%2?0:1<<(step/2%5)));
   assert(sequence.due(sequence.phaseStarted+sequence.dwell()+100,false)==(rate!=0));
   assert(sequence.due(sequence.phaseStarted+sequence.dwell(),true));
   assert(!sequence.expired(sequence.phaseStarted+1800,false));assert(!sequence.expired(sequence.phaseStarted+1801,false));
   assert(sequence.advance(sequence.phaseStarted+sequence.dwell())==(step<19));
  }
 }
 assert(sequence.begin(2,1,0,0xfffffffeu));assert(sequence.fastest());
 assert(sequence.due(3,true));assert(!sequence.due(3,false));
 assert(sequence.mask()==21);assert(sequence.advance(3));assert(sequence.mask()==0);
 assert(sequence.advance(5));assert(sequence.mask()==10);
 assert(sequence.begin(1,1,1000,0));assert(sequence.mask()==3);assert(sequence.dwell()==35);
 assert(sequence.advance(35));assert(sequence.dwell()==18);
 for(int rate:{-1,1,49,1001})assert(!sequence.begin(0,1,rate,0));
 assert(!sequence.begin(-1,1,100,0));assert(!sequence.begin(3,1,100,0));
 assert(!sequence.begin(0,0,100,0));assert(!sequence.begin(0,21,100,0));
 assert(librarypattern::transitionReady(true,true,1000,114));
 assert(!librarypattern::transitionReady(true,false,1000,114));
 assert(librarypattern::transitionReady(false,false,1000,114));
 assert(librarypattern::transitionReady(true,false,70,35));
 assert(librarypattern::eventHasReleaseTime(40,100));assert(!librarypattern::eventHasReleaseTime(39,100));
 assert(librarypattern::eventHasReleaseTime(400,1000));assert(!librarypattern::eventHasReleaseTime(399,1000));
 for(int s=0;s<6;++s)glove::slot(s).id=s+1;
 refreshIdlePositions();assert(scs::calls==1&&positionValidMask==63);
 for(int s=0;s<6;++s)assert(actual[s]==501+s&&glove::slot(s).last==501+s&&positionSampleMs[s]==1000);
 now=1500;scs::readCount=5;refreshIdlePositions();assert(positionValidMask==0);
 for(int s=0;s<6;++s)assert(actual[s]==501+s&&positionSampleMs[s]==1000);
 scs::readCount=6;scs::error=1;refreshIdlePositions();assert(positionValidMask==0);
 scs::error=0;scs::samples[3]=65535;refreshIdlePositions();assert(positionValidMask==0&&positionSampleMs[3]==1000);
 int calls=scs::calls;running=true;positionValidMask=63;refreshIdlePositions();assert(scs::calls==calls&&positionValidMask==63);running=false;
 glove::busy=true;refreshIdlePositions();assert(scs::calls==calls&&positionValidMask==0);glove::busy=false;
 glove::slot(3).id=3;refreshIdlePositions();assert(scs::calls==calls&&positionValidMask==0);
 // Native stopped frames replace all positional-error/deadband decisions.
 positionValidMask=63;patternChangedMask=63;
 for(int residual:{27,50,400}){
  for(int s=0;s<6;++s){poseTargets[s]=900;actual[s]=900-residual;positionSampleMs[s]=101;axisPoseAt[s]=100;actualSpeed[s]=0;actualMoving[s]=0;}
  assert(patternPreparationReady()&&patternPhaseReady());
 }
 actualSpeed[1]=2400;assert(!patternPreparationReady()&&!patternPhaseReady());actualSpeed[1]=-2400;assert(!patternPhaseReady());actualSpeed[1]=0;
 actualMoving[1]=1;assert(!patternPhaseReady());actualMoving[1]=255;assert(!patternPhaseReady());actualMoving[1]=0;
 positionSampleMs[1]=axisPoseAt[1];assert(!patternPhaseReady());positionSampleMs[1]++;assert(patternPhaseReady());axisPoseAt[1]=positionSampleMs[1];assert(!patternPhaseReady());
 positionValidMask=0;assert(!patternPhaseReady());positionValidMask=63;positionSampleMs[1]++;assert(patternPhaseReady());
 assert(librarypattern::nativeMotionEnded(3,0xfffffffeu,0,0));assert(!librarypattern::nativeMotionEnded(0xfffffffeu,3,0,0));
 assert(sequence.begin(0,1,1000,0));assert(!sequence.due(34,true));assert(sequence.due(35,false));assert(sequence.advance(35));assert(!sequence.due(35,true));assert(sequence.due(53,false));
 assert(sequence.begin(0,1,0,0));assert(!sequence.due(100000,false));assert(!sequence.expired(100000,false));assert(sequence.due(100000,true));
 puts("PASS real pattern sequence: timed deadlines ignore arrival; fastest uses fresh native stopped speed/moving frames regardless27/50 residual, no dwell/timeout; wrap and readonly idle cases retained");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path(os.environ.get('VCVARS64', 'C:/Program Files/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat'))
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)
