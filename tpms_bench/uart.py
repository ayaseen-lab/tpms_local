"""Open USB-TTL UART for Hamaton board communication."""

from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports

DEFAULT_BAUD = 115200


def find_serial_ports() -> list[str]:
    """Return available serial ports, preferring USB-TTL adapters."""
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        return []
    preferred = [
        p
        for p in ports
        if any(k in p.upper() for k in ("USB", "SERIAL", "CH340", "CP210", "FTDI", "SLAB", "UART"))
    ]
    return preferred or ports


def default_port() -> str:
    ports = find_serial_ports()
    if not ports:
        if sys.platform == "darwin":
            return "/dev/cu.usbserial-130"
        return "COM3"
    return ports[0]


def open_uart(port: str | None = None, baudrate: int = DEFAULT_BAUD) -> serial.Serial:
    port = port or default_port()
    if not port:
        raise serial.SerialException("No serial port available for USB-TTL")
    ser = serial.Serial(
        port,
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
        raise serial.SerialException(f"Could not open serial port {port}")
    return ser


def verify_port(port: str) -> str:
    """Open/close port to verify it exists. Returns port or raises."""
    ser = open_uart(port)
    name = ser.port
    ser.close()
    return name
