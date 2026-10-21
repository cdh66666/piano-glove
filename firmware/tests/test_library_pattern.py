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
uint8_t patternChangedMask=0;int16_t poseFrom[6]={};uint16_t poseTargets[6]={};
namespace glove{
struct Slot{uint8_t id=0;int last=-1;}slots[6];Slot&slot(int s){return slots[s];}
bool busy=false;bool autoActive(){return busy;}bool mountActive(){return false;}bool benchActive(){return false;}bool rateActive(){return false;}bool sweepActive(){return false;}
}
namespace scs{
enum class Family{STS,SCS};constexpr int BROADCAST_ID=254;struct Profile{int range=4095;Family family=Family::STS;}pf;const Profile&profile(){return pf;}
int calls=0,readCount=6,error=0;uint16_t samples[6]={501,502,503,504,505,506};
int positionReadBudget(int){return 20;}int lastError(){return error;}
int syncReadPos(const uint8_t*,int,uint16_t*out,int){++calls;for(int s=0;s<6;++s)out[s]=samples[s];return readCount;}
}
''' + idle + phase_ready + r'''
int main(){
 librarypattern::Sequence sequence;
 for(int rate:{0,50,100,200,1000}){
  assert(sequence.begin(0,2,rate,1000));assert(sequence.total==20);
  for(int step=0;step<20;++step){
   assert(sequence.step==step);assert(sequence.mask()==(step%2?0:1<<(step/2%5)));
   assert(!sequence.due(sequence.phaseStarted+sequence.dwell()+100,false));
   assert(sequence.due(sequence.phaseStarted+sequence.dwell(),true));
   assert(!sequence.expired(sequence.phaseStarted+1800,false));assert(sequence.expired(sequence.phaseStarted+1801,false));
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
 // A small phase cannot appear completed just because its whole requested
 // motion fits inside the ordinary 114/35-count arrival allowance.
 patternChangedMask=2;positionValidMask=2;poseFrom[1]=0;poseTargets[1]=80;actual[1]=0;
 assert(!patternPhaseReady());actual[1]=39;assert(!patternPhaseReady());actual[1]=40;assert(patternPhaseReady());
 positionValidMask=0;assert(!patternPhaseReady());positionValidMask=2;
 poseTargets[1]=800;actual[1]=400;assert(!patternPhaseReady());actual[1]=685;assert(!patternPhaseReady());actual[1]=686;assert(patternPhaseReady());
 scs::pf.family=scs::Family::SCS;poseTargets[1]=20;actual[1]=0;assert(!patternPhaseReady());actual[1]=10;assert(patternPhaseReady());
 poseTargets[1]=500;actual[1]=250;assert(!patternPhaseReady());actual[1]=465;assert(patternPhaseReady());
 patternChangedMask=0;positionValidMask=0;assert(patternPhaseReady());
 // Preparation retains the ordinary servo tolerance even if its remaining
 // move is only two counts; a servo dead zone must not demand one-count arrival.
 scs::pf.family=scs::Family::STS;positionValidMask=63;
 for(int s=0;s<6;++s){poseTargets[s]=2000;actual[s]=1998;poseFrom[s]=1998;}
 assert(patternPreparationReady());actual[3]=1885;assert(!patternPreparationReady());actual[3]=1998;
 scs::pf.family=scs::Family::SCS;assert(patternPreparationReady());actual[3]=1964;assert(!patternPreparationReady());actual[3]=1998;
 // Only the new changing finger can gate an active phase. Static ID1 and
 // other axes retain old two-count poses without adding a one-count constraint.
 scs::pf.family=scs::Family::STS;patternChangedMask=2;
 poseFrom[1]=0;poseTargets[1]=80;actual[1]=0;assert(!patternPhaseReady());
 actual[1]=40;assert(patternPhaseReady());
 puts("PASS real pattern sequence: 3 masks, feedback-gated phases, rate 0/50..1000, no missed-phase advancement, wrap; 20% small goals require measured half progress and full strokes retain 114/35 tolerance; score deadline/half-target rules; actual idle read is read-only and stale samples are invalidated");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)
