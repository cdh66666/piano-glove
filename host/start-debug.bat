@echo off
REM ============================================================
REM  Piano Glove - debug console one-click launcher
REM
REM  Starts a static server for host/ on 127.0.0.1:8123 and opens
REM  the debug console in Chrome or Edge.
REM
REM  Why not just double-click the .html?
REM    - Opening via file:// does NOT work: Web Serial needs a
REM      secure context served over http, and some browsers block
REM      navigator.serial entirely on file://.
REM    - Chrome/Edge are required. The system default browser may
REM      not expose navigator.serial at all (e.g. Doubao/WeChat
REM      built-in browsers), and then the "connect" button will
REM      never find the board.
REM
REM  Why not just run `python -m http.server`?
REM    That is fine too - this script only saves you from having
REM    to remember the port and the URL.
REM ============================================================

setlocal
set "PORT=8123"
set "URL=http://127.0.0.1:%PORT%/web_piano_glove.html"

REM Python: prefer the managed runtime, fall back to whatever is on PATH.
set "PY=C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"

set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

REM Serve from this script's own folder (host/).
pushd "%~dp0"

REM Start the server only if nothing is already listening on the port.
"%PY%" -c "import socket,sys;s=socket.socket();r=s.connect_ex(('127.0.0.1',%PORT%));s.close();sys.exit(0 if r==0 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [*] starting static server on port %PORT% ...
    start "piano-glove-server" /min "%PY%" -u -m http.server %PORT% --bind 127.0.0.1
    timeout /t 2 /nobreak >nul
) else (
    echo [*] server already listening on port %PORT%
)

if exist "%CHROME%" goto useChrome
if exist "%EDGE%"   goto useEdge
goto useDefault

:useChrome
echo [*] opening %URL% in Chrome
start "" "%CHROME%" "%URL%"
goto done

:useEdge
echo [*] opening %URL% in Edge
start "" "%EDGE%" "%URL%"
goto done

:useDefault
echo [!] Chrome / Edge not found on this machine.
echo     Falling back to the default browser - Web Serial may not
echo     work there, so you might not be able to reach the board.
start "" "%URL%"

:done
echo.
echo [*] URL: %URL%
echo     Close the "piano-glove-server" window to stop the server.
popd
endlocal
