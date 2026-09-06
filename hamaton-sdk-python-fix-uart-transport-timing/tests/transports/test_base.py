"""Tests for the hardware-independent transport contract."""

import pytest

from hamaton.transports.base import HamatonTransport


class RecordingTransport(HamatonTransport):
    def __init__(self) -> None:
        self._open = False
        self.open_calls = 0
        self.close_calls = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self.open_calls += 1
        self._open = True

    def close(self) -> None:
        self.close_calls += 1
        self._open = False

    def write(self, data: bytes) -> None:
        self.validate_write_data(data)

    def read(self, max_bytes: int, timeout_seconds: float) -> bytes:
        self.validate_read_arguments(max_bytes, timeout_seconds)
        return b""


def test_context_manager_opens_and_closes_transport() -> None:
    transport = RecordingTransport()

    with transport as opened_transport:
        assert opened_transport is transport
        assert transport.is_open

    assert not transport.is_open
    assert transport.open_calls == 1
    assert transport.close_calls == 1


@pytest.mark.parametrize("max_bytes", [0, -1])
def test_read_size_must_be_positive(max_bytes: int) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        HamatonTransport.validate_read_arguments(max_bytes, 0)


def test_read_timeout_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        HamatonTransport.validate_read_arguments(1, -0.1)


def test_write_data_must_be_bytes() -> None:
    with pytest.raises(TypeError, match="must be bytes"):
        HamatonTransport.validate_write_data(bytearray(b"data"))  # type: ignore[arg-type]
