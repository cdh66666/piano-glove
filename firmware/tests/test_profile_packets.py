from pathlib import Path
root=Path(__file__).resolve().parent
src=(root.parent/'src/scs_bus.cpp').read_text(encoding='utf-8')
parts=[]
for begin,end in [('bool readFeedback(', 'bool setTorque('),('void syncMove(', 'int syncReadPos('),('bool probeProfile(', 'int posTol('),('int syncReadPos(', '// ---------------- 型号 / 位置量程')]:
    parts.append(src[src.index(begin):src.index(end)])
prefix=r'''
#include "../src/profile_limits.h"
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <vector>
#include <array>
enum class Family{UNKNOWN,STS,SCS};
struct Profile{Family family=Family::STS;uint16_t range=4095,model=0,minAng=0,maxAng=0;bool probed=false;} pf;
const Profile &profile(){return pf;}
struct Feedback{bool ok=false;int16_t pos=-1,speed=0,load=0,current=0;uint8_t voltage=0,temp=0,moving=0,mode=0;};
struct SyncItem{uint8_t id;uint16_t pos,speed;uint8_t acc;};void syncMove(const SyncItem*,int,bool benchRaw=false);bool checkedBenchSpeed(uint8_t,uint16_t,uint16_t &,uint16_t *actual=nullptr);
const int RESP_TIMEOUT_MS=20,INST_SYNC_READ=0x82;
const int PRES_BLOCK_LEN=15,REG_PRES_POS_L=56,RESP_BUF=96,INST_WRITE=3,INST_SYNC_WRITE=0x83,BROADCAST_ID=254,REG_MODEL_L=3,REG_MIN_ANGLE_L=9,REG_MAX_ANGLE_L=11;
uint8_t last[80],lastN=0,lastReadSize=0;
uint32_t clockNow=0;int readCount=0,failedId=-1;bool invalidPosition=false;
uint32_t millis(){return clockNow;}int lastError(){return 0;}
int g_lastErr=0;struct Stats{int tx=0;}g_stats;
struct Bus{int available(){return 0;}int read(){return 0;}void write(uint8_t*,uint8_t){}void flush(){}}bus;
uint8_t build(uint8_t,uint8_t,uint8_t*,uint8_t,uint8_t*){return 0;}
void eatEcho(uint8_t){}std::vector<std::array<uint8_t,8>> packets;size_t packetIndex=0;bool readPacket(int,uint8_t*r,int&n,uint16_t){if(packetIndex>=packets.size())return false;auto &p=packets[packetIndex++];memcpy(r,p.data(),8);n=8;return true;}
uint8_t modelBytes[2]={5,4},minBytes[2]={0,20},maxBytes[2]={3,235};
bool sendRecv(uint8_t,uint8_t,const uint8_t*p,uint8_t n,uint8_t*,int&,bool){memcpy(last,p,n);lastN=n;return true;}
bool readRegs(uint8_t id,uint8_t addr,uint8_t n,uint8_t*out,uint16_t timeout=20){
 ++readCount;clockNow+=timeout<5?timeout:5;if(id==failedId)return false;
 memset(out,0,n);lastReadSize=n;
 if(addr==3)memcpy(out,modelBytes,2);
 if(addr==9)memcpy(out,minBytes,2);
 if(addr==11)memcpy(out,maxBytes,2);
 if(addr==56){out[0]=invalidPosition?255:1;out[1]=invalidPosition?255:0x7d;}return true;
}
'''
tests=r'''
int main(){
 uint16_t mn,mx;uint8_t lo[]={0,0},hi[]={255,15};
 assert(identifyLimitEndian(lo,hi,mn,mx)==1&&mx==4095);
 uint8_t slo[]={0,20},shi[]={3,235};assert(identifyLimitEndian(slo,shi,mn,mx)==2&&mn==20&&mx==1003);
 uint8_t tlo[]={100,0},thi[]={184,11};assert(identifyLimitEndian(tlo,thi,mn,mx)==1&&mn==100&&mx==3000);
 uint8_t zero[]={0,0},amb[]={1,0},bad[]={255,255};
 assert(!identifyLimitEndian(zero,zero,mn,mx));assert(!identifyLimitEndian(zero,amb,mn,mx));assert(!identifyLimitEndian(zero,bad,mn,mx));
 Profile actual;assert(probeProfile(6,actual));assert(actual.family==Family::SCS&&actual.minAng==20&&actual.maxAng==1003&&actual.model==0x0504);
 pf=actual;Feedback fb;assert(readFeedback(6,fb,20));assert(fb.pos==381&&lastReadSize==11);
 assert(moveTo(6,381,1200,30));const uint8_t wantS[]={42,1,125,0,0,0,200};assert(lastN==7&&!memcmp(last,wantS,7));
 SyncItem item{6,381,1200,30};syncMove(&item,1);const uint8_t syncS[]={42,6,6,1,125,0,0,0,200};assert(lastN==9&&!memcmp(last,syncS,9));
 SyncItem grouped[6]={{1,100,1000,0},{2,200,1000,0},{3,300,1000,0},{4,400,1000,0},{5,500,1000,0},{6,600,1000,0}};syncMove(grouped,6,true);assert(lastN==44&&last[0]==42&&last[1]==6);for(int i=0;i<6;i++){int k=2+7*i;assert(last[k]==i+1&&last[k+1]==(grouped[i].pos>>8)&&last[k+2]==(grouped[i].pos&255)&&last[k+3]==0&&last[k+4]==0&&last[k+5]==3&&last[k+6]==232);}lastN=0;grouped[5].id=5;syncMove(grouped,6,true);assert(lastN==0&&g_lastErr!=0);grouped[5].id=6;
 pf.family=Family::STS;pf.range=4095;lastN=0;syncMove(grouped,6,true);assert(lastN==50&&last[0]==41&&last[1]==7);
 pf.family=Family::STS;assert(moveTo(6,381,1200,30));const uint8_t wantT[]={41,30,125,1,0,0,176,4};assert(lastN==8&&!memcmp(last,wantT,8));
 syncMove(&item,1);const uint8_t syncT[]={41,7,6,30,125,1,0,0,176,4};assert(lastN==10&&!memcmp(last,syncT,10));
 assert(!readFeedback(6,fb,20));assert(fb.pos==32001&&lastReadSize==15);
 pf.family=Family::SCS;pf.range=1023;uint8_t ids[]={1,2,3,4,5,6};uint16_t pos[6];
 clockNow=0;readCount=0;assert(positionReadBudget(6)==120);assert(syncReadPos(ids,6,pos,120)==6);assert(readCount==6);for(auto p:pos)assert(p==381);
 failedId=2;assert(syncReadPos(ids,6,pos,120)==5&&pos[1]==65535);failedId=-1;
 invalidPosition=true;assert(syncReadPos(ids,6,pos,120)==0);invalidPosition=false;
 clockNow=0;readCount=0;assert(syncReadPos(ids,6,pos,8)==2);assert(clockNow==8&&readCount==2);
 pf.family=Family::STS;pf.range=4095;assert(positionReadBudget(6)==8);
 packets={{{255,255,1,4,0,0,8,0}},{{255,255,2,4,1,0,8,0}},{{255,255,3,4,0,0,32,0}},{{255,255,4,4,0,1,8,0}}};packetIndex=0;assert(syncReadPos(ids,6,pos,8)==2&&pos[0]==2048&&pos[1]==65535&&pos[2]==65535&&pos[3]==2049);
 puts("actual profile/feedback/move/syncMove PASS: ID6 raw0504, custom20..1003, unique endian only, SC09 BE and unchanged STS LE");
}
'''
(root/'profile_packets_generated.cpp').write_text(prefix+'\n'.join(parts)+tests,encoding='utf-8')
