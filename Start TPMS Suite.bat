@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title TPMS Suite 4.0
echo.
echo  TPMS Suite 4.0
echo  --------------

REM Prefer packaged PyInstaller onedir build if present
if exist "%~dp0dist\TPMS_Suite\Fyrqom_TPMS_Suite.exe" (
  if exist "%~dp0dist\TPMS_Suite\_internal\" (
    echo Launching packaged Fyrqom_TPMS_Suite.exe ...
    start "" "%~dp0dist\TPMS_Suite\Fyrqom_TPMS_Suite.exe"
    exit /b 0
  )
)
if exist "%~dp0dist\TPMS_Suite\TPMS_Suite.exe" (
  if exist "%~dp0dist\TPMS_Suite\_internal\" (
    echo Launching packaged TPMS_Suite.exe ...
    start "" "%~dp0dist\TPMS_Suite\TPMS_Suite.exe"
    exit /b 0
  )
)

REM Do NOT start repo-root TPMS_Suite.exe from this script.
REM That file is the Go double-click launcher. Older builds called this .bat,
REM and this .bat starting the .exe again caused an infinite console flicker loop.

set "PY="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\pythonw.exe" set "PY=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\pythonw.exe" set "PY=%LocalAppData%\Programs\Python\Python311\pythonw.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY (
  where pythonw >nul 2>&1 && for /f "delims=" %%I in ('where pythonw') do (
    set "PY=%%I"
    goto :have_py
  )
)
if not defined PY (
  where python >nul 2>&1 && for /f "delims=" %%I in ('where python') do (
    set "PY=%%I"
    goto :have_py
  )
)
:have_py
if not defined PY (
  echo.
  echo Python was not found.
  echo Run Setup_Windows.bat once, or install Python 3.11+ from python.org
  echo ^(check "Add python.exe to PATH"^), then try again.
  echo.
  pause
  exit /b 1
)

echo Using: %PY%
"%PY%" "%~dp0main.py"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo TPMS Suite exited with code %EC%.
  pause
)
exit /b %EC%
