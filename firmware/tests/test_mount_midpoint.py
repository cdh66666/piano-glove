from pathlib import Path
r=Path(__file__).resolve().parent
s=(r.parent/'src/glove.cpp').read_text(encoding='utf-8')
func=s[s.index('bool mountActive()'):s.index('bool setMap(')]
safe=s[s.index('void safe()'):s.index('bool motionCalibrationSupported()')]
invalid=s[s.index('void invalidateCalibration()'):s.index('void calClear()')]
vars=s[s.index('bool g_mountActive='):s.index('const char *g_mountReason=')]+s[s.index('const char *g_mountReason='):s.index('const char *g_mountReason=')+len('const char *g_mountReason="none";')]
prefix=r"""
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <string.h>
#include <stdlib.h>
#include <string>
uint32_t now=0;uint32_t millis(){return now;}
bool g_benchActive=false,g_armed=true,g_calibrated=true,g_sweep=false,g_rate=false,g_rateSent=false,g_demo=false,g_auto=false;uint32_t g_benchDeadline=0;
const int SLOT_COUNT=6;
struct Slot{bool valid=true;}g_slot[6];int saves=0;void save(){++saves;}
std::string output;struct SerialMock{void println(const char*s){output+=s;}}Serial;
namespace scs {enum class Family{STS,SCS};struct Profile{Family family=Family::SCS;bool probed=true;int range=1023;}pf;const Profile&profile(){return pf;}int lastError(){return 0;}int posTol(){return 6;}
struct Feedback{bool ok=true;int pos=100;};
int goals[6],pos[6];bool torque[6];int motionWrites=0,offCalls=0;int offline=-1,badLimit=-1,mixedModel=-1;bool badReadback=false;
bool setTorque(uint8_t id,bool on){torque[id-1]=on;if(!on)++offCalls;return true;}
bool readRegs(uint8_t id,uint8_t a,uint8_t n,uint8_t*d){if(id==offline)return false;memset(d,0,n);if(a==3){d[0]=id==mixedModel?6:5;d[1]=4;}if(a==9){d[0]=0;d[1]=20;d[2]=id==badLimit?1:3;d[3]=id==badLimit?244:235;}if(a==40)*d=torque[id-1];if(a==42){d[0]=2;d[1]=badReadback?1:0;d[5]=200;}return true;}
bool readFeedback(uint8_t id,Feedback&fb){if(id==offline)return false;fb.pos=pos[id-1];return true;}
bool moveTo(uint8_t id,uint16_t p,uint16_t speed,uint8_t acc){assert(p==512&&speed==200&&acc==0);++motionWrites;goals[id-1]=p;torque[id-1]=true;return true;}}
void torqueAll(bool on){for(int i=1;i<=6;i++)scs::setTorque(i,on);}
void safe();void invalidateCalibration();
"""
tests=r"""
void reset(){now=0;g_mountActive=false;g_mountReady=0;g_mountReason="none";g_armed=g_calibrated=true;g_benchActive=g_sweep=g_rate=g_auto=g_demo=false;saves=0;scs::pf={};scs::offline=scs::badLimit=scs::mixedModel=-1;scs::badReadback=false;scs::motionWrites=scs::offCalls=0;for(int i=0;i<6;i++){g_slot[i].valid=true;scs::pos[i]=100;scs::torque[i]=true;}output.clear();}
void off(){assert(!g_mountActive&&!g_armed);for(bool x:scs::torque)assert(!x);}
int main(){
reset();g_calibrated=false;for(auto &sl:g_slot)sl.valid=false;assert(mountStart());assert(g_mountActive&&!g_armed&&!g_calibrated&&saves==1&&scs::motionWrites==6&&g_mountReady==0);for(auto &sl:g_slot)assert(!sl.valid);
for(int i=0;i<6;i++)scs::pos[i]=512;for(int i=0;i<6;i++){now+=20;mountTick();}assert(mountReadyMask()==63&&g_mountArrivalDeadline==0);int writes=scs::motionWrites,saveCount=saves;now=2000;assert(mountKeep());now=4000;mountTick();assert(g_mountActive&&scs::motionWrites==writes&&saves==saveCount);now=5000;mountTick();off();assert(output.find("watchdog")!=std::string::npos);assert(!mountKeep());assert(scs::motionWrites==writes);
reset();scs::offline=4;assert(!mountStart());off();assert(scs::motionWrites==0&&saves==0);
reset();scs::badLimit=6;assert(!mountStart());off();assert(scs::motionWrites==0&&saves==0);
reset();scs::mixedModel=6;assert(!mountStart());off();assert(scs::motionWrites==0);
reset();scs::badReadback=true;assert(!mountStart());off();assert(saves==1&&scs::motionWrites==1);
reset();assert(mountStart());now=2500;assert(mountKeep());now=4000;mountTick();off();assert(!strcmp(mountReason(),"arrival_timeout"));
reset();assert(mountStart());scs::pos[0]=1004;now=20;mountTick();off();assert(!strcmp(mountReason(),"feedback_hardware_outside"));
reset();assert(mountStart());scs::offline=1;now=20;mountTick();off();
reset();assert(mountStart());assert(mountStop());off();assert(!strcmp(mountReason(),"stopped"));assert(scs::motionWrites==6);
reset();assert(mountStart());scs::offline=1;assert(!mountStop());off();assert(!strcmp(mountReason(),"release_unverified"));
reset();scs::pf.family=scs::Family::STS;assert(!mountStart());off();assert(scs::motionWrites==0&&saves==0);
puts("MOUNT actual helpers PASS: oldcal independence, six preflights,512 goals, persistentinvalidate, feedbackready,3000ms watchdog,4000ms arrival, KEEPnoEEPROM, failure/STOPSAFE noresume");}
"""
(r/'mount_midpoint_generated.cpp').write_text(prefix+vars+'\n'+safe+invalid+func+tests,encoding='utf-8')
