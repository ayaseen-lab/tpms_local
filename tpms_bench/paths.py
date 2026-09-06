"""Resolve app and results folders for source runs and frozen Windows builds."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Writable application root: next to the .exe when packaged."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundle_root() -> Path:
    """Read-only bundle (PyInstaller _MEIPASS) or source tree."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def sdk_src() -> Path:
    return bundle_root() / "hamaton-sdk-python-fix-uart-transport-timing" / "src"


def results_dir() -> Path:
    folder = app_root() / "results"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "logs").mkdir(parents=True, exist_ok=True)
    (folder / "iq").mkdir(parents=True, exist_ok=True)
    return folder
