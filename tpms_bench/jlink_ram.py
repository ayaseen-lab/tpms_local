"""J-Link / SWD SRAM RX has been removed.

Board replies are read only over USB-TTL RX. This module remains as a
compatibility stub so old imports fail clearly instead of launching JLinkExe.
"""

from __future__ import annotations

from dataclasses import dataclass


class JLinkRemovedError(RuntimeError):
    """Raised when legacy J-Link SRAM helpers are called."""


@dataclass
class DumpResult:
    blob: bytes
    ok: bool
    message: str


def _gone(what: str = "J-Link SRAM RX"):
    raise JLinkRemovedError(
        f"{what} was removed — use USB-TTL TX/RX only (no JTAG / J-Link)."
    )


def jlink_exe() -> str:
    _gone()


def jlink_available() -> bool:
    return False


def close_session() -> None:
    return None


def dump_sram(*_a, **_k) -> bytes:
    _gone()


def dump_sram_result(*_a, **_k) -> DumpResult:
    return DumpResult(b"", False, "J-Link removed — USB-TTL RX only")


def probe_jlink() -> bool:
    return False


def last_jlink_log_tail(n: int = 400) -> str:
    return ""


def extract_frames(*_a, **_k):
    _gone("extract_frames")


def snapshot_keys(*_a, **_k):
    _gone("snapshot_keys")


def new_board_frames(*_a, **_k):
    _gone("new_board_frames")
