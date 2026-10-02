@echo off
setlocal
cd /d "%~dp0"
title [Feitian SCR501] Contactless PC/SC Bridge (RF Only)

set "PATH=%~dp0drivers;%PATH%"

echo ===============================================================
echo   Feitian SCR501 (VID_096E^&PID_0603) Contactless PC/SC Bridge
echo   (Notice: Currently Contactless RF Interface ONLY)
echo   Connecting to BixVReader / VPCD on 127.0.0.1:35963
echo ===============================================================
echo.

set "POWERSHELL_BIN=powershell.exe"
if exist "%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" (
    set "POWERSHELL_BIN=%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
)

"%POWERSHELL_BIN%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\feitian_scr501_bridge.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Bridge exited with error code %ERRORLEVEL%.
    pause
)
