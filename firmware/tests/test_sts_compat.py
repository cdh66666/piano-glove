from pathlib import Path
import runpy
r=Path(__file__).resolve().parent
v=runpy.run_path(str(r/'test_bench_diag.py'))
bus=(r.parent/'src/scs_bus.cpp').read_text(encoding='utf-8')
config=bus[bus.index('bool checkedBenchSpeed('):bus.index('bool setTorque(')]
prefix=v['prefix'][:v['prefix'].index('namespace scs{')]
prefix=prefix.replace('maximum=1003','maximum=4095')
prefix+=r'''
namespace scs{
enum class Family{STS,SCS};struct Profile{Family family=Family::STS;bool probed=true;int range=4095;}pf;
const Profile&profile(){return pf;}int posTol(){return pf.family==Family::SCS?6:24;}int lastError(){return 0;}
bool setTorque(uint8_t,bool on){assert(!on);return true;}
uint8_t endian=0,phase=4,resolution=1,mode=0;bool configFail=false,badRead=false;int writes=0,syncCalls=0;uint8_t last[8],saved[7][8];
struct SyncItem{uint8_t id;uint16_t pos,speed;uint8_t acc;};
bool readRegs(uint8_t id,uint8_t a,uint8_t n,uint8_t*d){memset(d,0,n);if(configFail)return false;if(a==2)*d=endian;if(a==18)*d=phase;if(a==30)*d=resolution;if(a==33)*d=mode;if(a==41||a==42){memcpy(d,saved[id]+1,n);if(badRead)d[1]^=1;}return true;}
bool writeRegs(uint8_t id,uint8_t a,const uint8_t*d,uint8_t n){++writes;saved[id][0]=a;memcpy(saved[id]+1,d,n);return true;}
void syncMove(const SyncItem*v,int n,bool raw){assert(raw);++syncCalls;for(int i=0;i<n;i++)benchMotionPayload(pf.family==Family::SCS,v[i].pos,v[i].speed,v[i].acc,saved[v[i].id]);}
'''+config.replace('uint16_t *actual){','uint16_t *actual=nullptr){')+'\n}\n'
tests=r'''
void reset(){now=0;g_armed=g_calibrated=true;g_benchActive=false;g_sweep=g_rate=g_auto=g_demo=false;offline=false;feedbackPosition=100;for(auto &sl:g_slot){sl.lo=50;sl.hi=3000;sl.valid=true;}scs::pf={};scs::endian=0;scs::phase=4;scs::resolution=1;scs::mode=0;scs::configFail=scs::badRead=false;scs::writes=scs::syncCalls=offCalls=0;}
int main(){uint16_t raw;
reset();assert(scs::checkedBenchSpeed(1,8000,raw)&&raw==8000);scs::phase=0;assert(scs::checkedBenchSpeed(1,1000,raw)&&raw==20);assert(scs::checkedBenchSpeed(1,999,raw)&&raw==19);assert(!scs::checkedBenchSpeed(1,49,raw));assert(!scs::checkedBenchSpeed(1,8001,raw));scs::mode=1;assert(!scs::checkedBenchSpeed(1,1000,raw));scs::mode=0;scs::resolution=2;assert(!scs::checkedBenchSpeed(1,1000,raw));scs::resolution=1;scs::endian=1;assert(!scs::checkedBenchSpeed(1,1000,raw));
reset();assert(benchMove(1,2000,1000)&&benchActualSpeed()==1000);const uint8_t expected[]={41,0,208,7,0,0,232,3};assert(!memcmp(scs::saved[1],expected,8));
reset();scs::phase=0;uint16_t targets[]={200,210,220,230,240,250};assert(benchGroup(63,targets,999)&&benchActualSpeed()==950);assert(scs::syncCalls==1&&scs::writes==0);for(int id=1;id<=6;id++){assert(scs::saved[id][0]==41&&scs::saved[id][1]==0&&scs::saved[id][6]==19&&scs::saved[id][7]==0);}
reset();scs::mode=1;assert(!benchGroup(63,targets,1000)&&scs::syncCalls==0&&!g_armed);
reset();targets[5]=3001;assert(!benchGroup(63,targets,1000)&&scs::syncCalls==0);targets[5]=250;
reset();scs::badRead=true;assert(!benchGroup(63,targets,8000)&&!g_armed&&!g_benchActive);
reset();assert(benchMove(1,200,200));now=1199;assert(benchKeep()&&g_benchDeadline==2399);now=2400;assert(!benchKeep()&&!g_armed&&!g_benchActive);now=0;assert(!benchKeep());
puts("STS actual config+BENCH PASS: normalizedphase units, range4095 LE acc/goal/speed, oncegroup, badmode/resolution/endian/readback fail, KEEP cannot revive expired");}
'''
g=(r.parent/'src/glove.cpp').read_text(encoding='utf-8')
keep=g[g.index('bool benchKeep()'):g.index('int mountTarget()')]
(r/'sts_compat_generated.cpp').write_text(prefix+v['safe']+v['bench']+keep+tests,encoding='utf-8')
