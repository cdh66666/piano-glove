@echo off
REM ============================================================
REM  Piano Glove - debug console one-click launcher
REM
REM  起本地串口桥 (bridge.py) + 打开调试台。
REM
REM  为什么不是 `python -m http.server`？
REM    因为串口**不在浏览器里**开。Web Serial 只有电脑版 Chrome/Edge 有，
REM    侧边栏浏览器 / 内嵌 WebView / 微信里打开的网页一律没有 ——
REM    在那些地方点「连接」永远没反应。
REM    bridge.py 在自己的进程里用 pyserial 开串口，网页只发 HTTP，
REM    于是任何浏览器都能用，而且串口口是 Python 那边自动挑的，不用手选。
REM ============================================================

setlocal
set "PORT=8123"
set "URL=http://127.0.0.1:%PORT%/web_piano_glove.html"

REM Python: prefer the managed runtime, fall back to whatever is on PATH.
set "PY=C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"

pushd "%~dp0"

REM ---- pyserial 是唯一的依赖，缺了就补上 ----
"%PY%" -c "import serial" >nul 2>&1
if errorlevel 1 (
    echo [*] 缺 pyserial, 正在安装 ...
    "%PY%" -m pip install --disable-pip-version-check -q pyserial
    "%PY%" -c "import serial" >nul 2>&1
    if errorlevel 1 (
        echo [!] pyserial 装不上。手动跑一下:
        echo         "%PY%" -m pip install pyserial
        pause
        popd
        exit /b 1
    )
)

REM ---- 端口被占（多半是上一次的桥还在）就先收掉 ----
"%PY%" -c "import socket,sys;s=socket.socket();r=s.connect_ex(('127.0.0.1',%PORT%));s.close();sys.exit(0 if r==0 else 1)" >nul 2>&1
if not errorlevel 1 (
    echo [*] %PORT% 已经被占用了。
    echo     如果那就是之前开的调试台，直接用它就行；要重开请先关掉那个窗口。
    echo     现在先按现状打开浏览器。
    start "" "%URL%"
    goto done
)

echo [*] 启动串口桥 (自动扫描 + 自动连接) ...
echo     窗口别关 —— 串口开在这个进程里。Ctrl+C 停。
REM 桥自己会用 --open 打开浏览器，所以这里不用再 start 一次
"%PY%" -u bridge.py --port %PORT% --open

:done
popd
endlocal
