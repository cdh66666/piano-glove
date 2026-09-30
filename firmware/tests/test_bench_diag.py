from pathlib import Path
r=Path(__file__).resolve().parent
s=(r.parent/'src/glove.cpp').read_text(encoding='utf-8')
m=(r.parent/'src/main.cpp').read_text(encoding='utf-8')
bench=s[s.index('static int armFeedbackMargin('):s.index('// Position commands may engage')]+s[s.index('bool benchActive()'):s.index('bool mountActive(')]
safe=s[s.index('void safe()'):s.index('bool motionCalibrationSupported()')]
diag=m[m.index('static bool servoDiag('):m.index('static void cmdLine(')]
prefix=r"""
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <string.h>
#include <string>
#include <stdarg.h>
#include "../src/profile_limits.h"
bool g_mountActive=false;uint32_t g_mountDeadline=0,g_mountArrivalDeadline=0;uint8_t g_mountReady=0;const char*g_mountReason="none";
uint32_t now=0;uint32_t millis(){return now;}
bool g_benchActive=false,g_armed=true,g_calibrated=true,g_sweep=false,g_rate=false,g_rateSent=false,g_demo=false,g_auto=false;uint32_t g_benchDeadline=0;const char*g_benchFailure="none";
std::string output;void sayf(const char*f,...){char b[384];va_list a;va_start(a,f);vsnprintf(b,sizeof(b),f,a);va_end(a);output+=b;output+="\n";}void errf(const char*f,...){output+="ERR";}void okf(const char*f,...){output+="OK";}
struct SerialMock{void println(const char*p){output+=p;}}Serial;
struct Slot{bool valid=true;int lo=50,hi=300;};Slot g_slot[6];
struct ArmCheck{bool registersOk=true,feedbackOk=true,limitsOk=true;int torque=1,minimum=20,maximum=1003,position=100;};
int calInvalidSlot(){return -1;}int slotOfId(uint8_t id){return id>=1&&id<=6?id-1:-1;}bool motionCalibrationSupported(){return true;}
int feedbackPosition=100;bool offline=false;bool inspectArmSlot(int,ArmCheck &r){r={};r.position=feedbackPosition;return !offline;}
namespace calcircle{bool contains(int a,int b,int x,int){return x>=a&&x<=b;}}
int offCalls=0;void torqueAll(bool b){assert(!b);++offCalls;}
namespace scs{enum class Family{STS,SCS};struct Profile{Family family=Family::SCS;bool probed=true;int range=1023;}pf;const Profile&profile(){return pf;}bool setTorque(uint8_t,bool on){assert(!on);return true;}int lastError(){return 0;}int posTol(){return 6;}struct SyncItem{uint8_t id;uint16_t pos,speed;uint8_t acc;};int syncCalls=0,syncCount=0;bool groupActive=false;uint8_t groupGoals[7][6];void syncMove(const SyncItem*items,int n,bool raw){assert(raw);++syncCalls;syncCount=n;groupActive=true;for(int i=0;i<n;++i){const auto &v=items[i];uint8_t data[6]={uint8_t(v.pos>>8),uint8_t(v.pos),0,0,uint8_t(v.speed>>8),uint8_t(v.speed)};memcpy(groupGoals[v.id],data,6);}}uint8_t last[6];int writes=0,reads=0;bool badWrite=false,badRead=false;
bool writeRegs(uint8_t,uint8_t a,const uint8_t*d,uint8_t n){assert(a==42&&n==6);++writes;memcpy(last,d,6);return !badWrite;}
bool readRegs(uint8_t id,uint8_t a,uint8_t n,uint8_t*d){++reads;if(a==42&&n==6){memcpy(d,groupActive?groupGoals[id]:last,6);if(badRead)d[0]^=1;return true;}for(int i=0;i<n;i++)d[i]=a+i;return true;}}
"""
tests=r"""
void reset(){now=0;g_armed=g_calibrated=true;g_benchActive=false;g_sweep=g_rate=g_auto=g_demo=false;offline=false;feedbackPosition=100;for(auto &sl:g_slot)sl={};scs::pf={};scs::writes=scs::reads=offCalls=0;scs::badRead=scs::badWrite=false;scs::syncCalls=scs::syncCount=0;scs::groupActive=false;output.clear();}
int main(){
reset();assert(benchMove(1,200,1000));assert(g_benchActive&&g_benchDeadline==1200&&scs::writes==1);assert(scs::last[0]==0&&scs::last[1]==200&&scs::last[2]==0&&scs::last[3]==0&&scs::last[4]==3&&scs::last[5]==232);
now=1199;benchTick();assert(g_benchActive);now=1200;benchTick();assert(!g_benchActive&&!g_armed&&offCalls==1&&scs::writes==1&&output.find("BENCH_DONE")!=std::string::npos);now=5000;benchTick();assert(scs::writes==1&&offCalls==1);
reset();feedbackPosition=301;assert(benchMove(1,200,500));assert(scs::writes==1);safe();
reset();feedbackPosition=306;assert(benchMove(1,200,500));safe();
reset();feedbackPosition=44;assert(benchMove(1,200,500));safe();
reset();feedbackPosition=307;assert(!benchMove(1,200,500)&&scs::writes==0);
reset();feedbackPosition=43;assert(!benchMove(1,200,500)&&scs::writes==0);
reset();g_slot[0].lo=50;g_slot[0].hi=54;feedbackPosition=56;assert(!benchMove(1,52,500)&&scs::writes==0);
reset();g_slot[0].lo=900;g_slot[0].hi=1003;feedbackPosition=1004;assert(!benchMove(1,950,500)&&scs::writes==0); // Hardware bounds remain exact.
reset();feedbackPosition=301;assert(!benchMove(1,301,500)&&scs::writes==0); // Target remains exact calibration bound.
reset();assert(!benchMove(1,200,49));assert(!benchMove(1,200,1001));assert(!benchMove(7,200,1000));assert(!benchMove(1,301,200));assert(!benchMove(1,49,200));assert(scs::writes==0);
reset();g_slot[0].lo=0;assert(!benchMove(1,19,100));g_slot[0].lo=50;g_armed=false;assert(!benchMove(1,200,100));g_armed=true;offline=true;assert(!benchMove(1,200,100));assert(scs::writes==0);
reset();scs::pf.family=scs::Family::STS;assert(!benchMove(1,200,100));assert(scs::writes==0);
reset();scs::badRead=true;assert(!benchMove(1,200,500));assert(!g_benchActive&&!g_armed&&offCalls==1);
reset();assert(benchMove(1,200,50));safe();assert(!g_benchActive&&!g_armed&&scs::writes==1);
uint16_t positions[6]={200,210,220,230,240,250};
reset();assert(benchGroup(0x3f,positions,1000));assert(scs::syncCalls==1&&scs::syncCount==6&&scs::writes==0&&scs::reads==6);for(int id=1;id<=6;id++){assert(scs::groupGoals[id][0]==0&&scs::groupGoals[id][1]==positions[id-1]&&scs::groupGoals[id][2]==0&&scs::groupGoals[id][3]==0&&scs::groupGoals[id][4]==3&&scs::groupGoals[id][5]==232);}safe();
reset();assert(benchGroup(0x05,positions,500));assert(scs::syncCalls==1&&scs::syncCount==2&&scs::reads==2);safe();
reset();assert(!benchGroup(0,positions,1000)&&scs::syncCalls==0&&!g_armed);
reset();assert(!benchGroup(0x80,positions,1000)&&scs::syncCalls==0);
reset();positions[5]=301;assert(!benchGroup(0x3f,positions,1000)&&scs::syncCalls==0&&!g_armed);positions[5]=250;
reset();g_slot[5].valid=false;assert(!benchGroup(0x3f,positions,1000)&&scs::syncCalls==0);
reset();scs::badRead=true;assert(!benchGroup(0x3f,positions,1000)&&scs::syncCalls==1&&!g_armed&&!g_benchActive);
reset();g_benchActive=true;g_benchDeadline=100;now=101;assert(!benchGroup(0x3f,positions,1000)&&scs::syncCalls==0&&!g_armed);
reset();assert(servoDiag(1));assert(scs::writes==0&&scs::reads==5);assert(output.find("status=65")!=std::string::npos&&output.find("lock=48")!=std::string::npos&&output.find("max_torque=4113")!=std::string::npos&&output.find("start=64 length=3 hex=404142")!=std::string::npos);
uint8_t payload[8];motionPayload(true,200,1000,30,payload);assert(payload[5]==0&&payload[6]==200);motionPayload(true,200,0,30,payload);assert(payload[6]==200);
puts("actual BENCH/DIAG PASS: bounds, raw big-endian1000, readback,1200ms autonomous SAFE/no resume, ordinarycap200 unchanged, rawread-only67bytes +LOCK48/status65");}
"""
(r/'bench_diag_generated.cpp').write_text(prefix+safe+bench+diag+tests,encoding='utf-8')
