"""Tests for the in-memory mock transport."""

import pytest

from hamaton.exceptions import TransportClosedError
from hamaton.transports.mock import MockTransport


def test_records_writes_in_order() -> None:
    transport = MockTransport(open_immediately=True)

    transport.write(b"first")
    transport.write(b"second")

    assert transport.writes == [b"first", b"second"]


def test_returns_queued_read_chunks_in_order() -> None:
    transport = MockTransport([b"first", b"second"], open_immediately=True)

    assert transport.read(100, 0) == b"first"
    assert transport.read(100, 0) == b"second"
    assert transport.read(100, 0) == b""


def test_large_chunk_is_split_at_max_bytes() -> None:
    transport = MockTransport([b"abcdef"], open_immediately=True)

    assert transport.read(2, 0) == b"ab"
    assert transport.read(3, 0) == b"cde"
    assert transport.read(3, 0) == b"f"


def test_queue_read_ignores_empty_chunks() -> None:
    transport = MockTransport()

    transport.queue_read(b"")

    assert transport.pending_read_count == 0


def test_reads_and_writes_require_open_transport() -> None:
    transport = MockTransport()

    with pytest.raises(TransportClosedError, match="closed"):
        transport.write(b"data")
    with pytest.raises(TransportClosedError, match="closed"):
        transport.read(1, 0)


def test_close_is_idempotent_and_transport_can_reopen() -> None:
    transport = MockTransport(open_immediately=True)

    transport.close()
    transport.close()
    transport.open()

    assert transport.is_open


def test_clear_discards_writes_and_pending_input() -> None:
    transport = MockTransport([b"input"], open_immediately=True)
    transport.write(b"output")

    transport.clear()

    assert transport.writes == []
    assert transport.read_requests == []
    assert transport.pending_read_count == 0
