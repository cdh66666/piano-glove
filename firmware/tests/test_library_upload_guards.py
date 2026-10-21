"""Execute the real C++ upload/prepare guard prefixes with fake ownership state.

This verifies command ownership, not SPIFFS or physical movement. Full storage
and transport integrity require the separate on-device reports.
"""
from pathlib import Path
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent
source = (root.parent / 'src/device_library.cpp').read_text(encoding='utf-8')
owner = source[source.index('static bool ownerMatches('):source.index('static bool startUpload(')]
controller = source[source.index('static String requestController('):source.index('static void abortUpload(')]
start = source[source.index('static bool startUpload('):source.index('abortUpload();uint32_t free=')]
start += 'abortUpload();return true;}\n'
prepare = source[source.index('static bool prepare(){'):source.index(' if(limitsSaved){stop(')]
prepare += 'return true;}\n'
harness = '''#include <string>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include "../src/library_controller.h"
#include "../src/library_storage.h"
using String=std::string;
uint32_t millis(){return 0;}
static uint8_t positionValidMask=0;
static bool ready=true,running=false,incoming=false;
static int uploadSlot=0,aborts=0;
static String uploadOwner="none",uploadController,owner="none",controller,failure="none";
struct Web {String token,form;bool hasHeader(const char*){return !token.empty();}String header(const char*){return token;}String arg(const char*){return form;}}web;
static bool validSlot(int s){return s>=1&&s<=100;}
static void abortUpload(){++aborts;incoming=false;uploadSlot=0;uploadOwner="none";uploadController="";}
''' + controller + owner + start + prepare + '''
int main(){
 assert(startUpload(1,144,"usb")&&aborts==1);
 incoming=true;uploadSlot=7;uploadOwner="usb";
 assert(!startUpload(2,144,"wifi"));assert(aborts==1&&incoming&&uploadSlot==7);
 assert(failure=="upload_owned_by_other_transport");
 assert(!ownerMatches("wifi"));assert(ownerMatches("usb"));
 assert(!prepare());assert(failure=="upload_active_finish_or_abort_first");
 incoming=false;assert(!prepare());
 incoming=true;uploadOwner="wifi";
 assert(!startUpload(2,144,"usb"));assert(aborts==1);
 assert(!ownerMatches("usb"));assert(ownerMatches("wifi"));
 assert(startUpload(2,144,"wifi")&&aborts==2);
 assert(prepare());
 incoming=true;uploadSlot=2;uploadOwner="wifi";uploadController="page-a";web.token="page-b";
 assert(!startUpload(3,144,"wifi")&&aborts==2&&uploadSlot==2);
 assert(failure=="controller_mismatch");
 web.token="page-a";assert(startUpload(3,144,"wifi")&&aborts==3);
 web.token=std::string(65,'a');assert(!startUpload(3,144,"wifi")&&aborts==3&&failure=="controller_token_invalid");web.token="";
 running=true;assert(!startUpload(1,144,"usb")&&aborts==3&&failure=="motion_busy");running=false;
 ready=false;assert(!startUpload(1,144,"usb")&&aborts==3&&failure=="storage_not_ready");ready=true;
 for(int s:{0,101})assert(!startUpload(s,144,"usb")&&aborts==3&&failure=="slot_out_of_range");
 for(int bytes:{143,145,960129})assert(!startUpload(1,bytes,"usb")&&aborts==3&&failure=="pgl_size_invalid");
 assert(librarystorage::stagingSpace(16128)==36452);
 assert(100*(132+1000*12)+librarystorage::stagingSpace(16128)<1318001);
 puts("PASS actual upload guards: controller/transport mismatch cannot abort another uploader; active/slot-only upload blocks prepare; precise bounds/readiness; 100x1000 worst-case size reservation retains old slot");
}
'''
cpp = root / 'library_upload_guards_generated.cpp'
exe = root / 'library_upload_guards_generated.exe'
cpp.write_text(harness,encoding='utf-8')
vcvars = Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
environment = os.environ.copy()
assert ' ' not in str(vcvars)
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1)
        environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH'])
assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)
