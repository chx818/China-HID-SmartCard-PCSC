@echo off
setlocal
cd /d "%~dp0"
title Watchdata W2160 Serial PC/SC Bridge
echo ===============================================================
echo   W2160 / CRW-Xs SERIAL bridge
echo   Select the COM port before starting the VPCD relay.
echo ===============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\w2160_serial_bridge.ps1" %*
set "BRIDGE_EXIT=%ERRORLEVEL%"
if %BRIDGE_EXIT% NEQ 0 (
    echo.
    echo [ERROR] Bridge exited with error code %BRIDGE_EXIT%.
    pause
)
exit /b %BRIDGE_EXIT%
