@echo off
setlocal
cd /d "%~dp0"
title [DeCard T6 / T10] Contact Smart Card PC/SC Bridge

set "PATH=%~dp0drivers;%PATH%"

echo ===============================================================
echo   DeCard T6 / T10 Contact Smart Card Bridge
echo   Connecting to BixVReader / VPCD on 127.0.0.1:35963
echo ===============================================================
echo.

set "POWERSHELL_BIN=powershell.exe"
if exist "%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" (
    set "POWERSHELL_BIN=%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
)

"%POWERSHELL_BIN%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\decard_contact_bridge.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Bridge exited with error code %ERRORLEVEL%.
    pause
)
