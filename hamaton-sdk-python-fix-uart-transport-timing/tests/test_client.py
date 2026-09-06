"""Mock-transport tests for the client transaction engine."""

from collections.abc import Iterable

import pytest

from hamaton.client import HamatonClient
from hamaton.codec import CommandCodec
from hamaton.exceptions import CommandTimeoutError, TransportClosedError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult
from hamaton.transports.mock import MockTransport


class ExampleCodec(CommandCodec):
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        super().__init__(0x20, timeout_seconds=timeout_seconds)

    def build_request_data(self) -> bytes:
        return b"\x5A"

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return CommandResult.failure(frame.payload[2])
        if frame.payload[2] == 0x00:
            return CommandResult.pending(message="operation in progress")
        return CommandResult.success(frame.payload[2:])


class InvalidResultCodec(ExampleCodec):
    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        return "invalid"  # type: ignore[return-value]


class ScriptedClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class TimeoutOnceTransport(MockTransport):
    def __init__(self, response_data: bytes) -> None:
        super().__init__([response_data], open_immediately=True)
        self._timeout_returned = False

    def read(self, max_bytes: int, timeout_seconds: float) -> bytes:
        if not self._timeout_returned:
            self.validate_read_arguments(max_bytes, timeout_seconds)
            self._require_open()
            self.read_requests.append((max_bytes, timeout_seconds))
            self._timeout_returned = True
            return b""
        return super().read(max_bytes, timeout_seconds)


def response(payload: bytes) -> bytes:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload).to_bytes()


def test_execute_writes_request_and_returns_success() -> None:
    transport = MockTransport(
        [response(b"\x20\x01\x01reading")], open_immediately=True
    )
    client = HamatonClient(transport)

    result = client.execute(ExampleCodec())

    assert transport.writes == [bytes.fromhex("3C 11 00 03 20 01 5A 3E")]
    assert result.is_success
    assert result.value == b"\x01reading"


def test_execute_parses_response_split_across_reads() -> None:
    raw_response = response(b"\x20\x01\x01done")
    transport = MockTransport(
        [raw_response[:3], raw_response[3:6], raw_response[6:]],
        open_immediately=True,
    )

    result = HamatonClient(transport).execute(ExampleCodec())

    assert result.is_success
    assert len(transport.read_requests) == 3


def test_unrelated_frames_are_ignored() -> None:
    unrelated = response(b"\x40\x01version")
    matching = response(b"\x20\x01\x01done")
    transport = MockTransport([unrelated, matching], open_immediately=True)

    result = HamatonClient(transport).execute(ExampleCodec())

    assert result.value == b"\x01done"
    assert len(transport.read_requests) == 2


def test_matching_frame_after_unrelated_frame_in_same_chunk_is_used() -> None:
    received = response(b"\x40\x01version") + response(b"\x20\x01\x01done")
    transport = MockTransport([received], open_immediately=True)

    result = HamatonClient(transport).execute(ExampleCodec())

    assert result.value == b"\x01done"
    assert len(transport.read_requests) == 1


def test_negative_response_is_returned_as_terminal_failure() -> None:
    transport = MockTransport(
        [response(b"\xA0\x01\x03")], open_immediately=True
    )

    result = HamatonClient(transport).execute(ExampleCodec())

    assert result.is_failure
    assert result.error_code == 0x03


def test_empty_transport_read_causes_timeout() -> None:
    transport = MockTransport(open_immediately=True)
    client = HamatonClient(transport, clock=ScriptedClock([0, 0]))

    with pytest.raises(CommandTimeoutError, match="0x20.*10 seconds"):
        client.execute(ExampleCodec())

    assert transport.read_requests == [(256, 10.0)]


def test_expired_deadline_causes_timeout_before_read() -> None:
    transport = MockTransport(open_immediately=True)
    client = HamatonClient(transport, clock=ScriptedClock([0, 11]))

    with pytest.raises(CommandTimeoutError, match="did not complete"):
        client.execute(ExampleCodec())

    assert transport.read_requests == []


def test_pending_response_resets_complete_command_timeout() -> None:
    transport = MockTransport(
        [response(b"\x20\x01\x00"), response(b"\x20\x01\x01done")],
        open_immediately=True,
    )
    clock = ScriptedClock([0, 3, 5, 6])

    result = HamatonClient(transport, clock=clock).execute(ExampleCodec())

    assert result.is_success
    assert transport.read_requests == [(256, 7.0), (256, 9.0)]


def test_pending_and_success_can_arrive_in_same_read_chunk() -> None:
    received = response(b"\x20\x01\x00") + response(b"\x20\x01\x01done")
    transport = MockTransport([received], open_immediately=True)
    clock = ScriptedClock([0, 1, 2])

    result = HamatonClient(transport, clock=clock).execute(ExampleCodec())

    assert result.is_success
    assert len(transport.read_requests) == 1


def test_execute_requires_open_transport() -> None:
    with pytest.raises(TransportClosedError, match="closed"):
        HamatonClient(MockTransport()).execute(ExampleCodec())


def test_client_context_manager_owns_transport_lifecycle() -> None:
    transport = MockTransport([response(b"\x20\x01\x01done")])

    with HamatonClient(transport) as client:
        assert client.is_open
        assert client.execute(ExampleCodec()).is_success

    assert not transport.is_open


def test_codec_must_return_command_result() -> None:
    transport = MockTransport(
        [response(b"\x20\x01\x01done")], open_immediately=True
    )

    with pytest.raises(TypeError, match="must return CommandResult"):
        HamatonClient(transport).execute(InvalidResultCodec())


def test_read_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        HamatonClient(MockTransport(), read_size=0)


def test_codec_can_request_retry_after_transport_timeout() -> None:
    transport = TimeoutOnceTransport(response(b"\x20\x01\x01done"))
    codec = ExampleCodec()
    codec.max_attempts = 2

    result = HamatonClient(transport).execute(codec)

    assert result.is_success
    assert transport.writes == [codec.build_request(), codec.build_request()]
