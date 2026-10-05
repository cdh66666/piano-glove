@echo off
setlocal
cd /d "%~dp0"
set "PY=python"
python -c "import sys; assert sys.version_info.major == 3" >nul 2>&1
if errorlevel 1 set "PY=py -3"
%PY% -c "import serial" >nul 2>&1
if errorlevel 1 (
  echo Python 3 and pyserial are required. Run: python -m pip install -r requirements.txt
  pause
  exit /b 1
)
%PY% start-dual.py %*
if errorlevel 1 pause
endlocal
