from pathlib import Path
r=Path(__file__).resolve().parent;s=(r.parent/'src/main.cpp').read_text(encoding='utf-8')
fmt=s[s.index('static void sayf('):s.index('static void okf(')]
cmd=s[s.index('static void cmdInfo()'):s.index('static void cmdStatusAll()')]
prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <assert.h>
#include <string>
std::string output;struct Logger{void println(const char*s){output=s;}}Serial;
const char*FW_ID="PIANO_GLOVE_2",*FW_VER="2.2.4",*g_enrollPhase="OFF";bool g_enroll=false;int g_enrollNext=1;
int bitcount(uint8_t){return 6;}
namespace scs{enum class Family{SCS,STS};struct Profile{Family family=Family::STS;int range=4095;bool probed=true;}pf;const Profile&profile(){return pf;}const char*familyName(Family f){return f==Family::STS?"STS":"SCS";}}
namespace glove{bool calibrated(){return true;}bool armed(){return false;}bool autoActive(){return false;}bool sweepActive(){return false;}uint8_t onlineMask(){return 63;}int mountTarget(){return scs::pf.family==scs::Family::STS?2048:512;}int mountSpeed(){return scs::pf.family==scs::Family::STS?800:200;}uint32_t originEpoch(){return 1234567890;}}
'''
tests=r'''
int main(){cmdInfo();assert(output.size()>384&&output.size()<1024);assert(output.find("bench_default_speed=8000")!=std::string::npos&&output.find("motion_speed_default=8000")!=std::string::npos);assert(output.find("bench_speed_max=8000")!=std::string::npos&&output.find("origin_epoch=1234567890")!=std::string::npos&&output.find("mount_target=2048 mount_speed=800")!=std::string::npos);scs::pf.family=scs::Family::SCS;scs::pf.range=1023;cmdInfo();assert(output.find("bench_default_speed=1000")!=std::string::npos&&output.find("motion_speed_default=200")!=std::string::npos);assert(output.find("bench_speed_max=1000")!=std::string::npos&&output.find("motion_inset=6")!=std::string::npos);printf("actual formatted INFO PASS: complete capabilities %zu bytes, no384truncation, bothfamily\n",output.size());}
'''
(r/'info_capabilities_generated.cpp').write_text(prefix+fmt+cmd+tests,encoding='utf-8')
