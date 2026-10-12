@echo off
setlocal
cd /d "%~dp0"
title Watchdata USB contact PC/SC Bridge
echo Watchdata USB contact bridge - W8298 / W5181 Plus
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\watchdata_contact_bridge.ps1" %*
set "BRIDGE_EXIT=%ERRORLEVEL%"
if %BRIDGE_EXIT% NEQ 0 (
    echo [ERROR] Bridge exited with error code %BRIDGE_EXIT%.
    pause
)
exit /b %BRIDGE_EXIT%
