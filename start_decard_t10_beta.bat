@echo off
setlocal
cd /d "%~dp0"
title [DeCard T10 Beta] Dual-Interface T10 PC/SC Bridge (Contact Slot 0x0C and RF Pad)

set "PATH=%~dp0drivers;%PATH%"

echo ===============================================================
echo   DeCard T10 Beta PC/SC Bridge (VID_0471 PID_A133)
echo   Supports Contact Slot (0x0C) and Contactless Pad (ISO 14443-4)
echo   Connecting to BixVReader / VPCD on 127.0.0.1:35963
echo ===============================================================
echo.

set "POWERSHELL_BIN=powershell.exe"
if exist "%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" (
    set "POWERSHELL_BIN=%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
)

"%POWERSHELL_BIN%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\decard_t10_beta_bridge.ps1" %*

set "BRIDGE_EXIT=%ERRORLEVEL%"
if %BRIDGE_EXIT% NEQ 0 (
    echo.
    echo [ERROR] Bridge exited with error code %BRIDGE_EXIT%.
    pause
)
exit /b %BRIDGE_EXIT%
