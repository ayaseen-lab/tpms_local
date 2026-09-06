"""Tests for the optional pyserial UART transport."""

from typing import Any

import pytest

from hamaton.client import HamatonClient
from hamaton.commands.query_version import QueryVersionCodec
from hamaton.exceptions import TransportClosedError, TransportError
from hamaton.models import VersionInfo
from hamaton.transports import uart
from hamaton.transports.uart import UartTransport

QUERY_VERSION_REQUEST = bytes.fromhex("3C 11 00 02 40 01 3E")
QUERY_VERSION_RESPONSE = bytes.fromhex(
    "3C 22 00 16 40 01 "
    "00 00 00 03 "
    "00 00 00 03 "
    "00 00 00 25 "
    "00 00 00 26 "
    "00 00 00 49 "
    "3E"
)


class FakeSerial:
    def __init__(self, read_data: bytes = b"") -> None:
        self.is_open = True
        self.timeout: float | None = 0
        self.read_data = read_data
        self.writes: list[bytes] = []
        self.calls: list[tuple[str, bytes | None]] = []
        self.reset_input_buffer_calls = 0
        self.flush_calls = 0
        self.close_calls = 0
        self.read_calls: list[int] = []
        self.in_waiting = len(read_data)

    def write(self, data: bytes) -> int:
        self.calls.append(("write", data))
        self.writes.append(data)
        return len(data)

    def reset_input_buffer(self) -> None:
        self.calls.append(("reset_input_buffer", None))
        self.reset_input_buffer_calls += 1

    def flush(self) -> None:
        self.calls.append(("flush", None))
        self.flush_calls += 1

    def read(self, max_bytes: int) -> bytes:
        self.read_calls.append(max_bytes)
        chunk = self.read_data[:max_bytes]
        self.read_data = self.read_data[len(chunk) :]
        self.in_waiting = len(self.read_data)
        return chunk

    def close(self) -> None:
        self.close_calls += 1
        self.is_open = False


class FakeSerialFactory:
    def __init__(self, connection: FakeSerial) -> None:
        self.connection = connection
        self.arguments: dict[str, Any] | None = None

    def __call__(self, **arguments: Any) -> FakeSerial:
        self.arguments = arguments
        return self.connection


def test_open_uses_protocol_uart_settings() -> None:
    connection = FakeSerial()
    factory = FakeSerialFactory(connection)
    transport = UartTransport("COM12", serial_factory=factory)

    transport.open()

    assert transport.is_open
    assert transport.baudrate == UartTransport.DEFAULT_BAUD_RATE
    assert transport.post_write_delay_seconds == (
        UartTransport.DEFAULT_POST_WRITE_DELAY_SECONDS
    )
    assert factory.arguments == {
        "port": "COM12",
        "baudrate": 115200,
        "bytesize": 8,
        "parity": "N",
        "stopbits": 1,
        "timeout": 0,
        "write_timeout": 1.0,
    }


def test_open_accepts_custom_baudrate() -> None:
    connection = FakeSerial()
    factory = FakeSerialFactory(connection)
    transport = UartTransport("COM12", baudrate=9600, serial_factory=factory)

    transport.open()

    assert factory.arguments is not None
    assert factory.arguments["baudrate"] == 9600


def test_write_resets_input_then_sends_exact_bytes_and_flushes() -> None:
    connection = FakeSerial()
    transport = UartTransport("COM12", serial_factory=FakeSerialFactory(connection))
    transport.open()

    transport.write(b"frame")

    assert connection.calls == [
        ("reset_input_buffer", None),
        ("write", b"frame"),
        ("flush", None),
    ]
    assert connection.reset_input_buffer_calls == 1
    assert connection.writes == [b"frame"]
    assert connection.flush_calls == 1


def test_read_temporarily_applies_call_timeout() -> None:
    connection = FakeSerial(b"response")
    connection.timeout = 3.0
    transport = UartTransport("COM12", serial_factory=FakeSerialFactory(connection))
    transport.open()

    result = transport.read(4, 0.25)

    assert result == b"resp"
    assert connection.read_calls == [1, 3]
    assert connection.timeout == 3.0


def test_read_drains_adapter_buffer_like_read_all() -> None:
    connection = FakeSerial(b"full-response")
    transport = UartTransport(
        "COM12",
        post_write_delay_seconds=0,
        serial_factory=FakeSerialFactory(connection),
    )
    transport.open()

    result = transport.read(256, 1.0)

    assert result == b"full-response"
    assert connection.read_calls == [1, 12]


