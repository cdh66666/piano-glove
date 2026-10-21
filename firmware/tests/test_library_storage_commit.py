"""Run actual commit/openScore code with an in-memory File/SPIFFS adapter.

This checks byte integrity and transaction rollback. It does not simulate the
ESP32's SPIFFS GC or prove that a real-board stack overflow has been fixed.
It models writable buffered-stat lag: stored metadata must come from the
reopened, verified file instead of size() before fclose.
"""
from pathlib import Path
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent
source = (root.parent / 'src/device_library.cpp').read_text(encoding='utf-8')
metadata = source[source.index('struct Metadata '):source.index('static char apName')]
scratch = source[source.index('static uint8_t storageReadBuffer'):source.index('static void storageDiagnostics')]
implementation = source[source.index('static bool readExact('):source.index('static String entry(')]
readback = source[source.index('static bool __attribute__((noinline)) readScoreUsb('):source.index('static const char PAGE[]')]
readback = readback.replace('__attribute__((noinline)) ', '')
harness = r'''
#include <stdint.h>
#include <assert.h>
#include <algorithm>
#include <fstream>
#include <iterator>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <stdio.h>
#include "../src/score_format.h"
using String=std::string;
using Bytes=std::vector<uint8_t>;
static bool failCompressedWrite=false;
static bool corruptCompressedWrite=false;
static bool failReadAfterVerification=false;
static constexpr int FILE_READ=0,FILE_WRITE=1;
class File {
 std::shared_ptr<Bytes> data;size_t pos=0,statSize=0;bool opened=false,afterVerification=false,writable=false;String name;
public:
 File()=default;
 File(std::shared_ptr<Bytes> d,String n,bool writeMode=false):data(d),statSize(d?d->size():0),opened(true),writable(writeMode),name(n){}
 explicit operator bool()const{return opened&&bool(data);}
 size_t size()const{return opened&&data?(writable?statSize:data->size()):0;}
 size_t position()const{return pos;}
 size_t read(uint8_t*out,size_t n){if(!opened||(failReadAfterVerification&&afterVerification))return 0;n=std::min(n,size()-pos);memcpy(out,data->data()+pos,n);pos+=n;return n;}
 size_t write(const uint8_t*in,size_t n){if(!opened||(failCompressedWrite&&name=="/compressed.tmp"))return 0;if(pos+n>data->size())data->resize(pos+n);memcpy(data->data()+pos,in,n);pos+=n;if(corruptCompressedWrite&&name=="/compressed.tmp"&&n)(*data)[pos-1]^=1;return n;}
 bool seek(size_t p){if(!opened||p>size())return false;pos=p;afterVerification=p==132;return true;}
 void close(){opened=false;}
};
struct MockSPIFFS {
 std::map<String,std::shared_ptr<Bytes>> files;
 bool failFinalRename=false,corruptFinalWrite=false,failBackupRename=false,failRollbackRename=false,failBackupRemove=false,failPrimaryRemove=false;
 File open(String name,int mode){if(mode==FILE_WRITE)files[name]=std::make_shared<Bytes>();auto i=files.find(name);return i==files.end()?File():File(i->second,name,mode==FILE_WRITE);}
 bool remove(String name){if((failBackupRemove&&name=="/s100.pgc.bak")||(failPrimaryRemove&&name=="/s100.pgc"))return false;return files.erase(name)>0;}
 bool exists(String name){return files.count(name)!=0;}
 bool rename(String from,String to){if(!exists(from))return false;if(failFinalRename&&from=="/compressed.tmp")return false;if(failBackupRename&&from=="/s100.pgc")return false;if(failRollbackRename&&from=="/s100.pgc.bak")return false;if(corruptFinalWrite&&from=="/compressed.tmp")(*files[from])[files[from]->size()-2]^=1;files[to]=files[from];files.erase(from);return true;}
} SPIFFS;
static File incoming,playing;
static int uploadSlot=0;
static uint32_t received=0,expectedBytes=0;
static String failure="none";
static String path(int slot){return "/s"+std::to_string(slot)+".pgc";}
static bool validSlot(int slot){return slot>=1&&slot<=100;}
static void delay(int){}
static void storageDiagnostics(const char*){}
static void abortUpload(){if(incoming)incoming.close();SPIFFS.remove("/upload.tmp");uploadSlot=0;received=expectedBytes=0;}
static bool scoreReadAllowed(){return true;}
struct SerialMock{int rows=0;void printf(const char*,...){++rows;}}Serial;
''' + metadata + scratch + implementation + readback + r'''
static Bytes load(const char*path){std::ifstream in(path,std::ios::binary);return Bytes(std::istreambuf_iterator<char>(in),{});}
static void upload(Bytes bytes,uint32_t expected=0){incoming=SPIFFS.open("/upload.tmp",FILE_WRITE);assert(incoming.write(bytes.data(),bytes.size())==bytes.size());uploadSlot=100;received=bytes.size();expectedBytes=expected?expected:received;}
static Bytes readBack(int slot){File file;uint8_t h[128];assert(openScore(slot,file,h));Bytes out(h,h+128);EventReader reader(file,storageReadBuffer,sizeof(storageReadBuffer));uint32_t prev=0;pgl::Event event;uint8_t bytes[16];for(uint32_t i=0;i<pgl::u32(h+8);++i){assert(reader.event(prev,event));pgl::bytes(event,bytes);out.insert(out.end(),bytes,bytes+16);prev=event.t;}assert(reader.exhausted());return out;}
int main(int argc,char**argv){
 assert(argc==4);Bytes original=load(argv[1]),replacement=load(argv[2]),handset=load(argv[3]);assert(original.size()==16128&&replacement.size()==16128&&handset.size()==544);
 File buffered=SPIFFS.open("/buffered-stat",FILE_WRITE);uint8_t small[4]={};assert(buffered.write(small,4)==4&&buffered.position()==4&&buffered.size()==0);buffered.close();File persisted=SPIFFS.open("/buffered-stat",FILE_READ);assert(persisted.size()==4);persisted.close();SPIFFS.remove("/buffered-stat");
 upload(handset);assert(commit());assert(readBack(100)==handset&&meta[100].stored==311&&meta[100].notes==26&&meta[100].bytes==544);File cold;uint8_t coldHeader[128];assert(openScore(100,cold,coldHeader));uint32_t coldSize=cold.size();cold.close();assert(coldSize==meta[100].stored);
 upload(original);assert(commit());assert(cachedCount==1);assert(readBack(100)==original);assert(meta[100].bytes==original.size());assert(meta[100].stored==SPIFFS.files["/s100.pgc"]->size()&&meta[100].stored>132);assert(!SPIFFS.exists("/upload.tmp"));assert(!SPIFFS.exists("/compressed.tmp"));
 Serial.rows=0;assert(readScoreUsb(100)&&Serial.rows==1001);failReadAfterVerification=true;Serial.rows=0;assert(!readScoreUsb(100)&&failure=="score_read_error"&&Serial.rows==1);failReadAfterVerification=false;
 for(int i=0;i<20;++i){const Bytes&b=i%2?original:replacement;upload(b);assert(commit());assert(readBack(100)==b);assert(meta[100].stored==SPIFFS.files["/s100.pgc"]->size()&&meta[100].stored>132);assert(cachedCount==1);assert(!SPIFFS.exists("/s100.pgc.bak"));}
 upload(original);assert(commit());
 Bytes corrupt=replacement;corrupt.back()^=1;upload(corrupt);assert(!commit());assert(failure=="invalid_pgl_crc_or_events");assert(readBack(100)==original);
 Bytes truncated(replacement.begin(),replacement.end()-1);upload(truncated,replacement.size());assert(!commit());assert(failure=="incomplete");assert(readBack(100)==original);
 upload(replacement);failCompressedWrite=true;assert(!commit());failCompressedWrite=false;assert(failure=="storage_full_or_write_failed");assert(readBack(100)==original);
 upload(replacement);corruptCompressedWrite=true;assert(!commit());corruptCompressedWrite=false;assert(failure=="compressed_staging_crc_failed");assert(readBack(100)==original);
 upload(replacement);SPIFFS.failBackupRename=true;assert(!commit());SPIFFS.failBackupRename=false;assert(failure=="replace_backup_failed");assert(readBack(100)==original);assert(!SPIFFS.exists("/compressed.tmp"));
 upload(replacement);SPIFFS.failFinalRename=true;assert(!commit());SPIFFS.failFinalRename=false;assert(failure=="commit_rename_failed");assert(readBack(100)==original);
 upload(replacement);SPIFFS.corruptFinalWrite=true;assert(!commit());SPIFFS.corruptFinalWrite=false;assert(failure=="compressed_readback_crc_failed");assert(readBack(100)==original);
 assert(cachedCount==1);assert(!SPIFFS.exists("/s100.pgc.bak"));assert(!SPIFFS.exists("/upload.tmp"));
 upload(replacement);SPIFFS.failFinalRename=SPIFFS.failRollbackRename=true;assert(!commit());SPIFFS.failFinalRename=SPIFFS.failRollbackRename=false;assert(failure=="commit_rollback_failed");assert(!meta[100].valid&&cachedCount==0&&SPIFFS.exists("/s100.pgc.bak"));assert(recoverStoredSlot(100));assert(readBack(100)==original);
 uint8_t h[128];File restored;assert(openScore(100,restored,h));cacheEntry(100,h,restored.size());restored.close();
 SPIFFS.files["/s100.pgc.bak"]=std::make_shared<Bytes>(*SPIFFS.files["/s100.pgc"]);
 SPIFFS.failBackupRemove=true;upload(replacement);assert(!commit());SPIFFS.failBackupRemove=false;assert(failure=="storage_recovery_required");assert(readBack(100)==original);assert(recoverStoredSlot(100));
 SPIFFS.files["/s100.pgc.bak"]=std::make_shared<Bytes>(*SPIFFS.files["/s100.pgc"]);
 (*SPIFFS.files["/s100.pgc"])[0]^=1;SPIFFS.failPrimaryRemove=true;assert(!recoverStoredSlot(100));SPIFFS.failPrimaryRemove=false;assert(failure=="storage_recovery_required"&&SPIFFS.exists("/s100.pgc.bak"));assert(recoverStoredSlot(100));assert(readBack(100)==original);
 SPIFFS.files["/s100.pgc.bak"]=std::make_shared<Bytes>(*SPIFFS.files["/s100.pgc"]);
 (*SPIFFS.files["/s100.pgc.bak"])[0]^=1;(*SPIFFS.files["/s100.pgc"])[0]^=1;
 assert(!recoverStoredSlot(100)&&failure=="storage_backup_corrupt_preserved");assert(SPIFFS.exists("/s100.pgc")&&SPIFFS.exists("/s100.pgc.bak"));
 puts("PASS actual commit/openScore/recovery with buffered-stat lag: real slot4 PGL544B/26notes stores311B with warm/cold metadata equal; 1000-note byte-exact roundtrip; 20 replacements exact stored sizes; CRC/truncation/write/staging/backup/final-rename/readback failures preserve prior slot; rollback failure invalidates cache and valid journal recovers; remove failure/corrupt backup preserve evidence");
}
'''
cpp = root / 'library_storage_commit_generated.cpp'
exe = root / 'library_storage_commit_generated.exe'
cpp.write_text(harness, encoding='utf-8')
vcvars = Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
environment = os.environ.copy()
for line in subprocess.check_output(['cmd', '/d', '/c', f'call {vcvars} >nul && set'], encoding='utf-8', errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key, value = line.split('=', 1)
        environment[key.upper()] = value
compiler = shutil.which('cl.exe', path=environment['PATH'])
assert compiler
subprocess.run([compiler, '/nologo', '/EHsc', '/std:c++17', str(cpp), '/Fe:' + str(exe)], cwd=root, env=environment, check=True)
fixtures = root.parents[2] / 'evidence/software-20261010/fixtures'
handset_source = root.parents[2] / 'evidence/software-dev-20261011/integration/examples/波尔卡右手原谱六小节.pgl'
handset = root.parents[2] / 'evidence/software-dev-20261011/firmware/fixture-slot4-26-notes.pgl'
shutil.copyfile(handset_source, handset)
subprocess.run([str(exe), str(fixtures / 'capacity-001.pgl'), str(fixtures / 'capacity-100.pgl'), str(handset)], check=True)
