"""Optional pyserial-based UART transport."""

import time
from collections.abc import Callable
from typing import Any

from ..exceptions import TransportClosedError, TransportError
from .base import HamatonTransport

SerialFactory = Callable[..., Any]


def _load_serial_factory() -> SerialFactory:
    """Load pyserial only when a physical UART is opened."""
    try:
        import serial
    except ImportError as error:
        raise TransportError(
            "UART support requires pyserial; install hamaton-sdk-python[uart]"
        ) from error
    return serial.Serial


class UartTransport(HamatonTransport):
    """Hamaton 115200-baud, 8N1 UART transport.

    The protocol specifies 3.3 V TTL electrical levels. A suitable USB-to-TTL
    adapter is required; a standard RS-232 port must not be connected directly.
    """

    DEFAULT_BAUD_RATE = 115200
    DEFAULT_POST_WRITE_DELAY_SECONDS = 0.2
    BYTESIZE = 8
    STOPBITS = 1
    PARITY = "N"

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUD_RATE,
        write_timeout_seconds: float = 1.0,
        post_write_delay_seconds: float = DEFAULT_POST_WRITE_DELAY_SECONDS,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        if not isinstance(port, str):
            raise TypeError("port must be a string")
        if not port.strip():
            raise ValueError("port cannot be empty")
        if not isinstance(baudrate, int):
            raise TypeError("baudrate must be an integer")
        if baudrate <= 0:
            raise ValueError("baudrate must be greater than zero")
        if write_timeout_seconds < 0:
            raise ValueError("write_timeout_seconds cannot be negative")
        if post_write_delay_seconds < 0:
            raise ValueError("post_write_delay_seconds cannot be negative")

        self.port = port
        self.baudrate = baudrate
        self.write_timeout_seconds = float(write_timeout_seconds)
        self.post_write_delay_seconds = float(post_write_delay_seconds)
        self._serial_factory = serial_factory
        self._serial: Any | None = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and bool(self._serial.is_open)

    def open(self) -> None:
        if self.is_open:
            return
        factory = self._serial_factory or _load_serial_factory()
        try:
            self._serial = factory(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.BYTESIZE,
                parity=self.PARITY,
                stopbits=self.STOPBITS,
                timeout=0,
                write_timeout=self.write_timeout_seconds,
            )
        except Exception as error:
            self._serial = None
            raise TransportError(f"could not open UART port {self.port}: {error}") from error

    def close(self) -> None:
        serial_connection = self._serial
        self._serial = None
        if serial_connection is not None:
            try:
                serial_connection.close()
            except Exception as error:
                raise TransportError(f"could not close UART port: {error}") from error

    def write(self, data: bytes) -> None:
        self.validate_write_data(data)
        serial_connection = self._require_open()
        try:
            serial_connection.reset_input_buffer()
            written = serial_connection.write(data)
            if written != len(data):
                raise TransportError(
                    f"UART wrote {written} of {len(data)} requested bytes"
                )
            serial_connection.flush()
            if self.post_write_delay_seconds:
                time.sleep(self.post_write_delay_seconds)
        except TransportError:
            raise
        except Exception as error:
            raise TransportError(f"could not write to UART: {error}") from error

    def read(self, max_bytes: int, timeout_seconds: float) -> bytes:
        self.validate_read_arguments(max_bytes, timeout_seconds)
        serial_connection = self._require_open()
        old_timeout = serial_connection.timeout
        try:
            serial_connection.timeout = timeout_seconds
            first_byte = serial_connection.read(1)
            if not first_byte:
                return b""

            # Drain bytes already buffered by the adapter, matching read_all().
            serial_connection.timeout = 0
            buffered = bytearray(first_byte)
            while len(buffered) < max_bytes:
                waiting = serial_connection.in_waiting
                if waiting <= 0:
                    break
                buffered.extend(
                    serial_connection.read(min(max_bytes - len(buffered), waiting))
                )
            return bytes(buffered)
        except Exception as error:
            raise TransportError(f"could not read from UART: {error}") from error
        finally:
            serial_connection.timeout = old_timeout

    def _require_open(self) -> Any:
        if not self.is_open:
            raise TransportClosedError("UART transport is closed")
        return self._serial
