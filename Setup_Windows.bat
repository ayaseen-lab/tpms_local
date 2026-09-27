@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title TPMS Suite 2.0 — First-time Windows setup
echo.
echo  TPMS Suite 2.0 — Windows setup
echo  --------------------------------
echo  Creates .venv, installs requirements, fetches rtl_433/Zadig.
echo.

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python 3.11+ not found on PATH.
    echo Install from https://www.python.org/downloads/windows/
    echo Enable "Add python.exe to PATH", then re-run this file.
    pause
    exit /b 1
  )
  set "BOOT=py -3"
) else (
  set "BOOT=python"
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %BOOT% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
)

set "PY=%~dp0.venv\Scripts\python.exe"
echo Upgrading pip...
"%PY%" -m pip install --upgrade pip
echo Installing requirements...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip install failed
  pause
  exit /b 1
)

if exist "installer\fetch_vendor.py" (
  echo Fetching Windows vendor binaries (rtl_433, Zadig)...
  "%PY%" installer\fetch_vendor.py
)

echo.
echo Setup complete.
echo Starting TPMS Suite...
echo.
call "%~dp0Start TPMS Suite.bat"
exit /b %ERRORLEVEL%
