from pathlib import Path
import os
import shutil
import subprocess
root=Path(__file__).resolve().parent
vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
environment=os.environ.copy()
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
target=root/'library_targets_test.exe'
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(root/'library_targets_test.cpp'),'/Fe:'+str(target)],cwd=root,env=environment,check=True)
subprocess.run([str(target)],check=True)
