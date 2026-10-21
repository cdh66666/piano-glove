"""Compile real software arming and unchanged strict ARM with fake servo I/O.

No device or serial port is opened. Moving feedback may miss calibration and
arrival windows; target bounds, hardware frames and register checks still pass.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
subprocess.run([sys.executable, str(root / 'test_safe_arm.py')], check=True)
base = (root / 'safe_arm_generated.cpp').read_text(encoding='utf-8')
base = base[:base.index('int main(){')]
base = base.replace('assert(goals[id-1]==', 'assert(relaxSoftwareMockGoal||goals[id-1]==')
base = base.replace('const int lo=20,hi=1003;', 'const int lo=hardwareMin,hi=hardwareMax;')
base = base.replace('bool readFeedback(uint8_t id,Feedback &fb){', '''bool readFeedback(uint8_t id,Feedback &fb){
 if(feedbackMissing)return false;
 fb.voltage=healthVoltage;fb.temp=healthTemperature;
 if(movingSamples){fb.pos=(movingSample++%3)*200+200;fb.ok=true;return true;}
''')
prefix = '''bool relaxSoftwareMockGoal=false,feedbackMissing=false,movingSamples=false;
int movingSample=0,healthVoltage=50,healthTemperature=25,hardwareMin=20,hardwareMax=1003;
'''
harness = prefix + base + r'''
void softwareReset(){
 reset();relaxSoftwareMockGoal=true;feedbackMissing=movingSamples=false;movingSample=0;healthVoltage=50;healthTemperature=25;hardwareMin=20;hardwareMax=1003;
 for(auto&slot:g_slot){slot.lo=400;slot.hi=500;slot.standby=450;}
 scs::edgePosition=700; // Clearly beyond the old 15%+35 calibration window.
}
void modeOff(){assert(!g_libraryArm&&!g_libraryOffhand&&!g_librarySoftware);}
void goalsBounded(uint8_t selected,int amplitude){
 for(int s=0;s<6;++s){const auto&slot=g_slot[s];
  const int expected=librarytargets::softwareTarget(s,scs::pf.family==scs::Family::SCS,slot.lo,slot.hi,hardwareMin,hardwareMax,
      s>0&&bool(selected&(1<<(s-1))),s==0?100:amplitude);
  assert(scs::goals[s]==expected&&expected>=slot.lo&&expected<=slot.hi&&expected>=hardwareMin&&expected<=hardwareMax);
  assert(armLibraryHardwareMinimum(s)==hardwareMin&&armLibraryHardwareMaximum(s)==hardwareMax);
 }
}
int main(){
 softwareReset();assert(armLibrarySoftwarePose(1,100));assert(g_armed&&scs::writes==6);modeOff();goalsBounded(1,100);
 assert(scs::goals[0]==494&&scs::goals[1]==406);for(int s=0;s<6;++s)assert(armLibraryLastPosition(s)==700);
 assert(fakeMs<100); // No 300ms arrival loop and no current-to-edge recovery pose.
 softwareReset();movingSamples=true;scs::edgePosition=-1;assert(armLibrarySoftwarePose(21,20));modeOff();goalsBounded(21,20);
 assert(fakeMs<100&&armLibraryLastPosition(0)==400); // Readable 200/400/600 motion is not "unstable".
 for(auto family:{scs::Family::SCS,scs::Family::STS})for(int amplitude:{1,20,60,100})for(int selected:{0,1,10,31}){
  softwareReset();scs::pf.family=family;scs::pf.range=family==scs::Family::SCS?1023:4095;
  assert(armLibrarySoftwarePose(selected,amplitude));modeOff();goalsBounded(selected,amplitude);
 }
 softwareReset();scs::edgePosition=700;assert(!armAtCurrent(63));off();assert(scs::writes==0);modeOff();
 softwareReset();scs::edgePosition=700;assert(!armPrepareCurrent(63));off();assert(scs::writes==0);modeOff();
 softwareReset();scs::edgePosition=700;assert(!armLibraryAtCurrent(63,false));off();assert(scs::writes==0);modeOff();
 softwareReset();scs::edgePosition=1004;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0&&strstr(armFailure(),"hardware_outside"));
 softwareReset();scs::edgePosition=19;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0);
 softwareReset();scs::edgePosition=-1;scs::prewriteHardwareOutside=true;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0);
 softwareReset();feedbackMissing=true;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0);
 for(int value:{39,66}){softwareReset();healthVoltage=value;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0&&strstr(armFailure(),"temperature_or_voltage"));}
 softwareReset();healthTemperature=65;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0);
 softwareReset();scs::missingAck=true;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(strstr(armFailure(),"goal_write_unacknowledged"));
 softwareReset();scs::badGoal=true;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(strstr(armFailure(),"goal_mismatch"));
 softwareReset();scs::failedEnable=3;assert(!armLibrarySoftwarePose(1,100));off();modeOff();
 softwareReset();g_calibrated=false;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0);
 softwareReset();g_slot[0].id=2;assert(!armLibrarySoftwarePose(1,100));off();modeOff();assert(scs::writes==0);
 for(int amplitude:{0,101}){softwareReset();assert(!armLibrarySoftwarePose(1,amplitude));off();modeOff();assert(scs::writes==0);}
 softwareReset();assert(!armLibrarySoftwarePose(32,100));off();modeOff();assert(scs::writes==0);
 // Software targets retain at least 5% inset at both ends.
 softwareReset();for(auto&slot:g_slot){slot.lo=10;slot.hi=1010;slot.standby=450;}
 assert(armLibrarySoftwarePose(31,100));modeOff();goalsBounded(31,100);
 assert(scs::goals[0]==960&&scs::goals[1]==60);
 // Fresh hardware limits may narrow the window without expanding calibration.
 softwareReset();hardwareMin=440;hardwareMax=460;scs::edgePosition=450;
 assert(armLibrarySoftwarePose(31,100));modeOff();goalsBounded(31,100);
 assert(scs::goals[0]==460&&scs::goals[1]==440);
 softwareReset();hardwareMin=800;hardwareMax=900;scs::edgePosition=850;
 assert(!armLibrarySoftwarePose(31,100));off();modeOff();assert(scs::writes==0&&strstr(armFailure(),"target_intersection_empty"));
 // Software mode is reset: the next normal ARM retains its strict behavior.
 scs::edgePosition=700;for(auto&slot:g_slot){slot.lo=400;slot.hi=500;slot.standby=450;}
 assert(!armAtCurrent(63));off();modeOff();
 puts("PASS real software arm: direct musical pose, calibration/arrival advisory, moving frames, SCS/STS targets, unchanged strict ARM/PREPARE, hardware/health/readback failures and scoped reset");
}
'''
cpp = root / 'library_software_arm_generated.cpp'
exe = root / 'library_software_arm_generated.exe'
cpp.write_text(harness, encoding='utf-8')
vcvars = Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
environment = os.environ.copy()
for line in subprocess.check_output(['cmd', '/d', '/c', f'call {vcvars} >nul && set'], encoding='utf-8', errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key, value = line.split('=', 1)
        environment[key.upper()] = value
compiler = shutil.which('cl.exe', path=environment['PATH'])
assert compiler
for source, target in [(root / 'safe_arm_generated.cpp', root / 'safe_arm_generated.exe'), (cpp, exe)]:
    subprocess.run([compiler, '/nologo', '/EHsc', '/std:c++17', str(source), '/Fe:' + str(target)], cwd=root, env=environment, check=True)
    subprocess.run([str(target)], check=True)
