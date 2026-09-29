@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build TPMS Suite Windows installer (2.0)
echo.
echo  Builds Fyrqom_TPMS_Suite.exe + TPMS_Suite_Setup_2.0.0.exe
echo  Requires: Python 3.11+, network (vendor download), Inno Setup 6
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_installer.ps1"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo Build failed with exit code %EC%.
  pause
  exit /b %EC%
)
echo.
echo Done. Installer is under dist_installer\
dir /b dist_installer\TPMS_Suite_Setup_*.exe 2>nul
echo.
echo Packaged app:
dir /b dist\TPMS_Suite\Fyrqom_TPMS_Suite.exe 2>nul
pause
exit /b 0
