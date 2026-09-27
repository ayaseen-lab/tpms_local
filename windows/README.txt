Windows helpers for TPMS Suite 2.0
=================================

Repo-root TPMS_Suite.exe — double-click launcher (calls Start TPMS Suite.bat)
launcher/               — Go source for the .exe (rebuild with build_launcher.sh)

From the repo root on Windows:
  Setup_Windows.bat              first-time venv + deps
  Start TPMS Suite.bat           daily start
  Build_Windows_Installer.bat    full PyInstaller + Inno Setup package
