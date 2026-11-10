@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
rem 虚拟手机：不碰电脑 Wi-Fi。接了真手套就把下面改成 --device COM9
python -X utf8 tools\phone_simirtual_phone.py %*
