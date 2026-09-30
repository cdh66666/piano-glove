from pathlib import Path
r=Path(__file__).resolve().parent;s=(r.parent/'src/glove.cpp').read_text(encoding='utf-8')
body=s[s.index('static char g_originFailure'):s.index('void load() {')]
prefix=r'''
#include "../src/profile_limits.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <string>
bool invalid=false,persistFail=false,neverCenters=false;int pendingFrames=0;int writes=0,failed=-1,narrow=-1,mixed=-1;uint8_t doneMask=0;int positions[6];
uint32_t now=0;uint32_t millis(){return now;}void delay(uint32_t n){now+=n;}void safe(){}void invalidateCalibration(){invalid=true;}
struct Prefs{size_t putBytes(const char*,const void*,size_t n){assert(writes==0);return persistFail?0:n;}size_t putUInt(const char*,uint32_t){return 4;}void putUShort(const char*,uint16_t){}void putUChar(const char*k,uint8_t v){if(!strcmp(k,"origin_mask"))doneMask=v;}}prefs;
struct Logger{void printf(const char*,...){}}Serial;
namespace scs{enum class Family{SCS,STS};struct Profile{Family family=Family::STS;bool probed=true;int range=4095;}pf;const Profile&profile(){return pf;}int lastError(){return 0;}
struct Feedback{bool ok=true;int pos=100;};
bool checkedBenchSpeed(uint8_t,uint16_t,uint16_t &raw){raw=1000;return true;}
bool readRegs(uint8_t id,uint8_t a,uint8_t n,uint8_t*d){memset(d,0,n);if(a==3){d[0]=id==mixed?6:5;d[1]=4;}if(a==9){d[2]=id==narrow?0:255;d[3]=15;}if(a==31){d[0]=id;d[1]=1;}return true;}
bool readFeedback(uint8_t id,Feedback&fb){fb.pos=positions[id-1];if(writes>0&&(neverCenters||pendingFrames>0)){fb.pos=100;if(pendingFrames>0)--pendingFrames;}return true;}
bool writeRegs(uint8_t id,uint8_t a,const uint8_t*d,uint8_t n){assert(invalid&&a==40&&n==1&&*d==128);++writes;positions[id-1]=2048;return id!=failed;}}
'''
tests=r'''
void reset(){now=0;neverCenters=false;pendingFrames=0;invalid=persistFail=false;writes=0;failed=narrow=mixed=-1;doneMask=0;scs::pf={};for(int &p:positions)p=100;}
int main(){reset();assert(calOrigin()&&invalid&&writes==6&&doneMask==63);for(int p:positions)assert(p==2048);
reset();narrow=6;assert(!calOrigin()&&!invalid&&writes==0&&strstr(originFailure(),"full_hardware_limits_required"));
reset();mixed=6;assert(!calOrigin()&&!invalid&&writes==0);
reset();persistFail=true;assert(!calOrigin()&&!invalid&&writes==0&&strstr(originFailure(),"persist_failed"));
reset();failed=3;assert(!calOrigin()&&invalid&&writes==3&&doneMask==3&&strstr(originFailure(),"id=3"));
reset();pendingFrames=3;assert(calOrigin()&&writes==6&&now==15);
reset();neverCenters=true;assert(!calOrigin()&&writes==1&&now==200&&invalid);
reset();scs::pf.family=scs::Family::SCS;assert(!calOrigin()&&writes==0&&!invalid);
puts("STS ORIGIN actual PASS: full6preflight, persistbackup before invalidation/write, onlytorque128 noMOVE, sixreadbacks, narrow/mixed/persist/partialfailure safe");}
'''
(r/'sts_origin_generated.cpp').write_text(prefix+body+tests,encoding='utf-8')