def test_read_returns_empty_bytes_when_first_byte_times_out() -> None:
    connection = FakeSerial()
    transport = UartTransport(
        "COM12",
        post_write_delay_seconds=0,
        serial_factory=FakeSerialFactory(connection),
    )
    transport.open()

    assert transport.read(256, 0.5) == b""
    assert connection.read_calls == [1]


def test_write_waits_for_post_write_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSerial()
    transport = UartTransport(
        "COM12",
        post_write_delay_seconds=UartTransport.DEFAULT_POST_WRITE_DELAY_SECONDS,
        serial_factory=FakeSerialFactory(connection),
    )
    transport.open()
    sleeps: list[float] = []
    monkeypatch.setattr("hamaton.transports.uart.time.sleep", sleeps.append)

    transport.write(b"frame")

    assert sleeps == [UartTransport.DEFAULT_POST_WRITE_DELAY_SECONDS]


def test_write_skips_delay_when_post_write_delay_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSerial()
    transport = UartTransport(
        "COM12",
        post_write_delay_seconds=0,
        serial_factory=FakeSerialFactory(connection),
    )
    transport.open()
    sleeps: list[float] = []
    monkeypatch.setattr("hamaton.transports.uart.time.sleep", sleeps.append)

    transport.write(b"frame")

    assert sleeps == []


def test_read_returns_recorded_query_version_frame_in_one_call() -> None:
    connection = FakeSerial(QUERY_VERSION_RESPONSE)
    transport = UartTransport(
        "COM12",
        post_write_delay_seconds=0,
        serial_factory=FakeSerialFactory(connection),
    )
    transport.open()

    result = transport.read(len(QUERY_VERSION_RESPONSE), 2.0)

    assert result == QUERY_VERSION_RESPONSE
    assert connection.read_calls == [1, len(QUERY_VERSION_RESPONSE) - 1]


def test_client_executes_query_version_through_uart_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSerial(QUERY_VERSION_RESPONSE)
    transport = UartTransport(
        "COM12",
        post_write_delay_seconds=0,
        serial_factory=FakeSerialFactory(connection),
    )
    monkeypatch.setattr("hamaton.transports.uart.time.sleep", lambda _: None)

    with HamatonClient(transport) as client:
        result = client.execute(QueryVersionCodec())

    assert result.is_success
    assert result.value == VersionInfo(
        hardware_version=3,
        boot_version=3,
        software_version=37,
        trigger_database_version=38,
        programming_database_version=73,
    )
    assert connection.writes == [QUERY_VERSION_REQUEST]
    assert len(connection.read_calls) == 2


def test_close_is_idempotent() -> None:
    connection = FakeSerial()
    transport = UartTransport("COM12", serial_factory=FakeSerialFactory(connection))
    transport.open()

    transport.close()
    transport.close()

    assert connection.close_calls == 1
    assert not transport.is_open


def test_operations_require_an_open_port() -> None:
    transport = UartTransport("COM12", serial_factory=FakeSerialFactory(FakeSerial()))

    with pytest.raises(TransportClosedError, match="closed"):
        transport.write(b"data")
    with pytest.raises(TransportClosedError, match="closed"):
        transport.read(1, 0)


def test_open_wraps_serial_errors() -> None:
    def failing_factory(**arguments: Any) -> FakeSerial:
        del arguments
        raise OSError("port unavailable")

    with pytest.raises(TransportError, match="could not open"):
        UartTransport("COM12", serial_factory=failing_factory).open()


def test_partial_write_is_an_error() -> None:
    connection = FakeSerial()
    connection.write = lambda data: len(data) - 1  # type: ignore[method-assign]
    transport = UartTransport("COM12", serial_factory=FakeSerialFactory(connection))
    transport.open()

    with pytest.raises(TransportError, match="requested bytes"):
        transport.write(b"frame")


def test_pyserial_is_loaded_only_when_opening_uart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = UartTransport("COM12")

    def missing_pyserial() -> Any:
        raise TransportError("pyserial missing")

    monkeypatch.setattr(uart, "_load_serial_factory", missing_pyserial)

    with pytest.raises(TransportError, match="pyserial missing"):
        transport.open()


def test_invalid_port_is_rejected_before_loading_pyserial() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        UartTransport("  ")


@pytest.mark.parametrize(
    ("argument_name", "value", "message"),
    [
        ("baudrate", 0, "baudrate must be greater than zero"),
        ("post_write_delay_seconds", -1, "post_write_delay_seconds cannot be negative"),
    ],
)
def test_invalid_uart_settings_are_rejected(
    argument_name: str,
    value: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        UartTransport("COM12", **{argument_name: value})
