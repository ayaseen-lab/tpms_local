@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "%~dp0main.py"
) else if exist "D:\Xynovix\SDR_UI\.venv\Scripts\python.exe" (
  "D:\Xynovix\SDR_UI\.venv\Scripts\python.exe" "%~dp0main.py"
) else (
  python "%~dp0main.py"
)
