"""Execute actual bounded upload/chunk/delete guards with fake filesystem I/O."""
from pathlib import Path
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
upload=source[source.index('static String requestController('):source.index('// All library/file handlers')]
delete=source[source.index('static bool deleteScore('):source.index('static String listing(')]
cpp=root/'library_upload_chunks_generated.cpp';exe=root/'library_upload_chunks_generated.exe'
cpp.write_text(r'''
#include "../src/library_controller.h"
#include "../src/library_storage.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <algorithm>
#include <memory>
using String=std::string;
uint32_t now=0;uint32_t millis(){return now;}
struct Web{String token,form;bool hasHeader(const char*){return !token.empty();}String header(const char*){return token;}String arg(const char*){return form;}}web;
bool ready=true,running=false;String failure="none",owner="none",controller,uploadOwner="none",uploadController;
uint32_t expectedBytes=0,received=0,uploadLast=0;int uploadSlot=0,cachedCount=1;
struct Metadata{bool valid=false;}meta[101];
constexpr int FILE_WRITE=1;
bool failWrite=false;std::shared_ptr<std::vector<uint8_t>>staging;
struct File{
 bool opened=false;
 explicit operator bool()const{return opened;}
 void close(){opened=false;}
 size_t write(const uint8_t*p,size_t n){if(!opened||failWrite)return 0;staging->insert(staging->end(),p,p+n);return n;}
}incoming;
struct MockFS{
 uint32_t total=1318001,used=731916;bool oldSlot=true;
 uint32_t totalBytes(){return total;}uint32_t usedBytes(){return used;}
 File open(const char*,int){staging=std::make_shared<std::vector<uint8_t>>();File f;f.opened=true;return f;}
 bool remove(String name){if(name=="/upload.tmp"){staging.reset();return true;}if(name=="/s1.pgc"){oldSlot=false;return true;}return false;}
}SPIFFS;
String path(int slot){return "/s"+std::to_string(slot)+".pgc";}
bool validSlot(int slot){return slot>=1&&slot<=100;}
''' + upload + delete + r'''
int main(){
 web.token="page-a";assert(startUpload(1,16128,"wifi"));assert(uploadController=="page-a"&&received==0&&expectedBytes==16128);
 uint8_t bytes[384]={};now=15000;assert(chunk(bytes,384)&&received==384&&uploadLast==15000&&staging->size()==384);
 web.token="page-b";assert(!ownerMatches("wifi")&&failure=="controller_mismatch"&&received==384&&incoming);
 assert(!ownerMatches("usb")&&failure=="upload_owned_by_other_transport"&&received==384);
 meta[1].valid=true;assert(!deleteScore(1)&&failure=="upload_active_finish_or_abort_first"&&SPIFFS.oldSlot&&cachedCount==1);
 web.token="page-a";assert(ownerMatches("wifi"));for(int i=0;i<41;++i){++now;assert(chunk(bytes,384));}assert(received==16128&&staging->size()==16128);
 assert(!chunk(bytes,1)&&failure=="upload_chunk_bounds"&&!incoming&&uploadSlot==0&&SPIFFS.oldSlot);
 assert(!chunk(bytes,384)&&failure=="upload_not_started");
 assert(startUpload(1,144,"wifi"));failWrite=true;assert(!chunk(bytes,144)&&failure=="upload_write_failed"&&!incoming&&SPIFFS.oldSlot);failWrite=false;
 assert(startUpload(1,144,"wifi"));assert(!chunk(bytes,0)&&failure=="upload_chunk_bounds"&&!incoming&&SPIFFS.oldSlot);
 SPIFFS.used=SPIFFS.total-librarystorage::stagingSpace(16128)+1;assert(!startUpload(1,16128,"wifi")&&failure=="storage_full"&&!incoming&&SPIFFS.oldSlot);
 SPIFFS.used=SPIFFS.total-librarystorage::stagingSpace(16128);assert(startUpload(1,16128,"wifi"));abortUpload();
 running=true;assert(!deleteScore(1)&&failure=="motion_busy"&&SPIFFS.oldSlot);running=false;
 assert(deleteScore(1)&&!SPIFFS.oldSlot&&cachedCount==0&&!meta[1].valid);
 puts("PASS actual upload/chunk/delete: 42 bounded chunks reconstruct 16128 B; per-page/transport guards preserve staged bytes; delete blocked during upload; overflow/zero/write failure abort staging and preserve old slot; exact reservation boundary");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)
