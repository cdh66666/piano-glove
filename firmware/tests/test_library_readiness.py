"""Execute the actual hotspot status serializer; no Wi-Fi or servo I/O."""
from pathlib import Path
import json
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
status=source[source.index('static String statusJson(){'):source.index('static void serveScore(){')]
cpp=root/'library_readiness_generated.cpp';exe=root/'library_readiness_generated.exe'
cpp.write_text(r'''
#include "../src/library_storage.h"
#include "../src/library_targets.h"
#include <stdint.h>
#include <string>
#include <iostream>
class String{
 std::string value;
public:
 String(){}String(const char*s):value(s){}String(std::string s):value(s){}String(int n):value(std::to_string(n)){}String(unsigned n):value(std::to_string(n)){}
 String operator+(const String&other)const{return String(value+other.value);}friend String operator+(const char*a,const String&b){return String(std::string(a)+b.value);}
 String&operator+=(const String&other){value+=other.value;return *this;}size_t length()const{return value.size();}void remove(size_t from){value.resize(from);}const char*c_str()const{return value.c_str();}
};
String escape(String s){return s;}String state(){return "{\"active\":false}";}
bool ready=true,running=false,exclusiveBusy=false,incoming=false,offhandTestMode=false;int uploadSlot=0;uint8_t recoveryMask=0,positionValidMask=63;
String controller="page-a",lastStopReason="none";uint32_t lastStopAt=0,lastPrepareMs=0,lastPoseMs=0;
namespace scs{enum class Family{STS,SCS};struct Profile{Family family=Family::STS;}pf;const Profile&profile(){return pf;}}
namespace glove{
 bool cal=true,supported=true,other=false;
 struct Slot{int id;bool valid=true;}slots[6];const Slot&slot(int s){return slots[s];}
 bool calibrated(){return cal;}bool motionCalibrationSupported(){return supported;}bool autoActive(){return other;}bool mountActive(){return false;}bool benchActive(){return false;}bool rateActive(){return false;}bool sweepActive(){return false;}
}
bool calibrationValid(int s){return glove::slots[s].valid;}
''' + status + r'''
int main(){
 for(int i=0;i<6;++i)glove::slots[i].id=i+1;
 std::cout<<statusJson().c_str()<<"\n";
 positionValidMask=0;std::cout<<statusJson().c_str()<<"\n";positionValidMask=63;
 glove::cal=false;std::cout<<statusJson().c_str()<<"\n";glove::cal=true;
 glove::slots[2].id=6;std::cout<<statusJson().c_str()<<"\n";glove::slots[2].id=3;
 glove::other=true;std::cout<<statusJson().c_str()<<"\n";glove::other=false;
 incoming=true;uploadSlot=1;std::cout<<statusJson().c_str()<<"\n";incoming=false;uploadSlot=0;
 ready=false;std::cout<<statusJson().c_str()<<"\n";ready=true;
 scs::pf.family=scs::Family::SCS;std::cout<<statusJson().c_str()<<"\n";
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
states=[json.loads(line) for line in subprocess.check_output([str(exe)],text=True).splitlines()]
assert len(states)==8
for state in states:
    assert state['software_ready'] is True
    assert state['upload_protocol']=='chunks-v1' and state['upload_chunk_max']==384
    assert state['controller_id']=='page-a'
    assert state['piano_ids']==[2,3,4,5,6] and state['thumb_pose_id']==1
assert states[0]['motion_ready'] and states[0]['storage_ready'] and states[0]['readiness_error']=='none'
assert not states[1]['motion_ready'] and states[1]['readiness_error']=='position_feedback_lost'
for i in (2,3):
    assert not states[i]['calibration_ready'] and not states[i]['motion_ready'] and states[i]['readiness_error']=='calibration_not_ready'
assert states[4]['motion_busy'] and not states[4]['motion_ready'] and states[4]['readiness_error']=='motion_busy'
assert states[5]['upload_active'] and not states[5]['motion_ready'] and states[5]['readiness_error']=='upload_active_finish_or_abort_first'
assert not states[6]['storage_ready'] and states[6]['motion_ready']
assert states[7]['model']=='SC09' and states[7]['hold_adjustable'] is False
print('PASS actual hotspot status schema: power/feedback missing, calibration/ID mismatch, competing motion, upload, storage independently reported; per-page controller + chunks-v1; fixed five-finger mapping and both internal models')
