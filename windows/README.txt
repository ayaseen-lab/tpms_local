Windows helpers for TPMS Suite 2.0
=================================

Repo-root TPMS_Suite.exe — double-click launcher (starts packaged app or pythonw main.py)
launcher/               — launch_stub.py (Windows rebuild: build_launcher.bat)
                          optional Go source (build_launcher.sh) — must use -H windowsgui
                          Start TPMS Suite.bat must NOT start this .exe (flicker loop).

From the repo root on Windows:
  Setup_Windows.bat              first-time venv + deps
  Start TPMS Suite.bat           daily start
  Build_Windows_Installer.bat    full PyInstaller + Inno Setup package
