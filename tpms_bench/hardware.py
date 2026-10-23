"""Detect USB-TTL (board TX/RX) and RTL-SDR. No J-Link path."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .uart import find_serial_ports, list_serial_port_choices, port_device


@dataclass
class PathStatus:
    ok: bool
    label: str
    detail: str = ""


@dataclass
class HardwareTrio:
    """USB-TTL + SDR. ``jlink`` kept as a always-missing placeholder for old callers."""

    usb_ttl: PathStatus
    jlink: PathStatus
    sdr: PathStatus

    @property
    def board_ready(self) -> bool:
        return self.usb_ttl.ok

    @property
    def all_ok(self) -> bool:
        return self.usb_ttl.ok and self.sdr.ok

    def summary_lines(self) -> list[str]:
        return [
            f"USB-TTL  [{'OK' if self.usb_ttl.ok else 'MISSING'}]  {self.usb_ttl.label}"
            + (f" — {self.usb_ttl.detail}" if self.usb_ttl.detail else ""),
            f"SDR      [{'OK' if self.sdr.ok else 'MISSING'}]  {self.sdr.label}"
            + (f" — {self.sdr.detail}" if self.sdr.detail else ""),
        ]


def _ttl_status() -> PathStatus:
    choices = list_serial_port_choices()
    avoid = ("JLINK", "SEGGER", "BLUETOOTH", "UGREEN", "HITUNE", "HEADPHONE", "AIRPODS")
    for device, label in choices:
        text = f"{device} {label}".upper()
        if any(h in text for h in avoid):
            continue
        if any(
            h in text
            for h in (
                "USB SERIAL",
                "USB-SERIAL",
                "CH340",
                "CP210",
                "FTDI",
                "SLAB",
                "UART",
                "SILICON LABS",
                "PROLIFIC",
                "USBSERIAL",
            )
        ):
            return PathStatus(True, device, label.split("—", 1)[-1].strip() if "—" in label else "USB-TTL")
        if device.startswith("/dev/cu.usbserial"):
            return PathStatus(True, device, "USB-TTL serial")
        if device.upper().startswith("COM"):
            return PathStatus(True, device, label.split("—", 1)[-1].strip() if "—" in label else "USB serial")
    for device, label in choices:
        text = f"{device} {label}".upper()
        if any(h in text for h in avoid):
            continue
        if device.startswith("/dev/cu.usbserial") or device.upper().startswith("COM"):
            return PathStatus(True, device, label)
    return PathStatus(False, "—", "No CH340/USB-TTL adapter found")


def _no_window_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def _sdr_probe_candidates() -> list[tuple[str, Path | None]]:
    """Ordered (exe, cwd) pairs. Bundled rtl_433 first — PATH is often empty on Windows."""
    seen: set[str] = set()
    out: list[tuple[str, Path | None]] = []

    def add(exe: str, cwd: Path | None = None) -> None:
        path = Path(exe)
        key = str(path.resolve()) if path.is_file() else exe
        if key in seen:
            return
        seen.add(key)
        out.append((exe, cwd))

    try:
        from config import get_rtl433_dir, get_rtl433_exe

        bundled = get_rtl433_exe()
        if bundled.is_file():
            add(str(bundled), get_rtl433_dir())
    except Exception:
        pass

    try:
        from .rtl433 import rtl_433_path

        path = rtl_433_path()
        if path:
            add(path, Path(path).parent)
    except Exception:
        pass

    for name in ("rtl_test", "rtl_433-rtlsdr", "rtl_433"):
        found = shutil.which(name)
        if found:
            add(found, Path(found).parent)

    return out


def _interpret_sdr_probe(path: str, text: str) -> PathStatus | None:
    """Return a PathStatus when the probe output is conclusive; else None."""
    lower = text.lower()
    if "claimed by second instance" in text or "usb_claim_interface" in text:
        return PathStatus(True, path, "RTL-SDR present (in use by another process)")
    if "No supported devices found" in text:
        return PathStatus(
            False,
            path,
            "dongle not detected — plug in RTL-SDR or install WinUSB with Zadig",
        )
    if "Failed to open" in text or "usb_open" in lower:
        if "Found 1 device" in text or "Found 2 device" in text or "Using device" in text:
            return PathStatus(True, path, "RTL-SDR present (may be in use)")
        return PathStatus(False, path, "dongle not detected — check Zadig WinUSB driver")
    if "Using device" in text or "Found 1 device" in text or "Tuned to" in text or "Rafael Micro" in text:
        name = "RTL-SDR"
        for line in text.splitlines():
            if "NESDR" in line or "Nooelec" in line or "RTL2832" in line:
                name = line.strip()[:60]
                break
        return PathStatus(True, path, name)
    return None


def _sdr_status() -> PathStatus:
    candidates = _sdr_probe_candidates()
    if not candidates:
        return PathStatus(False, "—", "rtl_433 / rtl_test not installed")

    last_detail = "dongle not detected"
    last_path = candidates[0][0]
    for path, cwd in candidates:
        last_path = path
        is_rtl_test = Path(path).stem.lower() == "rtl_test"
        cmd = [path, "-t"] if is_rtl_test else [path, "-f", "433.92M", "-T", "2", "-F", "null"]
        timeout = 8 if is_rtl_test else 12
        run_cwd = str(cwd) if cwd and cwd.is_dir() else None
        env = None
        if run_cwd and sys.platform == "win32":
            # Companion DLLs (rtlsdr.dll, libusb) live next to the bundled exe.
            env = os.environ.copy()
            env["PATH"] = run_cwd + os.pathsep + env.get("PATH", "")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                cwd=run_cwd,
                env=env,
                **_no_window_kwargs(),
            )
        except subprocess.TimeoutExpired:
            # Device opened long enough to hang the short probe — treat as present.
            return PathStatus(True, path, "RTL-SDR (probe timed out — device likely OK)")
        except Exception as exc:
            last_detail = str(exc)
            continue

        text = (proc.stdout or "") + (proc.stderr or "")
        interpreted = _interpret_sdr_probe(path, text)
        if interpreted is not None:
            return interpreted
        if proc.returncode == 0:
            return PathStatus(True, path, "RTL-SDR")
        last_detail = "dongle not detected — check cable / Zadig WinUSB"

    return PathStatus(False, last_path, last_detail)


def check_hardware_trio() -> HardwareTrio:
    """Probe USB-TTL (board TX/RX) and RTL-SDR. J-Link is removed."""
    return HardwareTrio(
        usb_ttl=_ttl_status(),
        jlink=PathStatus(False, "—", "removed — board RX is USB-TTL only"),
        sdr=_sdr_status(),
    )


def preferred_usb_ttl_port() -> str:
    """Device path for BenchRunner — never a J-Link CDC UART."""
    status = _ttl_status()
    if status.ok:
        return status.label
    ports = find_serial_ports()
    if ports:
        return port_device(ports[0])
    return "/dev/cu.usbserial-130" if sys.platform == "darwin" else "COM3"
