"""Read Hamaton UART replies from nRF52840 SRAM via J-Link.

Commands go out on USB-TTL TX. Board UART replies are mirrored into SRAM.
Do not halt the CPU during LF/RF — savebin on a running target.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from hamaton.exceptions import FrameError
from hamaton.frame import HamatonFrame

from .paths import results_dir

RESULTS = results_dir()


def _hidden_kwargs() -> dict:
    """Prevent J-Link Commander from flashing a Windows console on every dump."""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {"creationflags": flags, "startupinfo": startupinfo}

RAM_ADDR = 0x20002000
RAM_LEN = 0x10000
RAM_BIN = RESULTS / "nrf_uart_window.bin"
JLINK_SCRIPT = RESULTS / "jlink_dump_window.jlink"
JLINK_LOG = RESULTS / "jlink_last.log"

_JLINK_EXE: str | None = None


@dataclass
class DumpResult:
    blob: bytes
    ok: bool
    message: str


def jlink_exe() -> str:
    """Resolve SEGGER J-Link executable (versioned install folders on Windows)."""
    global _JLINK_EXE
    if _JLINK_EXE and Path(_JLINK_EXE).exists():
        return _JLINK_EXE

    for name in ("JLink.exe", "JLinkExe", "JLink"):
        found = shutil.which(name)
        if found and Path(found).exists():
            _JLINK_EXE = found
            return found

    search_roots = [
        Path(r"C:\Program Files\SEGGER"),
        Path(r"C:\Program Files (x86)\SEGGER"),
    ]
    if sys.platform == "darwin":
        search_roots.append(Path("/Applications/SEGGER"))

    candidates: list[Path] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        candidates.extend(root.glob("JLink*/JLink.exe"))
        candidates.extend(root.glob("JLink*/JLinkExe"))
        direct = root / "JLink" / "JLink.exe"
        if direct.exists():
            candidates.append(direct)

    if candidates:
        # Prefer highest version folder name (JLink_V970 > JLink_V818).
        candidates.sort(key=lambda p: p.parent.name, reverse=True)
        _JLINK_EXE = str(candidates[0])
        return _JLINK_EXE

    return "JLink.exe"


def _jlink_available() -> bool:
    path = Path(jlink_exe())
    return path.exists() or shutil.which(jlink_exe()) is not None


def dump_sram(addr: int = RAM_ADDR, length: int = RAM_LEN) -> bytes:
    return dump_sram_result(addr, length).blob


def dump_sram_result(addr: int = RAM_ADDR, length: int = RAM_LEN) -> DumpResult:
    if not _jlink_available():
        return DumpResult(b"", False, "Board SRAM reader not available on this PC")

    ram_path = str(RAM_BIN.resolve())
    JLINK_SCRIPT.write_text(
        "\n".join(
            [
                "si SWD",
                "speed 4000",
                "device NRF52840_XXAA",
                "connect",
                f'savebin "{ram_path}", 0x{addr:X}, 0x{length:X}',
                "exit",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                jlink_exe(),
                "-AutoConnect",
                "1",
                "-NoGui",
                "1",
                "-CommanderScript",
                str(JLINK_SCRIPT.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            **_hidden_kwargs(),
        )
    except FileNotFoundError as exc:
        return DumpResult(b"", False, f"Board SRAM reader launch failed: {exc}")
    except subprocess.TimeoutExpired:
        return DumpResult(b"", False, "Board SRAM read timed out")

    log_text = (result.stdout or "") + "\n" + (result.stderr or "")
    JLINK_LOG.write_text(log_text, encoding="utf-8")

    if "Cannot connect" in log_text or "Could not find" in log_text:
        return DumpResult(b"", False, "Cannot connect to board — check programming cable")

    if not RAM_BIN.exists():
        return DumpResult(b"", False, f"Board SRAM read failed (rc={result.returncode})")

    blob = RAM_BIN.read_bytes()
    if len(blob) < 256:
        return DumpResult(blob, False, "Board SRAM read too small")
    return DumpResult(blob, True, "ok")


def probe_jlink() -> bool:
    return dump_sram_result().ok


def last_jlink_log_tail(n: int = 400) -> str:
    if not JLINK_LOG.exists():
        return ""
    return JLINK_LOG.read_text(encoding="utf-8", errors="replace")[-n:]


def extract_frames(blob: bytes, address: int) -> list[tuple[int, HamatonFrame]]:
    frames: list[tuple[int, HamatonFrame]] = []
    tag = bytes([HamatonFrame.HEADER, address])
    index = 0
    while True:
        start = blob.find(tag, index)
        if start < 0 or start + 4 > len(blob):
            break
        payload_length = int.from_bytes(blob[start + 2 : start + 4], "big")
        total = payload_length + HamatonFrame.OVERHEAD
        if payload_length > 64 or start + total > len(blob):
            index = start + 1
            continue
        if blob[start + total - 1] != HamatonFrame.TAIL:
            index = start + 1
            continue
        raw = blob[start : start + total]
        try:
            frames.append((start, HamatonFrame.from_bytes(raw)))
        except FrameError:
            index = start + 1
            continue
        index = start + total
    return frames


def snapshot_keys(blob: bytes) -> set[tuple[int, bytes]]:
    keys: set[tuple[int, bytes]] = set()
    for offset, frame in extract_frames(blob, HamatonFrame.BOARD_ADDRESS):
        keys.add((offset, frame.to_bytes()))
    return keys


def new_board_frames(blob: bytes, before: set[tuple[int, bytes]]) -> list[HamatonFrame]:
    found: list[HamatonFrame] = []
    for offset, frame in extract_frames(blob, HamatonFrame.BOARD_ADDRESS):
        if (offset, frame.to_bytes()) not in before:
            found.append(frame)
    return found
