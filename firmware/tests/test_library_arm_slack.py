"""Run old ARM regression unchanged, then scoped LIB ARM and real median guards."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parent
subprocess.run([sys.executable,str(root/'test_safe_arm.py')],check=True)
base=(root/'safe_arm_generated.cpp').read_text(encoding='utf-8')
base=base.replace('bool readFeedback(uint8_t id,Feedback &fb){',
    'bool readFeedback(uint8_t id,Feedback &fb){if(sampleIndex>=0){fb.pos=samples[sampleIndex++%3];fb.ok=true;return true;}')
base=base.replace('assert(goals[id-1]==','assert(relaxLibraryMockGoal||goals[id-1]==')
prefix='bool relaxLibraryMockGoal=false;int sampleIndex=-1,samples[3]={};\n#include "../src/library_recovery.h"\n'
base=base[:base.index('int main(){')]
harness=prefix+base+'''
int main(){
 reset();assert(armLibraryAtCurrent(63,false));assert(g_armed&&!g_libraryArm);
 reset();g_calibrated=false;assert(!armLibraryAtCurrent(63,false));assert(!g_libraryArm&&!g_armed);
 reset();scs::hardwareOutside=true;assert(!armLibraryAtCurrent(63,false));assert(!g_libraryArm&&scs::writes==0);off();
 reset();scs::pf.family=scs::Family::STS;scs::pf.range=4095;g_slot[2].lo=1768;g_slot[2].hi=2417;
 assert(!armFeedbackAllowed(g_slot[2],2522,4095));
 g_libraryArm=true;assert(armFeedbackMargin(g_slot[2])==114);assert(armFeedbackAllowed(g_slot[2],2522,4095));assert(!armFeedbackAllowed(g_slot[2],2532,4095));
 assert(armCurrentGoal(g_slot[2],2522,0,4095)==2385);assert(armCurrentGoal(g_slot[2],2522,0,2300)==2300);assert(armCurrentGoal(g_slot[2],2522,2500,4095)==-1);
 scs::Feedback fb;samples[0]=2521;samples[1]=9999;samples[2]=2522;sampleIndex=0;assert(readArmFeedback(2,fb,"test")&&fb.pos==2522);
 samples[0]=500;samples[1]=1000;samples[2]=2000;sampleIndex=0;assert(!readArmFeedback(2,fb,"test"));assert(strstr(armFailure(),"library_feedback_unstable"));
 sampleIndex=-1;g_libraryArm=false;reset();scs::pf.family=scs::Family::SCS;g_slot[2].lo=400;g_slot[2].hi=500;assert(armFeedbackMargin(g_slot[2])==15);
 g_libraryArm=true;assert(armFeedbackMargin(g_slot[2])==35);assert(armFeedbackAllowed(g_slot[2],534,1023));assert(!armFeedbackAllowed(g_slot[2],536,1023));assert(armCurrentGoal(g_slot[2],534,20,1003)==494);g_libraryArm=false;
 reset();scs::hardwareOutside=true;assert(!armLibraryAtCurrent(63,true));assert(!g_libraryArm&&!g_libraryOffhand&&scs::writes==0);off();
 reset();scs::edgePosition=700;for(auto&slot:g_slot){slot.lo=400;slot.hi=500;slot.standby=450;}assert(!armLibraryAtCurrent(63,false));off();
 relaxLibraryMockGoal=true;assert(armLibraryAtCurrent(63,true));assert(!g_libraryArm&&!g_libraryOffhand);for(int i=0;i<6;++i){assert(scs::goals[i]==494);assert(armLibraryLastPosition(i)==700);assert(armLibraryHardwareMinimum(i)==20&&armLibraryHardwareMaximum(i)==1003);}relaxLibraryMockGoal=false;
 int slack=librarypolicy::margin(1667,2480,false);assert(slack==121);int deviation=librarypolicy::deviation(1667,2480,2785,slack);assert(deviation==184);
 assert(librarypolicy::recoverAllowed(1667,2480,2785,slack,deviation,0,4095));assert(librarypolicy::recoverAllowed(1667,2480,2788,slack,deviation,0,4095));assert(!librarypolicy::recoverAllowed(1667,2480,2789,slack,deviation,0,4095));
 assert(!librarypolicy::recoverAllowed(1667,2480,2785,slack,deviation,0,2700));assert(librarypolicy::deviation(1667,2480,2601,slack)==0);
 assert(librarypolicy::inwardTarget(1667,2480,2785,slack,2440));assert(!librarypolicy::inwardTarget(1667,2480,2785,slack,2800));assert(librarypolicy::inwardTarget(1667,2480,1300,slack,1707));assert(!librarypolicy::inwardTarget(1667,2480,1300,slack,1200));
 puts("PASS actual LIB ARM: scoped mode resets success/failure, fixed hardware limits, phone ID3 slack114, working90pct goal, median outlier, unstable rejection, SCS35; normal ARM margin unchanged");
 puts("PASS explicit OFFHAND ARM: NORMAL rejects stable outside calibration, OFFHAND accepts hardware-bounded current with work goal; actual recovery policy rejects outward/exceeding initial deviation and clears at normal window");
}
'''
cpp=root/'library_arm_slack_generated.cpp';exe=root/'library_arm_slack_generated.exe'
cpp.write_text(harness,encoding='utf-8')
vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
environment=os.environ.copy()
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
for source,target in [(root/'safe_arm_generated.cpp',root/'safe_arm_generated.exe'),(cpp,exe)]:
    subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(source),'/Fe:'+str(target)],cwd=root,env=environment,check=True)
    subprocess.run([str(target)],check=True)
