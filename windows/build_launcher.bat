@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

REM Rebuild repo-root TPMS_Suite.exe as a windowed stub (no console flicker).
REM Requires .venv (Setup_Windows.bat) and PyInstaller.

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Run Setup_Windows.bat first.
  exit /b 1
)

"%PY%" -m pip install -q pyinstaller
"%PY%" -m PyInstaller --noconfirm --clean --onefile --noconsole --name Fyrqom_TPMS_Suite --icon "%CD%\installer\tpms_suite.ico" --distpath "%CD%" --workpath "%TEMP%\tpms_launcher_build" --specpath "%TEMP%\tpms_launcher_build" "%CD%\windows\launcher\launch_stub.py"
if errorlevel 1 exit /b 1
if exist "%CD%\TPMS_Suite.exe" del /F /Q "%CD%\TPMS_Suite.exe" >nul 2>&1
copy /Y "%CD%\Fyrqom_TPMS_Suite.exe" "%CD%\windows\Fyrqom_TPMS_Suite.exe" >nul
echo Wrote Fyrqom_TPMS_Suite.exe (GUI subsystem + icon)
exit /b 0
