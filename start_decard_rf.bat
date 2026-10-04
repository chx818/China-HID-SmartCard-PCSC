@echo off
setlocal
cd /d "%~dp0"
title [DeCard RF] Dual-Interface T6 / T10 Contactless PC/SC Bridge

set "PATH=%~dp0drivers;%PATH%"

echo ===============================================================
echo   DeCard Dual-Interface T6 / T10 Contactless PC/SC Bridge
echo   Connecting to BixVReader / VPCD on 127.0.0.1:35963
echo ===============================================================
echo.

set "POWERSHELL_BIN=powershell.exe"
if exist "%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" (
    set "POWERSHELL_BIN=%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
)

"%POWERSHELL_BIN%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\decard_rf_bridge.ps1" %*

set "BRIDGE_EXIT=%ERRORLEVEL%"
if %BRIDGE_EXIT% NEQ 0 (
    echo.
    echo [ERROR] Bridge exited with error code %BRIDGE_EXIT%.
    pause
)
exit /b %BRIDGE_EXIT%
