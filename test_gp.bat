@echo off
setlocal
cd /d "%~dp0"
title [Test] GlobalPlatformPro Verification

set "GP_EXE="
if exist "%~dp0gp.exe" set "GP_EXE=%~dp0gp.exe"
if not defined GP_EXE if exist "%~dp0..\gp.exe" set "GP_EXE=%~dp0..\gp.exe"
if not defined GP_EXE if exist "%~dp0tools\gp.exe" set "GP_EXE=%~dp0tools\gp.exe"
if not defined GP_EXE (
    where gp.exe >nul 2>nul
    if %ERRORLEVEL% equ 0 set "GP_EXE=gp.exe"
)

if not defined GP_EXE (
    echo [ERROR] gp.exe not found!
    echo Please download GlobalPlatformPro (gp.exe) from:
    echo   https://github.com/martinpaljak/GlobalPlatformPro/releases
    echo and place gp.exe into this folder.
    echo.
    pause
    exit /b 1
)

echo ===============================================================
echo   Executing GlobalPlatformPro over "Virtual PCD" Reader...
echo ===============================================================
echo.

"%GP_EXE%" -r "Virtual PCD" -l -v

echo.
echo ===============================================================
echo   Execution finished.
echo ===============================================================
pause
