"""TPMS Suite — combined SDR Receiver and TPMS Board app."""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_paths() -> None:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        root = Path(__file__).resolve().parent
    for path in (
        root,
        root / "sdr_ui",
        root / "hamaton-sdk-python-fix-uart-transport-timing" / "src",
    ):
        text = str(path)
        if path.exists() and text not in sys.path:
            sys.path.insert(0, text)


_bootstrap_paths()

from shell import run_app

if __name__ == "__main__":
    run_app()
