from pathlib import Path
root=Path(__file__).resolve().parent
src=(root.parent/'src/glove.cpp').read_text(encoding='utf-8')
body=src[src.index('bool motionCalibrationSupported('):src.index('uint16_t pressPos(')]
move_body=src[src.index('bool pressSlot('):src.index('bool benchActive(')]
prefix=r'''
#include <stdint.h>
#include <initializer_list>
#include "../src/cal_circle.h"
#include <stdlib.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct ArmCheck{bool registersOk=false,feedbackOk=false,limitsOk=false;int registerError=0,feedbackError=0,limitError=0,torque=-1,goal=-1,position=-1,minimum=-1,maximum=-1,responseLevel=-1,responseError=0;};
struct Log{void println(const char*){}}Serial;
uint32_t fakeMs=0;uint32_t millis(){return fakeMs;}void delay(uint32_t n){fakeMs+=n;}
const int SLOT_COUNT=6;bool g_armed=false,g_calibrated=true;uint16_t g_speed=1200;uint8_t g_acc=30;
struct Slot{uint8_t id;bool valid=true;int lo=100,hi=900,standby=100;};Slot g_slot[6];
int calInvalidSlot(){return 0-1;}
int slotOfId(uint8_t id){for(int i=0;i<6;i++)if(g_slot[i].id==id)return i;return -1;}
bool moveRaw(uint8_t,uint16_t,uint16_t,uint8_t);
namespace scs{
enum class Family{UNKNOWN,STS,SCS};
struct Profile{Family family=Family::SCS;bool probed=true;int range=1023;}pf;
struct Feedback{bool ok=true;int pos=381;};
const int REG_TORQUE_EN=40;
bool torque[6];int goals[6];int writes=0,enables=0,safeCount=0;
int edgePosition=-1;
bool hardwareOutside=false,prewriteHardwareOutside=false,configFailed=false;int configReads=0;
bool slack=false,prewriteOutside=false,settleTransient=false,settlePersistent=false,settleOutside=false,engagementTransient=false,enableTransient=false,enablePersistent=false;int feedbackReads[6]={};
bool autoEnable=false;int autoEnableId=-1;int implicitEnables=0;bool missingAck=false;bool badGoal=false,badOff=false,drift=false,outside=false;int failedEnable=-1;
const Profile &profile(){return pf;}int posTol(){return pf.family==Family::SCS?6:24;}
int lastError(){return 0;}
bool readRegs(uint8_t id,uint8_t addr,uint8_t n,uint8_t *out){
 int i=id-1;if(addr==8){++configReads;if(configFailed)return false;out[0]=1;if(n==5){assert(pf.family==Family::SCS);out[1]=0;out[2]=20;out[3]=3;out[4]=235;}return true;}if(addr==9){const int lo=20,hi=1003;out[0]=pf.family==Family::SCS?lo>>8:lo&255;out[1]=pf.family==Family::SCS?lo&255:lo>>8;out[2]=pf.family==Family::SCS?hi>>8:hi&255;out[3]=pf.family==Family::SCS?hi&255:hi>>8;return true;}out[0]=badOff?1:torque[i];
 if(n==4){int v=goals[i]+(badGoal?1:0);out[1]=0;
 out[2]=pf.family==Family::SCS?v>>8:v&255;out[3]=pf.family==Family::SCS?v&255:v>>8;}
 return true;
}
bool readFeedback(uint8_t id,Feedback &fb){int i=id-1;int n=++feedbackReads[i];fb.pos=edgePosition>=0?edgePosition:hardwareOutside||(prewriteHardwareOutside&&n>1)?1005:outside||(prewriteOutside&&n>1)||(settleOutside&&n>=4)?1021:(drift&&torque[i]?481:((settleTransient&&n==4)||(engagementTransient&&n>=3&&n<=4)||(enableTransient&&n>=7&&n<=8)||(enablePersistent&&n>=7)||(settlePersistent&&n>=4)?390:(slack&&n>1?401:381)));return true;}
bool moveTo(uint8_t id,uint16_t p,uint16_t,uint8_t){assert(!torque[id-1]);goals[id-1]=p;++writes;if(autoEnable&&(autoEnableId<0||id==autoEnableId)){torque[id-1]=true;++implicitEnables;}return !missingAck;}
bool setTorque(uint8_t id,bool on){if(on){assert(writes==6);assert(goals[id-1]==(edgePosition>=0?(edgePosition<g_slot[id-1].lo?g_slot[id-1].lo:(edgePosition>g_slot[id-1].hi?g_slot[id-1].hi:edgePosition)):(slack?401:381)));++enables;if(id==failedEnable)return false;}torque[id-1]=on;return true;}
}
void safe(){++scs::safeCount;g_armed=false;for(int i=0;i<6;++i)scs::torque[i]=false;}
'''
body+='\nuint16_t pressPos(int,uint8_t){return 800;}\n'+move_body
tests=r'''
void reset(){g_calibrated=true;g_armed=false;scs::pf={};scs::writes=0;scs::enables=0;scs::safeCount=0;fakeMs=0;scs::edgePosition=-1;scs::hardwareOutside=scs::prewriteHardwareOutside=false;scs::settleTransient=scs::settlePersistent=scs::settleOutside=scs::engagementTransient=scs::enableTransient=scs::enablePersistent=false;scs::slack=false;scs::prewriteOutside=false;memset(scs::feedbackReads,0,sizeof(scs::feedbackReads));scs::autoEnableId=-1;scs::autoEnable=false;scs::implicitEnables=0;scs::missingAck=false;scs::badGoal=scs::badOff=scs::drift=scs::outside=false;scs::failedEnable=-1;for(int i=0;i<6;++i){g_slot[i].id=i+1;g_slot[i].lo=100;g_slot[i].hi=900;scs::torque[i]=false;scs::goals[i]=800;}}
void off(){assert(!g_armed);for(bool on:scs::torque)assert(!on);}
int main(){
 reset();assert(!moveRaw(1,381,600,30));g_armed=true;assert(!moveRaw(1,99,600,30));assert(!moveRaw(77,381,600,30));g_slot[0].lo=0;assert(!moveRaw(1,19,600,30));assert(scs::writes==0);
 reset();scs::autoEnable=true;scs::edgePosition=461;for(auto &sl:g_slot){sl.lo=276;sl.hi=460;}assert(armAtCurrent(63));for(int goal:scs::goals)assert(goal==460);for(auto &sl:g_slot)assert(sl.lo==276&&sl.hi==460); // Actual passive rebound regression.
 for(int edge:{901,906,99,94}){reset();scs::autoEnable=true;scs::edgePosition=edge;assert(armAtCurrent(63));for(int goal:scs::goals)assert(goal==(edge>900?900:100));for(auto &sl:g_slot)assert(sl.lo==100&&sl.hi==900);}
 reset();scs::edgePosition=1021;assert(!armAtCurrent(63));off();assert(scs::writes==0&&strstr(armFailure(),"feedback_outside"));
 reset();scs::edgePosition=0;for(auto &sl:g_slot)sl.lo=200;assert(!armAtCurrent(63));off();assert(scs::writes==0);
 reset();scs::edgePosition=106;for(auto &sl:g_slot){sl.lo=100;sl.hi=104;}assert(!armAtCurrent(63));off();assert(scs::writes==0); // Small span4 floors to zero margin.
 reset();scs::edgePosition=1004;for(auto &sl:g_slot){sl.lo=900;sl.hi=1003;}assert(!armAtCurrent(63));off();assert(scs::writes==0&&strstr(armFailure(),"feedback_hardware_outside"));
 for(int edge:{801,890,199,110}){reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;for(auto &sl:g_slot){sl.lo=200;sl.hi=800;}scs::edgePosition=edge;assert(armFeedbackAllowed(g_slot[0],edge,4095));assert(armCurrentGoal(g_slot[0],edge,20,1003)==(edge>800?800:200));for(auto &sl:g_slot)assert(sl.lo==200&&sl.hi==800);}
 for(int edge:{891,109}){reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;for(auto &sl:g_slot){sl.lo=200;sl.hi=800;}scs::edgePosition=edge;assert(!armAtCurrent(63));off();assert(scs::writes==0);}
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;scs::edgePosition=1004;for(auto &sl:g_slot){sl.lo=900;sl.hi=1003;}assert(!armAtCurrent(63));off();assert(scs::writes==0&&strstr(armFailure(),"feedback_hardware_outside"));
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;scs::edgePosition=106;for(auto &sl:g_slot){sl.lo=100;sl.hi=104;}assert(!armAtCurrent(63));off();assert(scs::writes==0);
 reset();for(auto &sl:g_slot)sl.hi=1020;scs::hardwareOutside=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"feedback_hardware_outside"));assert(scs::writes==0);
 reset();for(auto &sl:g_slot)sl.hi=1020;scs::prewriteHardwareOutside=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"prewrite_hardware_outside"));assert(scs::writes==0);
 reset();scs::autoEnable=true;scs::enableTransient=true;assert(armAtCurrent(63));assert(g_armed&&scs::writes==6);
 reset();scs::autoEnable=true;scs::enablePersistent=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"enabled_moved"));assert(scs::writes==6);
 reset();scs::autoEnable=true;scs::engagementTransient=true;assert(armAtCurrent(63));assert(g_armed&&scs::writes==6);for(int goal:scs::goals)assert(goal==381);
 reset();scs::engagementTransient=true;assert(!armPrepareCurrent(63));off();assert(strstr(armFailure(),"postwrite_moved"));assert(fakeMs==0&&scs::writes==1);
 reset();scs::autoEnable=true;scs::settleTransient=true;assert(armAtCurrent(63));assert(g_armed&&scs::writes==6&&fakeMs>=90);
 reset();scs::settleTransient=true;assert(!armPrepareCurrent(63));off();assert(strstr(armFailure(),"current_moved"));assert(fakeMs==0&&scs::writes==6);
 reset();scs::autoEnable=true;scs::settlePersistent=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"postwrite_moved"));assert(fakeMs==300&&scs::writes==1);
 reset();scs::autoEnable=true;scs::settleOutside=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"postwrite_outside"));assert(fakeMs==5&&scs::writes==1);
 reset();scs::autoEnable=true;scs::slack=true;assert(armAtCurrent(63));assert(g_armed);for(int goal:scs::goals)assert(goal==401);
 reset();scs::slack=true;assert(armPrepareCurrent(63));off();for(int goal:scs::goals)assert(goal==401);
 reset();scs::autoEnable=true;scs::slack=true;scs::drift=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"postwrite_moved"));
 reset();scs::prewriteOutside=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"prewrite_outside"));assert(scs::writes==0);
 reset();scs::autoEnable=true;assert(armPrepareCurrent(63));off();assert(scs::implicitEnables==6&&scs::enables==0&&scs::writes==6);
 reset();scs::autoEnable=true;assert(armAtCurrent(63));assert(g_armed&&scs::implicitEnables==6&&scs::enables==0);
 reset();scs::autoEnable=true;scs::drift=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"postwrite_moved"));assert(scs::writes==1);
 reset();scs::autoEnable=true;scs::badGoal=true;assert(!armPrepareCurrent(63));off();assert(strstr(armFailure(),"goal_mismatch"));
 reset();scs::autoEnable=true;scs::missingAck=true;assert(!armPrepareCurrent(63));off();assert(strstr(armFailure(),"goal_write_unacknowledged"));
 reset();scs::autoEnable=true;scs::outside=true;assert(!armAtCurrent(63));off();assert(scs::writes==0&&scs::implicitEnables==0);
 for(auto family:{scs::Family::SCS,scs::Family::STS})for(int span:{4,7,100,237,600}){reset();scs::pf.family=family;scs::pf.range=family==scs::Family::SCS?1023:4095;auto &sl=g_slot[0];sl.lo=200;sl.hi=200+span;const int margin=span*15/100;assert(armFeedbackMargin(sl)==margin);assert(armFeedbackAllowed(sl,sl.lo-margin,scs::pf.range));assert(armFeedbackAllowed(sl,sl.hi+margin,scs::pf.range));assert(!armFeedbackAllowed(sl,sl.lo-margin-1,scs::pf.range));assert(!armFeedbackAllowed(sl,sl.hi+margin+1,scs::pf.range));assert(armCurrentGoal(sl,sl.hi+margin,20,1003)==sl.hi);assert(sl.lo==200&&sl.hi==200+span);}
 reset();ArmCheck row;assert(inspectArmSlot(0,row));assert(row.responseLevel==1&&row.torque==0&&row.goal==800&&row.position==381&&row.minimum==20&&row.maximum==1003);assert(scs::writes==0&&scs::enables==0&&scs::safeCount==0);
 reset();assert(armPrepareCurrent(63));off();assert(scs::writes==6&&scs::enables==0);
 reset();scs::missingAck=true;assert(!armPrepareCurrent(63));off();assert(strstr(armFailure(),"goal_write_unacknowledged"));assert(strstr(armFailure(),"observed=381 expected=381"));assert(scs::enables==0);
 reset();assert(armAtCurrent(63));assert(g_armed&&scs::enables==6);
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;assert(armAtCurrent(63));
 reset();scs::pf.probed=false;assert(!armAtCurrent(63));off();assert(scs::writes==0);
 reset();g_calibrated=false;assert(!armAtCurrent(63));off();
 reset();scs::badOff=true;assert(!armAtCurrent(63));off();assert(scs::enables==0);
 reset();scs::outside=true;assert(!armAtCurrent(63));off();assert(scs::enables==0);
 reset();scs::badGoal=true;assert(!armAtCurrent(63));off();assert(scs::enables==0);assert(strstr(armFailure(),"goal_mismatch"));
 reset();scs::failedEnable=3;assert(!armAtCurrent(63));off();
 reset();scs::drift=true;assert(!armAtCurrent(63));off();
 reset();g_slot[0].lo=504;g_slot[0].hi=31;g_slot[0].standby=9;assert(calcircle::valid(504,9,31,1023));assert(!motionCalibrationSupported());assert(!armAtCurrent(63));assert(!pressSlot(0,1200,30));assert(!releaseSlot(0,1200,30));assert(!moveRaw(1,9,1200,30));off();assert(scs::writes==0);
 reset();g_slot[0].lo=1000;g_slot[0].hi=5;assert(!armAtCurrent(63));off();assert(scs::writes==0);
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;g_slot[0].lo=4090;g_slot[0].hi=5;assert(!armAtCurrent(63));off();assert(scs::writes==0);
 for(int range=1023;range<=4095;range+=3072)for(int n=1;n<=7;n++){reset();scs::pf.range=range;scs::pf.family=range==1023?scs::Family::SCS:scs::Family::STS;for(auto &sl:g_slot){sl.lo=381;sl.hi=381+n;}assert(armAtCurrent(63));}
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;scs::autoEnable=true;scs::autoEnableId=4;assert(armAtCurrent(63));assert(g_armed&&scs::implicitEnables==1&&scs::enables==5);for(int goal:scs::goals)assert(goal==381);
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;scs::autoEnable=true;assert(armPrepareCurrent(63));off();assert(scs::implicitEnables==6&&scs::enables==0);
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;scs::autoEnable=true;scs::drift=true;assert(!armAtCurrent(63));off();assert(strstr(armFailure(),"postwrite_moved"));
 reset();scs::configReads=0;ArmCheck merged;assert(inspectArmSlot(0,merged)&&scs::configReads==1&&merged.minimum==20&&merged.maximum==1003&&merged.responseLevel==1);scs::configFailed=true;assert(!inspectArmSlot(0,merged)&&!merged.limitsOk&&merged.responseLevel==-1);scs::configFailed=false;
 puts("actual armAtCurrent PASS: SCS/STS, merged SCS config read/failure, off before goals, all goals before enable, readback/profile/calibration/drift/partial-enable rollback");
}
'''
(root/'safe_arm_generated.cpp').write_text(prefix+body+tests,encoding='utf-8')
