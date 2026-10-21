@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
set "PG_PY=python"
python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if errorlevel 1 set "PG_PY=py -3"
%PG_PY% -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if errorlevel 1 (
    echo Python 3.10 or newer is required. Customer EXE needs no Python install.
    pause
    popd
    exit /b 1
)
%PG_PY% -c "import serial, pypdfium2, pypdf, PIL" >nul 2>&1
if errorlevel 1 (
    %PG_PY% -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Dependency install failed.
        pause
        popd
        exit /b 1
    )
)
%PG_PY% -u customer_runtime.py %*
if errorlevel 1 pause
popd
endlocal
