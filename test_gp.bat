@echo off
setlocal
cd /d "%~dp0"
title [Test] GlobalPlatformPro Verification

set "GP_EXE="
if exist "%~dp0tools\gp.exe" (
    set "GP_EXE=%~dp0tools\gp.exe"
) else if exist "%~dp0gp.exe" (
    set "GP_EXE=%~dp0gp.exe"
) else if exist "%~dp0..\gp.exe" (
    set "GP_EXE=%~dp0..\gp.exe"
) else (
    set "GP_EXE=gp.exe"
)

echo ===============================================================
echo   Executing GlobalPlatformPro over "Virtual PCD" Reader...
echo ===============================================================
echo.

"%GP_EXE%" -r "Virtual PCD" -l -v -X

echo.
echo ===============================================================
echo   Execution finished.
echo ===============================================================
pause
