"""Detect USB-TTL (board TX/RX) and RTL-SDR. No J-Link path."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

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


def _sdr_status() -> PathStatus:
    for binary in ("rtl_test", "rtl_433"):
        path = shutil.which(binary)
        if not path:
            continue
        try:
            if binary == "rtl_test":
                proc = subprocess.run(
                    [path, "-t"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            else:
                proc = subprocess.run(
                    [path, "-f", "433.92M", "-T", "2", "-F", "log"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            text = (proc.stdout or "") + (proc.stderr or "")
            if "No supported devices found" in text or "Failed to open" in text:
                if "Found 1 device" in text or "Found 2 device" in text or "Using device" in text:
                    return PathStatus(True, path, "RTL-SDR present (may be in use)")
                return PathStatus(False, path, "dongle not detected")
            if "Using device" in text or "Found 1 device" in text or "Tuned to" in text or "Rafael Micro" in text:
                name = "RTL-SDR"
                for line in text.splitlines():
                    if "NESDR" in line or "Nooelec" in line or "RTL2832" in line:
                        name = line.strip()[:60]
                        break
                return PathStatus(True, path, name)
            if "claimed by second instance" in text or "usb_claim_interface" in text:
                return PathStatus(True, path, "RTL-SDR present (in use by another process)")
        except Exception as exc:
            return PathStatus(False, path, str(exc))

    try:
        from config import get_rtl433_exe

        exe = get_rtl433_exe()
        if exe.is_file():
            return PathStatus(False, str(exe), "rtl_433 found but no RTL-SDR dongle")
    except Exception:
        pass
    return PathStatus(False, "—", "rtl_433 / rtl_test not installed")


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
