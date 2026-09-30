from pathlib import Path
r=Path(__file__).resolve().parent
s=(r.parent/'src/glove.cpp').read_text(encoding='utf-8')
variables=s[s.index('bool     g_rate '):s.index('// ---- DEMO ----')]
tick=s[s.index('void rateTick()'):s.index('void demoTick(')]
start=s[s.index('bool rateStart('):s.index('bool     rateActive()')]
prefix=r"""
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
#include <string>
const int SLOT_COUNT=6;bool g_armed=false,g_calibrated=true,g_demo=false,g_auto=false,g_sweep=false;
struct Slot{uint8_t id;int lo=10,hi=900,standby=100,last=100;bool online=true;};Slot g_slot[6];
struct ArmCheck{bool feedbackOk=true,limitsOk=true;int minimum=20,maximum=880,position=100;};
uint32_t tm=0;uint32_t micros(){return tm;}int off=0;std::string last;
struct Printer{void printf(const char* f,...){char b[300];va_list a;va_start(a,f);vsnprintf(b,sizeof(b),f,a);va_end(a);last=b;}}Serial;
namespace scs{struct Profile{int range=1023;}pf;const Profile& profile(){return pf;}int posTol(){return 6;}
struct SyncItem{uint8_t id;uint16_t pos,speed;uint8_t acc;};int goal[6],pos[6],readMode=0,writes=0;
void syncMove(SyncItem* p,int n){++writes;for(int i=0;i<n;++i){goal[p[i].id-1]=p[i].pos;assert(p[i].pos>=20&&p[i].pos<=880);}}
void drain(int){}int positionReadBudget(int n){return n*20;}
void syncReadPos(uint8_t*ids,int n,uint16_t*out,int){for(int i=0;i<n;++i)out[i]=readMode==1?65535:readMode==2?950:goal[ids[i]-1];tm+=20000;}
}
int calInvalidSlot(){return -1;}bool refresh(int){return true;}bool motionCalibrationSupported(){return true;}
bool inspectArmSlot(int,ArmCheck& r){r={};return true;}uint16_t pressEnd(int){return 10;}
bool armAtCurrent(uint8_t){g_armed=true;return true;}void safe();
"""
body=prefix+variables+"\nvoid safe(){g_rate=false;g_armed=false;++off;}\n"+tick+start
tests=r"""
void reset(){tm=0;off=0;last.clear();scs::writes=0;scs::readMode=0;g_rate=false;g_armed=false;for(int i=0;i<6;++i){g_slot[i]={};g_slot[i].id=i+1;}}
int main(){
reset();assert(rateStart(63,0,30,100,3));assert(g_ratePhase==2);for(int i=0;i<6;++i)assert(g_ratePress[i]==20&&g_rateRest[i]==100);
rateTick();rateTick();assert(g_rateHalfN==0&&g_rateDone==0&&g_ratePhase==0);
for(int i=0;i<12;++i)rateTick();assert(!g_rate&&!g_armed&&g_rateDone==3&&g_rateHalfN==6);assert(last.find("valid=1")!=std::string::npos);
reset();assert(rateStart(63,0,30,25,3));for(int i=0;i<6;++i)assert(g_ratePress[i]==80);rateTick();scs::readMode=2;rateTick();assert(!g_rate&&!g_armed&&g_rateDone==0&&g_rateLost==1);assert(last.find("feedback_outside_range")!=std::string::npos);
reset();assert(rateStart(63,0,30,50,3));rateTick();scs::readMode=1;tm+=800000;rateTick();assert(!g_rate&&!g_armed&&g_rateDone==0&&g_rateLost==1);assert(last.find("valid=0")!=std::string::npos);
reset();assert(rateStart(63,0,30,50,3));int before=scs::writes;rateStop();assert(scs::writes==before&&!g_armed&&!g_rate);
puts("RATE real-function tests PASS: six axes clipped, rest excluded, measured cycles, feedbackfail abort, timeout invalid, stop no new target");
}
"""
(r/'rate_feedback_generated.cpp').write_text(body+tests,encoding='utf-8')
