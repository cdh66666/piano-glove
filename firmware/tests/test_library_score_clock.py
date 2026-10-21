"""Execute actual C++ software scheduling, start and feedback paths with fake I/O.

Never opens serial/hardware. Stalled and lagging but hardware-valid positions
must not change canonical song time; real faults retain their stop behavior.
"""
from pathlib import Path
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent
source = (root.parent / 'src/device_library.cpp').read_text(encoding='utf-8')
transition = source[source.index('static int poseTransition('):source.index('static bool startPlay(')]
starts = source[source.index('static bool startPlay('):source.index('static bool peekScoreEvent(')]
scheduler = source[source.index('static bool peekScoreEvent('):source.index('static void response(')]
service = source[source.index('static void serviceMotion(){'):source.index('const char *ssid()')]
phase_ready = source[source.index('static bool patternPreparationReady(){'):source.index('static String state(){')]
tempo_change = source[source.index('static bool changeTempo('):source.index('// Firmware targets')]
cpp = root / 'library_score_clock_generated.cpp'
exe = root / 'library_score_clock_generated.exe'
cpp.write_text(r'''
#include "../src/library_pattern.h"
#include "../src/library_score_clock.h"
#include "../src/library_targets.h"
#include "../src/score_format.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <vector>
#include <string>
#include <fstream>
#include <algorithm>
using std::min;using std::max;
uint32_t now=0;uint32_t millis(){return now;}
struct Write{uint32_t at;uint8_t ids;uint16_t targets[6]={},speed[6]={};uint8_t acc[6]={};};
std::vector<Write>writes;
namespace scs{
enum class Family{STS,SCS};struct Profile{Family family=Family::STS;uint16_t range=4095;}pf;const Profile&profile(){return pf;}
struct SyncItem{uint8_t id;uint16_t pos,speed;uint8_t acc;};
struct Feedback{bool ok=true;uint8_t voltage=50,temp=25;int16_t current=0;};
int busError=0,readCount=6;bool healthOk=true;uint8_t healthVoltage=50,healthTemp=25;uint16_t samples[6]={};
int lastError(){return busError;}int positionReadBudget(int){return 20;}
int syncReadPos(const uint8_t*,int,uint16_t*out,int){for(int s=0;s<6;++s)out[s]=samples[s];return readCount;}
bool readFeedback(int,Feedback&fb){fb.ok=healthOk;fb.voltage=healthVoltage;fb.temp=healthTemp;return healthOk;}
void syncMove(const SyncItem*items,int n,bool){Write w{};w.at=now;for(int i=0;i<n;++i){int s=items[i].id-1;w.ids|=1<<s;w.targets[s]=items[i].pos;w.speed[s]=items[i].speed;w.acc[s]=items[i].acc;}writes.push_back(w);}
}
namespace glove{bool isArmed=true;struct Slot{int lo=500,hi=900,last=1300;}slots[6];Slot&slot(int s){return slots[s];}bool armed(){return isArmed;}void safe(){isArmed=false;}}
bool running=true,training=false,initializing=false,nextReady=false,patternRunning=false,ready=true,resistanceSupported=true;
uint8_t positionValidMask=63,hold=50,requestedHold=50,enabledMask=63,healthValidMask=0,movingMask=0,feedbackSlot=0,patternChangedMask=0;
uint8_t amp=100,mask=0,positionsReady=0;
uint16_t tempo=100,poseTargets[6]={},speeds[6]={},hardwareMinimum[6]={},hardwareMaximum[6]={};int16_t poseFrom[6]={},actual[6]={},currentRaw[6]={};
uint8_t volts[6]={},temps[6]={};uint32_t positionSampleMs[6]={},healthSampleMs[6]={},axisPoseAt[6]={};
uint32_t endTimes[5]={},index=0,count=0,duration=0,previousEvent=0,playedEventCount=0,candidateEventCount=0;
uint32_t started=0,keepAt=0,positionsAt=0,feedbackAt=0,poseAt=0,lastPoseMs=0;
bool boundaryPending=false,boundaryReleaseStarted=false;
uint32_t boundaryAt=0,lastScoreBoundary=0,candidateEnds[5]={};
uint8_t candidateMask=0,boundaryRepeatMask=0,boundaryReleaseMask=0;
libraryclock::WallClock scoreClock;pgl::Event nextEvent;librarypattern::Sequence patternSequence;
struct Reader{std::vector<pgl::Event>events;size_t at=0;void reset(){at=0;}bool event(uint32_t,pgl::Event&out){if(at>=events.size())return false;out=events[at++];return true;}}playReader;
struct File{bool seek(int){return true;}void close(){}}playing;
std::string stopped,failure,owner,controller;int currentSlot=1;bool outputOk=true;uint32_t fileDuration=0;std::vector<uint16_t>armingSpeeds;int preparedMask=-1;
struct SerialMock{std::vector<std::string>lines;void printf(const char*format,...){char line[512];va_list args;va_start(args,format);vsnprintf(line,sizeof(line),format,args);va_end(args);lines.push_back(line);}}Serial;
void stop(const char*reason){running=false;initializing=false;glove::safe();stopped=reason;}
int target(int s,bool pressed,uint8_t amplitude){const auto&slot=glove::slot(s);return librarytargets::softwareTarget(s,scs::pf.family==scs::Family::SCS,slot.lo,slot.hi,hardwareMinimum[s],hardwareMaximum[s],pressed,amplitude);}
bool applyOutput(int){if(!outputOk){stop("hold_limit_write_readback_failed");return false;}return true;}
bool motionOwnerMatches(const char*){return true;}std::string requestController(const char*){return "page";}
bool validSlot(int s){return s>=1&&s<=100;}
bool openScore(int,File&,uint8_t*h){memset(h,0,128);pgl::put32(h+8,playReader.events.size());pgl::put32(h+12,fileDuration);return true;}
bool prepare(int selected=0,int amplitude=100){
 preparedMask=selected;glove::isArmed=true;for(int s=0;s<6;++s){hardwareMinimum[s]=0;hardwareMaximum[s]=scs::pf.range;actual[s]=scs::samples[s];poseTargets[s]=target(s,s>0&&(selected&(1<<(s-1))),s==0?100:amplitude);speeds[s]=scs::pf.family==scs::Family::SCS?1000:8000;armingSpeeds.push_back(1200);}
 return true;
}
static void tickScoreTimeline();
''' + transition + starts + scheduler + phase_ready + tempo_change + service + r'''
void reset(const std::vector<pgl::Event>&events,int rate,uint32_t end){
 now=0;running=true;training=initializing=nextReady=patternRunning=false;glove::isArmed=true;mask=0;positionsReady=0;positionValidMask=63;hold=50;enabledMask=63;healthValidMask=0;outputOk=true;resistanceSupported=true;
 index=previousEvent=playedEventCount=candidateEventCount=0;count=events.size();duration=fileDuration=end;tempo=rate;
 boundaryPending=boundaryReleaseStarted=false;lastScoreBoundary=0;memset(endTimes,0,sizeof(endTimes));
 scs::busError=0;scs::readCount=6;scs::healthOk=true;scs::healthVoltage=50;scs::healthTemp=25;
 for(int s=0;s<6;++s){glove::slots[s].lo=500;glove::slots[s].hi=900;hardwareMinimum[s]=0;hardwareMaximum[s]=scs::pf.range;poseFrom[s]=actual[s]=scs::samples[s]=1000;poseTargets[s]=target(s,false,100);speeds[s]=scs::pf.family==scs::Family::SCS?1000:8000;positionSampleMs[s]=healthSampleMs[s]=axisPoseAt[s]=0;}
 playReader.events=events;playReader.at=0;stopped.clear();writes.clear();Serial.lines.clear();armingSpeeds.clear();preparedMask=-1;scoreClock.start(0);
 feedbackAt=positionsAt=poseAt=keepAt=started=0;feedbackSlot=movingMask=patternChangedMask=0;
}
void tick(uint32_t at){now=at;keepAt=now;serviceMotion();}
bool hasWrite(uint32_t at,int slot,int goal){for(const auto&w:writes)if(w.at==at&&(w.ids&(1<<slot))&&w.targets[slot]==goal)return true;return false;}
int main(int argc,char**argv){
 libraryclock::WallClock c;c.start(100);assert(c.desired(110,100)==10);assert(c.desired(1710,1000)==16010);assert(!c.paused());
 c.start(0xfffffffeu);assert(c.desired(3,100)==5);c.start(0);assert(c.desired(1,50)==0);assert(c.desired(2,50)==1);assert(c.desired(2,50)==1);
 std::vector<pgl::Event>simple={{0,200,60,1,96,100},{200,200,64,2,96,100}};
 reset(simple,1000,400);tick(0);assert(playedEventCount==1&&mask==1);tick(20);
 assert(!scoreClock.paused()&&scoreClock.elapsed()==200&&mask==2&&playedEventCount==2);
 tick(40);assert(!running&&stopped=="completed"&&playedEventCount==2&&now==40);assert(actual[1]==1000&&actual[2]==1000);assert(Serial.lines.size()==1);
 assert(Serial.lines[0].find("\"arrival_checked\":false")!=std::string::npos);
 // Stalled positions beyond calibration + 15%, and even physically opposite
 // travel, cannot pause song time. A final release does not await arrival.
 reset({{0,4000,60,1,96,100}},100,4000);for(uint32_t t=0;t<=4000;t+=20)tick(t);
 assert(stopped=="completed"&&now==4000&&actual[1]==1000&&poseTargets[1]==880);
 reset(simple,100,400);tick(0);scs::samples[1]=1300;tick(220);assert(running&&playedEventCount==2);tick(400);assert(stopped=="completed");
 std::vector<pgl::Event>repeat={{0,200,60,1,96,100},{200,200,62,1,96,100},{200,200,65,3,96,100}};
 reset(repeat,100,400);tick(0);tick(159);assert(mask==1);tick(160);assert(boundaryReleaseStarted&&mask==0&&playedEventCount==1);tick(199);assert(mask==0);tick(200);assert(mask==5&&playedEventCount==3);assert(hasWrite(160,1,880)&&hasWrite(200,1,520));tick(400);assert(stopped=="completed");
 reset(repeat,1000,400);tick(0);tick(9);assert(mask==1);tick(10);assert(mask==0);tick(20);assert(mask==5);assert(hasWrite(10,1,880)&&hasWrite(20,1,520));tick(40);assert(stopped=="completed");
 reset({{0,200,60,1,96,100},{0,400,64,2,96,100},{200,200,62,1,96,100}},100,400);tick(0);tick(160);assert(mask==2&&poseTargets[2]==520);tick(200);assert(mask==3);tick(400);assert(stopped=="completed");
 // Missed pre-release has no fabricated same-tick UP/DOWN or tempo delay.
 reset(repeat,1000,400);tick(0);tick(25);assert(mask==5&&playedEventCount==3);assert(!hasWrite(25,1,880));tick(40);assert(stopped=="completed");
 // A global rest stays a real rest; subsequent onsets and tempo changes use
 // canonical source time rather than the timestamp of a late feedback frame.
 reset({{100,100,60,1,96,100},{500,100,64,2,96,100}},100,600);tick(0);assert(playedEventCount==0);tick(100);assert(mask==1);tick(200);assert(mask==0);now=300;assert(changeTempo(200,"usb"));tick(399);assert(playedEventCount==1);tick(400);assert(playedEventCount==2);tick(450);assert(stopped=="completed");
 reset(simple,100,400);tick(1000);assert(stopped=="completed"&&playedEventCount==2&&now==1000); // catch-up never stretches duration
 // Targets remain inset and clipped to actual hardware limits, independent
 // of measured calibration excursion.
 reset(simple,100,400);hardwareMinimum[1]=550;hardwareMaximum[1]=850;scs::samples[1]=actual[1]=700;tick(0);assert(poseTargets[1]==550);tick(200);assert(poseTargets[1]==850);
 reset(simple,100,400);hardwareMinimum[1]=950;tick(0);assert(stopped=="working_target_invalid");
 // Arming prepares only the released pose. First musical downstroke is one
 // six-axis library-speed broadcast after arming, at the score clock origin.
 for(auto family:{scs::Family::STS,scs::Family::SCS}){
  scs::pf.family=family;scs::pf.range=family==scs::Family::STS?4095:1023;reset(simple,100,400);running=false;
  assert(startPlay(1,100,100,"usb"));assert(preparedMask==0);assert(writes.size()==1&&writes[0].ids==63&&armingSpeeds.size()==6);
  for(int s=0;s<6;++s){assert(writes[0].speed[s]==(family==scs::Family::STS?8000:1000));assert(writes[0].acc[s]==0);}assert(playedEventCount==1);
  reset(simple,100,400);running=false;assert(train(1,100,100,"usb"));assert(preparedMask==1);assert(writes.size()==1&&writes[0].ids==63);tick(20);assert(running); // calibration advisory in training
  reset(simple,100,400);running=false;assert(startPattern(2,1,100,100,100,"usb"));assert(writes.size()==1&&writes[0].ids==63&&initializing);
 }
 scs::pf.family=scs::Family::STS;scs::pf.range=4095;
 // Genuine stop conditions remain live in the actual serviceMotion path.
 reset(simple,100,400);tick(0);scs::samples[2]=4096;tick(20);assert(stopped=="feedback_hardware_limit");
 reset(simple,100,400);tick(0);scs::readCount=5;tick(20);assert(stopped=="position_feedback_lost");
 reset(simple,100,400);tick(0);scs::busError=1;tick(20);assert(stopped=="position_feedback_lost");
 reset(simple,100,400);tick(0);scs::healthOk=false;tick(100);assert(stopped=="health_feedback_lost");
 for(int voltage:{39,66}){reset(simple,100,400);tick(0);scs::healthVoltage=voltage;tick(100);assert(stopped=="temperature_or_voltage");}
 reset(simple,100,400);tick(0);scs::healthTemp=65;tick(100);assert(stopped=="temperature_or_voltage");
 reset(simple,100,400);tick(0);now=2001;serviceMotion();assert(stopped=="controller_disconnected");
 reset(simple,100,400);tick(0);glove::isArmed=false;tick(20);assert(stopped=="external_stop");
 reset(simple,100,400);tick(0);stop("stopped");auto written=writes.size();tick(1000);assert(stopped=="stopped"&&writes.size()==written);
 reset(simple,100,400);scs::busError=1;tick(0);assert(stopped=="sync_write_failed");
 reset(simple,100,400);outputOk=false;tick(0);assert(stopped=="hold_limit_write_readback_failed");
 // Pattern pacing intentionally remains feedback-based, with its existing
 // timeout. No calibration-based veto is added to its initialization.
 reset(simple,100,400);running=false;assert(startPattern(2,1,100,100,100,"usb"));tick(20);assert(running&&initializing);tick(1801);assert(stopped=="pattern_full_target_not_reached");
 int cases=0;
 for(int arg=1;arg<argc;++arg){std::ifstream file(argv[arg],std::ios::binary);assert(file);std::vector<uint8_t>blob((std::istreambuf_iterator<char>(file)),{});pgl::Validator validator;assert(validator.header(blob.data(),blob.size()));
  std::vector<pgl::Event>events;for(uint32_t i=0;i<validator.count;++i){const uint8_t*b=blob.data()+128+16*i;assert(validator.add(b));events.push_back(pgl::event(b));}assert(validator.finish());
  for(auto family:{scs::Family::STS,scs::Family::SCS})for(int rate:{50,100,200,1000})for(int feedbackMode:{0,1}){
   scs::pf.family=family;scs::pf.range=family==scs::Family::STS?4095:1023;reset(events,rate,pgl::u32(blob.data()+12));uint32_t deadline=(duration*100+rate-1)/rate;
   for(uint32_t t=0;running&&t<=deadline+5;t+=5){if(feedbackMode)for(int s=0;s<6;++s){int delta=int(poseTargets[s])-scs::samples[s];scs::samples[s]+=delta<0?-min(-delta,1):min(delta,1);}tick(t);}
   assert(!running&&stopped=="completed"&&playedEventCount==events.size()&&index==count&&Serial.lines.size()==1);assert(now>=deadline&&now<deadline+5);assert(!scoreClock.paused());++cases;
  }
 }
 printf("PASS actual start/sendPose/service/scheduler: %d original/synthetic PGL cases, stalled/lagging positions, 50/100/200/1000 percent, exact deadline within 5ms tick; advisory calibration, no arrival waits, capped pre-release, late catchup, live tempo, first six-axis max-speed broadcast, bounded targets, genuine hardware/health/bus/lease/stop retained\n",cases);
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
fixtures=root.parents[2]/'evidence/software-20261011/reviewed-pdf-excerpts'
paths=[fixtures/(name+'.pgl') for name in ('1007271','969886','1003497','1002169','feature-hold-rest-chord-repeat')]
assert all(path.exists() for path in paths),paths
subprocess.run([str(exe),*map(str,paths)],check=True)
