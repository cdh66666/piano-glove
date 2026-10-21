"""Execute actual atomic LIB RELEASE helper and command dispatch without I/O."""
from pathlib import Path
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
helper=source[source.index('static void releaseUsb(){'):source.index('bool command(int n,char**t){')]
dispatch=source[source.index('bool command(int n,char**t){'):source.index(' if(action=="TEST"')]+ 'return false;}\n'
assert 'release_usb=1' in source
assert 'else if(action=="STOP"){stop();glove::safe();ok=true;}' in source
cpp=root/'library_usb_release_generated.cpp';exe=root/'library_usb_release_generated.exe'
cpp.write_text(r'''
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <string>
#include <vector>
using String=std::string;
bool running=false,initializing=false;String owner="none",failure="none",controller="phone-tab";
uint32_t keepAt=42;uint8_t mask=21;int stops=0,safes=0;std::vector<std::string>order;
struct SerialMock{String last;void println(const char*line){last=line;order.push_back("reply");}}Serial;
void stop(){++stops;order.push_back("stop");running=initializing=false;owner="none";controller="";failure="stopped";}
namespace glove{void safe(){++safes;order.push_back("safe");}}
''' + helper + dispatch + r'''
void reset(const char*who,bool active,bool preparing){owner=who;running=active;initializing=preparing;controller="phone-tab";keepAt=42;mask=21;failure="none";stops=safes=0;order.clear();Serial.last="";}
void invoke(){char a[]="LIB",b[]="RELEASE";char*t[]={a,b};assert(command(2,t));}
int main(){
 for(auto phase:{0,1,2}){reset("wifi",phase!=2,phase!=0);invoke();assert(stops==0&&safes==0&&owner=="wifi"&&controller=="phone-tab"&&failure=="none"&&keepAt==42&&mask==21);assert(running==(phase!=2)&&initializing==(phase!=0));assert(Serial.last=="OK LIB RELEASE skipped=1 owner=wifi"&&order==std::vector<std::string>{"reply"});}
 for(const char*who:{"usb","none","legacy"})for(bool active:{false,true})for(bool preparing:{false,true}){reset(who,active,preparing);invoke();assert(stops==1&&safes==1&&!running&&!initializing&&owner=="none"&&controller.empty());assert(Serial.last=="OK LIB RELEASE skipped=0"&&order==std::vector<std::string>({"stop","safe","reply"}));}
 reset("wifi",false,false);invoke();assert(stops==1&&safes==1); // Stale inactive ownership doesn't leave legacy torque on.
 reset("wifi",true,true);char a[]="LIB",b[]="RELEASE",extra[]="extra";char*t[]={a,b,extra};assert(command(3,t)&&stops==0&&safes==0&&Serial.last=="ERR LIB RELEASE usage");
 reset("wifi",true,true);char other[]="NOT_LIB";char*u[]={other,b};assert(!command(2,u)&&stops==0&&safes==0);
 puts("PASS actual atomic USB RELEASE: active/initializing/preparation-only WiFi gets skipped1 without stop/SAFE/lease/mask/controller mutation; USB/idle/legacy stop->SAFE->ACK once; malformed request doesn't alter motion; explicit LIB STOP remains global and INFO advertises release_usb1");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)
