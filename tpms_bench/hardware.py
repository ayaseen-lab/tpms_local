"""Detect USB-TTL, J-Link (SWD), and RTL-SDR so the suite uses the right path for each."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

import serial.tools.list_ports

from .uart import find_serial_ports, list_serial_port_choices, port_device


@dataclass
class PathStatus:
    ok: bool
    label: str
    detail: str = ""


@dataclass
class HardwareTrio:
    usb_ttl: PathStatus
    jlink: PathStatus
    sdr: PathStatus

    @property
    def all_ok(self) -> bool:
        return self.usb_ttl.ok and self.jlink.ok and self.sdr.ok

    def summary_lines(self) -> list[str]:
        def mark(p: PathStatus) -> str:
            return "OK" if p.ok else "MISSING"

        return [
            f"USB-TTL  [{mark(self.usb_ttl)}]  {self.usb_ttl.label}"
            + (f" — {self.usb_ttl.detail}" if self.usb_ttl.detail else ""),
            f"J-Link   [{mark(self.jlink)}]  {self.jlink.label}"
            + (f" — {self.jlink.detail}" if self.jlink.detail else ""),
            f"SDR      [{mark(self.sdr)}]  {self.sdr.label}"
            + (f" — {self.sdr.detail}" if self.sdr.detail else ""),
        ]


def _ttl_status() -> PathStatus:
    choices = list_serial_port_choices()
    for device, label in choices:
        text = label.upper()
        if any(h in text for h in ("JLINK", "SEGGER", "BLUETOOTH")):
            continue
        if any(h in text for h in ("USB SERIAL", "USB-SERIAL", "CH340", "CP210", "FTDI", "SLAB", "UART")):
            return PathStatus(True, device, label.split("—", 1)[-1].strip() if "—" in label else "USB-TTL")
        if device.startswith("/dev/cu.usbserial"):
            return PathStatus(True, device, "USB-TTL serial")
    # Fallback: first non-J-Link cu.* port
    for device, label in choices:
        if "JLINK" in label.upper() or "SEGGER" in label.upper():
            continue
        if device.startswith("/dev/cu.") or device.upper().startswith("COM"):
            return PathStatus(True, device, label)
    return PathStatus(False, "—", "No CH340/USB-TTL adapter found")


def _jlink_status() -> PathStatus:
    usb = False
    for p in serial.tools.list_ports.comports():
        text = f"{p.device} {p.description} {p.manufacturer} {p.hwid}".upper()
        if "SEGGER" in text or "JLINK" in text or "J-LINK" in text:
            usb = True
            break
    try:
        from . import jlink_ram

        exe = jlink_ram.jlink_exe()
        dump = jlink_ram.dump_sram_result()
        if dump.ok:
            return PathStatus(True, exe, f"SWD connected · SRAM {len(dump.blob)} bytes")
        if usb:
            return PathStatus(
                False,
                exe,
                dump.message or "USB present but SWD not connected to nRF52840",
            )
        return PathStatus(False, exe if exe else "JLinkExe", dump.message or "not found")
    except Exception as exc:
        if usb:
            return PathStatus(False, "J-Link USB", str(exc))
        return PathStatus(False, "—", str(exc))


def _sdr_status() -> PathStatus:
    # Prefer rtl_test when available.
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
                # Device may be busy (app already listening) — still count as present if Found N device
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

    # Fall back to app resolver.
    try:
        from config import get_rtl433_exe

        exe = get_rtl433_exe()
        if exe.is_file():
            return PathStatus(False, str(exe), "rtl_433 found but no RTL-SDR dongle")
    except Exception:
        pass
    return PathStatus(False, "—", "rtl_433 / rtl_test not installed")


def check_hardware_trio() -> HardwareTrio:
    """Probe USB-TTL (board TX), J-Link SWD (board RX fallback), and RTL-SDR."""
    return HardwareTrio(usb_ttl=_ttl_status(), jlink=_jlink_status(), sdr=_sdr_status())


def preferred_usb_ttl_port() -> str:
    """Device path for BenchRunner — never the J-Link CDC UART."""
    status = _ttl_status()
    if status.ok:
        return status.label
    # Fall back to labeled combo default.
    ports = find_serial_ports()
    if ports:
        return port_device(ports[0])
    return "/dev/cu.usbserial-130" if sys.platform == "darwin" else "COM3"
