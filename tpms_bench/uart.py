"""Open USB-TTL UART for Hamaton board communication."""

from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports

DEFAULT_BAUD = 115200

# Prefer real USB-TTL adapters over J-Link CDC UART / Bluetooth virtual COM ports.
_PREFERRED_HINTS = ("CH340", "CP210", "FTDI", "SLAB", "USB-SERIAL", "USB SERIAL", "UART")
_AVOID_HINTS = ("BLUETOOTH", "JLINK", "SEGGER", "AMT", "SOL")


def _port_label(port) -> str:
    """Human label: 'COM8 — USB-SERIAL CH340'."""
    desc = (port.description or "").strip() or (port.manufacturer or "").strip() or "Serial"
    return f"{port.device} — {desc}"


def _score_port(port) -> int:
    text = f"{port.device} {port.description} {port.manufacturer} {port.hwid}".upper()
    score = 0
    if any(h in text for h in _PREFERRED_HINTS):
        score += 100
    if "USB" in text:
        score += 10
    if any(h in text for h in _AVOID_HINTS):
        score -= 100
    return score


def list_serial_port_choices() -> list[tuple[str, str]]:
    """Return (device, label) pairs, preferred USB-TTL first."""
    ports = list(serial.tools.list_ports.comports())
    ports.sort(key=_score_port, reverse=True)
    return [(p.device, _port_label(p)) for p in ports]


def find_serial_ports() -> list[str]:
    """Return COM devices with descriptions, preferred USB-TTL first."""
    choices = list_serial_port_choices()
    if not choices:
        return []
    # Show labels in the combo so CH340 vs J-Link CDC is obvious.
    return [label for _dev, label in choices]


def port_device(port: str | None) -> str:
    """Strip UI label down to COMx / /dev/..."""
    if not port:
        return ""
    text = str(port).strip()
    if "—" in text:
        return text.split("—", 1)[0].strip()
    if " - " in text and text.upper().startswith("COM"):
        return text.split(" - ", 1)[0].strip()
    return text


def default_port() -> str:
    choices = list_serial_port_choices()
    if not choices:
        if sys.platform == "darwin":
            return "/dev/cu.usbserial-130"
        return "COM3"
    return choices[0][1]  # labeled entry for the combo


def open_uart(port: str | None = None, baudrate: int = DEFAULT_BAUD) -> serial.Serial:
    raw = port or default_port()
    device = port_device(raw)
    if not device:
        raise serial.SerialException("No serial port available for USB-TTL")
    ser = serial.Serial(
        device,
        baudrate,
        timeout=0.2,
        write_timeout=2.0,
        dsrdtr=False,
        rtscts=False,
    )
    ser.dtr = False
    ser.rts = False
    time.sleep(0.05)
    if not ser.is_open:
        raise serial.SerialException(f"Could not open serial port {device}")
    return ser


def verify_port(port: str) -> str:
    """Open/close port to verify it exists. Returns device name or raises."""
    ser = open_uart(port)
    name = ser.port
    ser.close()
    return name
