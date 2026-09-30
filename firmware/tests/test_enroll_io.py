"""Generate a host harness from the actual firmware I/O helpers (no serial hardware)."""
from pathlib import Path
root=Path(__file__).resolve().parent
source=(root.parent/'src/main.cpp').read_text(encoding='utf-8')
functions=source[source.index('static EnrollFlow g_enrollFlow;'):source.index('// ---------------------------------------------------------------- 槽位行输出')]
prefix=r'''
#include "../src/enroll_flow.h"
#include "../src/profile_limits.h"
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
uint32_t fakeMs=0;uint32_t millis(){return fakeMs;}void delay(int n){fakeMs+=n;}
void sayf(const char*,...){}
static void probeAndReport(uint8_t);
namespace scs {
constexpr uint32_t BUS_BAUD=1000000;
static uint32_t currentBaud=BUS_BAUD;
uint32_t busBaud(){return currentBaud;}
void setBusBaud(uint32_t b){currentBaud=b;}
enum class Family {UNKNOWN,STS,SCS};
struct Profile {Family family=Family::UNKNOWN;uint16_t range=0,model=0,minAng=0,maxAng=0;bool probed=false;};
static bool bootMode=false,badFeedback=false;static uint8_t bootMask=0;static int pingReads=0,feedbackReads=0;
static uint16_t model=0x1234;static bool scsMode=false,readFail=false,torqueStuck=false,idWriteWorks=true;
static int liveId=1,lastLock=0,idWrites=0;
bool readRegs(uint8_t,uint8_t addr,uint8_t,uint8_t *out){
 if(readFail)return false;
 if(addr==3){out[0]=model>>8;out[1]=model&255;}
 if(addr==9){out[0]=0;out[1]=scsMode?20:0;}
 if(addr==11){out[0]=scsMode?3:255;out[1]=scsMode?235:15;}
 if(addr==40)*out=torqueStuck?1:0;return true;
}
bool setTorque(uint8_t,bool on){assert(!on);return true;}
bool ping(uint8_t id,int){++pingReads;return bootMode?(currentBaud==BUS_BAUD&&id<=6&&(bootMask&(1u<<(id-1)))):id==liveId;}
struct Feedback{bool ok=true;int pos=381;};
Profile pf;const Profile &profile(){pf.range=1023;return pf;}int lastError(){return 0;}
bool readFeedback(uint8_t id,Feedback &fb,int){++feedbackReads;fb.ok=!badFeedback;return !badFeedback;}
bool writeRegs(uint8_t,uint8_t addr,const uint8_t *value,uint8_t){
 if(addr==48||addr==55)lastLock=addr;
 if(addr==5){++idWrites;if(idWriteWorks)liveId=*value;}
 return addr!=5; // Real devices may acknowledge at NEW ID; verification is authoritative.
}
void setProfile(const Profile&){}
}
namespace glove{int invalidations=0,maps=0,safes=0;void saveProfile(){} void safe(){++safes;} void markCommand(){} void invalidateCalibration(){++invalidations;} bool setMap(int,uint8_t){++maps;return true;}}
static int profileProbes=0;static void probeAndReport(uint8_t){++profileProbes;}
'''
tests=r'''
static void reset(){fakeMs=0;g_enrollFlow.stop();enrollSync();g_bootEnrollmentChecked=false;g_enrollAutomaticBoot=false;g_enrollBootReadyStable=0;scs::bootMode=false;scs::bootMask=0;scs::badFeedback=false;scs::pingReads=scs::feedbackReads=0;glove::invalidations=glove::maps=glove::safes=0;scs::currentBaud=scs::BUS_BAUD;scs::idWrites=0;scs::liveId=1;scs::model=0x1234;scs::readFail=false;scs::torqueStuck=false;scs::idWriteWorks=true;g_enrollModel=0;g_enrollFamily=scs::Family::UNKNOWN;}
int main(){
 reset();scs::scsMode=true;scs::liveId=20;assert(enrollRename(20,20));assert(scs::liveId==20&&scs::idWrites==0);
 reset();scs::scsMode=true;scs::liveId=19;assert(enrollRename(19,19));assert(scs::liveId==19&&scs::idWrites==0);
 reset();scs::scsMode=false;assert(enrollRename(1,20));assert(scs::lastLock==55&&scs::liveId==20);
 scs::liveId=2;scs::model=0x4321;assert(!enrollRename(2,19));assert(scs::liveId==2);
 reset();scs::scsMode=true;scs::model=0x0504;assert(enrollRename(1,20));assert(scs::lastLock==48);
 scs::liveId=2;scs::scsMode=false;assert(!enrollRename(2,19));
 reset();scs::torqueStuck=true;assert(!enrollRename(1,20));assert(scs::liveId==1);assert(!strcmp(g_enrollReason,"torque_off_unverified"));
 reset();scs::idWriteWorks=false;assert(!enrollRename(1,20));assert(scs::liveId==1);
 reset();scs::readFail=true;assert(!enrollRename(1,20));assert(!strcmp(g_enrollReason,"read_model_failed")&&!strcmp(g_enrollStep,"read_reg3"));
 reset();scs::model=0;assert(!enrollRename(1,20));assert(!strcmp(g_enrollReason,"model_invalid")&&g_enrollModelRaw==0);
 reset();scs::scsMode=false;g_enrollFlow.start();g_enrollFlow.phase=EnrollFlow::WAIT_NEXT;enrollSync();g_enrollLockedBaud=1000000;g_enrollBaudIndex=1;g_enrollScanId=1;g_enrollModel=scs::model;g_enrollFamily=scs::Family::STS;
 enrollTick(0);assert(g_enrollFlow.phase==EnrollFlow::PAUSED_BAUD && !g_enroll);
 reset();g_enrollFlow.start();g_enrollFlow.phase=EnrollFlow::WAIT_NEXT;enrollSync();g_enrollLockedBaud=1000000;g_enrollBaudIndex=1;g_enrollScanId=1;g_enrollModel=0x9999;g_enrollFamily=scs::Family::STS;
 enrollTick(0);assert(g_enrollFlow.phase==EnrollFlow::CONFLICT && !g_enroll);
 g_enrollLockedBaud=0;g_enroll=false;scs::setBusBaud(500000);enrollStop();assert(scs::busBaud()==500000);
 // A locked-baud round reaches observe after20 pings, not100.
 reset();g_enrollFlow.start();g_enrollFlow.phase=EnrollFlow::WAIT_NEXT;g_enrollFlow.expected=1ul<<20;enrollSync();g_enrollLockedBaud=scs::BUS_BAUD;g_enrollScanId=1;g_enrollBaudIndex=0;g_enrollLockedScans=0;g_enrollSeen=0;g_enrollFoundBaud=0;scs::liveId=20;
 for(int i=0;i<20;++i)enrollTick(0);assert(g_enrollFlow.lastSeen==(1ul<<20)&&scs::pingReads==20&&g_enrollBaudIndex==0);
 // The common-baud first candidate is read for identity then immediately rescanned.
 reset();g_enrollFlow.start();g_enrollFlow.phase=EnrollFlow::WAIT_FIRST;enrollSync();g_enrollScanId=1;g_enrollBaudIndex=0;g_enrollLockedBaud=0;g_enrollSeen=0;g_enrollFoundBaud=0;scs::liveId=1;
 for(int i=0;i<20;++i)enrollTick(0);assert(g_enrollLockedBaud==scs::BUS_BAUD&&g_enrollFlow.stable==1&&scs::idWrites==0);
 reset();scs::bootMode=true;scs::bootMask=0x3F;bootCheckEnrollment();assert(!g_enroll&&scs::pingReads==6&&scs::feedbackReads==6&&glove::invalidations==0&&glove::maps==0&&glove::safes==0);
 reset();scs::bootMode=true;scs::bootMask=0x1F;bootCheckEnrollment();assert(g_enroll&&g_enrollAutomaticBoot&&g_enrollFlow.phase==EnrollFlow::WAIT_EMPTY);assert(glove::invalidations==0&&glove::maps==0);
 enrollStop();int pingCount=scs::pingReads;bootCheckEnrollment();assert(!g_enroll&&scs::pingReads==pingCount&&!g_enrollAutomaticBoot);
 reset();scs::bootMode=true;scs::bootMask=0x3F;scs::badFeedback=true;bootCheckEnrollment();assert(g_enroll&&g_enrollFlow.phase==EnrollFlow::WAIT_EMPTY);
 reset();scs::bootMode=true;scs::bootMask=0x3F;scs::badFeedback=true;bootCheckEnrollment();for(int i=0;i<200;++i)enrollTick(0);assert(g_enroll&&g_enrollFlow.phase==EnrollFlow::WAIT_EMPTY&&glove::invalidations==0&&glove::maps==0);
 // Separate servo power arrives late while automatically preparing on empty bus.
 reset();scs::bootMode=true;bootCheckEnrollment();assert(g_enroll);for(int i=0;i<200;++i)enrollTick(0);assert(g_enrollFlow.phase==EnrollFlow::WAIT_FIRST&&glove::invalidations==0);
 scs::bootMask=0x3F;for(int i=0;i<200;++i)enrollTick(0);assert(!g_enroll&&g_enrollFlow.phase==EnrollFlow::OFF&&glove::invalidations==0&&glove::maps==0);
 // A deliberate renumber always waits for an empty bus, even with all six present.
 reset();scs::bootMode=true;scs::bootMask=0x3F;assert(enrollStart());for(int i=0;i<200;++i)enrollTick(0);assert(g_enroll&&g_enrollFlow.phase==EnrollFlow::WAIT_EMPTY&&!g_enrollAutomaticBoot);
 puts("actual I/O helpers PASS: STOP preserves busbaud, baud pause vs mixed model, model identity, endian profile, lock48/55, torque-off and ID verification failures");
}
'''
(root/'enroll_io_generated.cpp').write_text(prefix+functions+tests,encoding='utf-8')
