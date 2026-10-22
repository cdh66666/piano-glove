"""Execute actual controller identity/keep/HTTP parameter guards, without I/O."""
from pathlib import Path
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent
source = (root.parent / 'src/device_library.cpp').read_text(encoding='utf-8')
helpers = source[source.index('static String requestController('):source.index('static void abortUpload(')]
keep = source[source.index('static bool keep('):source.index('static void tickScoreTimeline();')]
integer = source[source.index('static bool httpInteger('):source.index('static bool scoreReadAllowed(')]
cpp = root / 'library_controller_generated.cpp'
exe = root / 'library_controller_generated.exe'
cpp.write_text(r'''
#include "../src/library_controller.h"
#include <stdint.h>
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string>
using String=std::string;
uint32_t now=100,keepAt=0;uint32_t millis(){return now;}
bool running=false;String owner="none",controller,failure="none";
struct Web {String token,form,value;bool hasHeader(const char*){return !token.empty();}String header(const char*){return token;}String arg(const char*name){return std::string(name)=="controller"?form:value;}}web;
''' + helpers + keep + integer + r'''
int main(){
 assert(librarycontroller::leaseTimeoutMs(true,true)==5000);
 for(bool wireless:{false,true})for(bool score:{false,true}){
  const uint32_t lease=wireless&&score?5000:2000;
  assert(!librarycontroller::leaseExpired(100+lease,100,wireless,score));
  assert(librarycontroller::leaseExpired(101+lease,100,wireless,score));
  assert(!librarycontroller::leaseExpired(lease-4,0xfffffffcu,wireless,score));
  assert(librarycontroller::leaseExpired(lease-3,0xfffffffcu,wireless,score));
 }
 for(const char*token:{"","A","page-42_abc"})assert(librarycontroller::validToken(token,strlen(token)));
 for(const char*token:{"a b","a\nb","a:b","a/b","a\"b"})assert(!librarycontroller::validToken(token,strlen(token)));
 std::string limit(64,'a'),oversize(65,'a');assert(librarycontroller::validToken(limit.c_str(),64));assert(!librarycontroller::validToken(oversize.c_str(),65));
 assert(keep("wifi")&&keepAt==0);
 running=true;owner="wifi";controller="page-a";web.token="page-a";
 assert(keep("wifi")&&keepAt==100);
 now=500;web.token="page-b";assert(!keep("wifi")&&keepAt==100&&failure=="controller_mismatch");
 assert(!keep("usb")&&keepAt==100);
 web.token="";assert(!keep("wifi")&&keepAt==100);web.form="page-a";assert(keep("wifi")&&keepAt==500);
 web.token="page-b";assert(!keep("wifi")&&keepAt==500); // Header takes precedence over beacon fallback.
 web.token=oversize;assert(!keep("wifi")&&failure=="controller_token_invalid"&&keepAt==500);
 web.token="";web.form="";controller="";assert(keep("wifi")); // Legacy page can only control legacy ownership.
 controller="page-a";assert(!motionOwnerMatches("wifi"));
 running=false;assert(motionOwnerMatches("usb"));assert(motionOwnerMatches("wifi"));
 int value=-1;web.value="100";assert(httpInteger("tempo",50,1000,value)&&value==100);
 for(const char*invalid:{"","garbage","100junk","-1","1001","999999999999999999999999"}){web.value=invalid;value=-1;assert(!httpInteger("tempo",50,1000,value)&&value==-1&&failure=="request_parameter_invalid name=tempo");}
 web.value=String("100\0junk",8);assert(!httpInteger("tempo",50,1000,value));
 puts("PASS actual controller/KEEP/parser: per-page ownership, no mismatched keep extension, transport separation, beacon fallback, header precedence, legacy isolation, token whitelist/length, malformed parameters leave destination untouched");
}
''', encoding='utf-8')
environment = os.environ.copy()
vcvars = Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd', '/d', '/c', f'call {vcvars} >nul && set'], encoding='utf-8', errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key, value = line.split('=', 1)
        environment[key.upper()] = value
compiler = shutil.which('cl.exe', path=environment['PATH'])
assert compiler
subprocess.run([compiler, '/nologo', '/EHsc', '/std:c++17', str(cpp), '/Fe:' + str(exe)], cwd=root, env=environment, check=True)
subprocess.run([str(exe)], check=True)
