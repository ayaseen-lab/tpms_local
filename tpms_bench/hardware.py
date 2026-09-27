"""Detect USB-TTL, optional J-Link (SWD), and RTL-SDR so the suite picks the right path."""

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
    def board_ready(self) -> bool:
        """Board path is ready when USB-TTL is present. J-Link is optional."""
        return self.usb_ttl.ok

    @property
    def all_ok(self) -> bool:
        # J-Link is NOT required: Windows client boards reply on USB-TTL RX.
        return self.usb_ttl.ok and self.sdr.ok

    def summary_lines(self) -> list[str]:
        jlink_mark = "OK" if self.jlink.ok else "OPTIONAL"
        return [
            f"USB-TTL  [{'OK' if self.usb_ttl.ok else 'MISSING'}]  {self.usb_ttl.label}"
            + (f" — {self.usb_ttl.detail}" if self.usb_ttl.detail else ""),
            f"J-Link   [{jlink_mark}]  {self.jlink.label}"
            + (f" — {self.jlink.detail}" if self.jlink.detail else ""),
            f"SDR      [{'OK' if self.sdr.ok else 'MISSING'}]  {self.sdr.label}"
            + (f" — {self.sdr.detail}" if self.sdr.detail else ""),
        ]


def _ttl_status() -> PathStatus:
    choices = list_serial_port_choices()
    for device, label in choices:
        text = label.upper()
        if any(h in text for h in ("JLINK", "SEGGER", "BLUETOOTH")):
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
            )
        ):
            return PathStatus(True, device, label.split("—", 1)[-1].strip() if "—" in label else "USB-TTL")
        if device.startswith("/dev/cu.usbserial"):
            return PathStatus(True, device, "USB-TTL serial")
        # Windows client: any non-J-Link COM port is a candidate board adapter.
        if device.upper().startswith("COM"):
            return PathStatus(True, device, label.split("—", 1)[-1].strip() if "—" in label else "USB serial")
    # Fallback: first non-J-Link cu.* / COM port
    for device, label in choices:
        if "JLINK" in label.upper() or "SEGGER" in label.upper():
            continue
        if device.startswith("/dev/cu.") or device.upper().startswith("COM"):
            return PathStatus(True, device, label)
    return PathStatus(False, "—", "No CH340/USB-TTL adapter found")


def _jlink_status() -> PathStatus:
    """J-Link is optional. Missing probe is not a hardware failure."""
    usb = False
    for p in serial.tools.list_ports.comports():
        text = f"{p.device} {p.description} {p.manufacturer} {p.hwid}".upper()
        if "SEGGER" in text or "JLINK" in text or "J-LINK" in text:
            usb = True
            break
    try:
        from . import jlink_ram

        if not jlink_ram.jlink_available():
            return PathStatus(
                False,
                "—",
                "optional — not required when board USB RX works",
            )
        exe = jlink_ram.jlink_exe()
        dump = jlink_ram.dump_sram_result()
        if dump.ok:
            return PathStatus(True, exe, f"SWD connected · SRAM {len(dump.blob)} bytes")
        if usb:
            return PathStatus(
                False,
                exe,
                "optional — USB present but SWD not connected (USB RX path still OK)",
            )
        return PathStatus(
            False,
            exe if exe else "JLinkExe",
            "optional — not required when board USB RX works",
        )
    except Exception as exc:
        return PathStatus(False, "—", f"optional — {exc}")


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

    # Fall back to app resolver (Windows bundled vendor rtl_433).
    try:
        from config import get_rtl433_exe

        exe = get_rtl433_exe()
        if exe.is_file():
            return PathStatus(False, str(exe), "rtl_433 found but no RTL-SDR dongle")
    except Exception:
        pass
    return PathStatus(False, "—", "rtl_433 / rtl_test not installed")


def check_hardware_trio() -> HardwareTrio:
    """Probe USB-TTL (required), J-Link (optional fallback), and RTL-SDR."""
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
