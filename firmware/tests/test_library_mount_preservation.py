"""Native execution of actual blank-partition scan and begin() mount guard."""
from pathlib import Path
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
scan=source[source.index('static bool blankStoragePartition(){'):source.index('static void serviceMotion();')]
begin=source[source.index('void begin(){'):source.index(' if(ready){\n  bool backups')]+ '}\n'
harness='''#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <string>
#include <algorithm>
#include <assert.h>
#include <stdio.h>
using std::min;
struct esp_partition_t {size_t size=4096;} partition;
const int ESP_PARTITION_TYPE_DATA=1,ESP_PARTITION_SUBTYPE_DATA_SPIFFS=2,ESP_OK=0;
uint8_t flash[4096];bool missing=false,readFailed=false,mounted=false,ready=false;
std::string failure;int formats=0,reads=0;
const esp_partition_t*esp_partition_find_first(int,int,const char*){return missing?nullptr:&partition;}
int esp_partition_read(const esp_partition_t*,size_t offset,void*data,size_t size){++reads;if(readFailed)return -1;memcpy(data,flash+offset,size);return ESP_OK;}
void delay(int){}
struct MockFS {bool begin(bool formatOnFail){assert(!formatOnFail);return mounted;}bool format(){++formats;mounted=true;return true;}}SPIFFS;
''' + scan + begin + '''
void reset(){memset(flash,255,sizeof(flash));missing=readFailed=mounted=ready=false;formats=reads=0;failure="none";}
int main(){
 reset();mounted=true;begin();assert(ready&&formats==0&&reads==0);
 reset();begin();assert(ready&&formats==1&&reads==4);
 for(size_t offset:{size_t(0),size_t(1024),size_t(4095)}){reset();flash[offset]=0;begin();assert(!ready&&formats==0&&failure=="storage_mount_failed_preserved");}
 reset();readFailed=true;begin();assert(!ready&&formats==0&&failure=="storage_mount_failed_preserved");
 reset();missing=true;begin();assert(!ready&&formats==0&&reads==0);
 puts("PASS actual flash scan/mount guards: only complete erased partition formats; existing, corrupt, missing or unreadable storage preserved");
}
'''
cpp=root/'library_mount_preservation_generated.cpp'
exe=root/'library_mount_preservation_generated.exe'
cpp.write_text(harness,encoding='utf-8')
vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
environment=os.environ.copy()
assert ' ' not in str(vcvars)
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH'])
assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)
