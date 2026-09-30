from pathlib import Path
r=Path(__file__).resolve().parent
s=(r.parent/'src/main.cpp').read_text(encoding='utf-8')
a=s.index('  if (strcmp(v, "POSALL") == 0) {')
block=s[a:s.index('  // ---- 舵机级 ----',a)]
assert 'bench_group=1 bench_feedback=1' in s
assert 'cutoff_ms=1200 armed=1 bench_active=1' in s
prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <stdarg.h>
#include <string>
std::string output;int now=0,readDelay=0,off=0;bool active=true,isArmed=true;uint8_t mask=63;
void okf(const char*f,...){char b[256];va_list a;va_start(a,f);vsnprintf(b,sizeof(b),f,a);va_end(a);output=b;}
namespace glove{const int SLOT_COUNT=6;struct Slot{uint8_t id;int last;};Slot slots[6]={{1,0},{2,0},{3,0},{4,0},{5,0},{6,0}};Slot&slot(int s){return slots[s];}uint8_t onlineMask(){return mask;}bool armed(){return isArmed;}bool benchActive(){return active;}void benchTick(){if(active&&now>=1200){active=isArmed=false;++off;}}}
namespace scs{uint16_t positionReadBudget(int n){return n*20;}bool syncReadPos(const uint8_t*,int n,uint16_t*p,uint16_t){now+=readDelay;for(int i=0;i<n;i++)p[i]=100+i;return true;}}
void parser(const char*v){
'''
tests=r'''
}
void reset(){now=0;readDelay=0;active=isArmed=true;mask=63;off=0;output.clear();}
int main(){
reset();parser("POSALL");assert(output=="POSALL 100 101 102 103 104 105 armed=1 bench_active=1");assert(off==0);
reset();now=1195;readDelay=10;parser("POSALL");assert(output=="POSALL 100 101 102 103 104 105 armed=0 bench_active=0");assert(off==1);
reset();mask=0;now=1200;parser("POSALL");assert(output=="POSALL -1 -1 -1 -1 -1 -1 online=0 armed=0 bench_active=0"&&off==1);
reset();active=isArmed=false;parser("POSALL");assert(output.find("armed=0 bench_active=0")!=std::string::npos);
puts("actual POSALL feedback state PASS: fixed six positions, fresh armed/bench state, expiry during reads SAFE, no-online expiry");
}
'''
(r/'bench_feedback_generated.cpp').write_text(prefix+block+tests,encoding='utf-8')
