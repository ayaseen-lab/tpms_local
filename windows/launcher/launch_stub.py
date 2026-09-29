"""Thin Windows double-click stub — starts the suite without a console flicker loop.

Older Go TPMS_Suite.exe called Start TPMS Suite.bat, which re-launched the exe.
This stub starts pythonw + main.py (or the packaged build) directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _message(text: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "TPMS Suite", 0x10)  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    root = _root()
    packaged = root / "dist" / "TPMS_Suite" / "Fyrqom_TPMS_Suite.exe"
    if not packaged.is_file():
        packaged = root / "dist" / "TPMS_Suite" / "TPMS_Suite.exe"
    if packaged.is_file() and (root / "dist" / "TPMS_Suite" / "_internal").is_dir():
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(packaged)], cwd=str(packaged.parent), close_fds=True, creationflags=flags)
        return 0

    main_py = root / "main.py"
    if not main_py.is_file():
        _message(f"TPMS Suite launcher: main.py not found.\n\nRoot: {root}")
        return 1

    candidates = [
        root / ".venv" / "Scripts" / "pythonw.exe",
        root / ".venv" / "Scripts" / "python.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Python" / "Python312" / "pythonw.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Python" / "Python311" / "pythonw.exe",
    ]
    py = next((p for p in candidates if p.is_file()), None)
    if py is None:
        for name in ("pythonw.exe", "python.exe"):
            found = shutil_which(name)
            if found:
                py = Path(found)
                break
    if py is None:
        _message(
            "Python was not found.\n\nRun Setup_Windows.bat once, or install Python 3.11+\n"
            "from python.org (check \"Add python.exe to PATH\")."
        )
        return 1

    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if py.name.lower() != "pythonw.exe":
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([str(py), str(main_py)], cwd=str(root), close_fds=True, creationflags=flags)
    return 0


def shutil_which(cmd: str) -> str | None:
    import shutil

    return shutil.which(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
