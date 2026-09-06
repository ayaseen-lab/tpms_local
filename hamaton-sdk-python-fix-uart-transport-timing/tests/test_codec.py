"""Tests for the shared command codec contract."""

import pytest

from hamaton.codec import CommandCodec
from hamaton.exceptions import UnexpectedResponseError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult


class ExampleCodec(CommandCodec):
    def __init__(self) -> None:
        super().__init__(command=0x20, subcommand=0x01, timeout_seconds=12.0)

    def build_request_data(self) -> bytes:
        return b"\x5A"

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return CommandResult.failure(frame.payload[2])
        return CommandResult.success(frame.payload[2:])


class InvalidDataCodec(ExampleCodec):
    def build_request_data(self) -> bytes:
        return "not bytes"  # type: ignore[return-value]


def test_build_request_includes_uart_envelope_and_command_fields() -> None:
    codec = ExampleCodec()

    assert codec.build_request() == bytes.fromhex("3C 11 00 03 20 01 5A 3E")


def test_build_request_frame_is_available_for_protocol_code() -> None:
    frame = ExampleCodec().build_request_frame()

    assert frame.address == HamatonFrame.HOST_ADDRESS
    assert frame.payload == b"\x20\x01\x5A"


@pytest.mark.parametrize("command", [0x20, 0xA0])
def test_accepts_positive_and_negative_command_responses(command: int) -> None:
    codec = ExampleCodec()
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, bytes([command, 0x01, 0x03]))

    assert codec.accepts_response(frame)


def test_rejects_wrong_address_command_and_subcommand() -> None:
    codec = ExampleCodec()

    assert not codec.accepts_response(HamatonFrame(0x11, b"\x20\x01"))
    assert not codec.accepts_response(HamatonFrame(0x22, b"\x21\x01"))
    assert not codec.accepts_response(HamatonFrame(0x22, b"\x20\x02"))
    assert not codec.accepts_response(HamatonFrame(0x22, b"\x20"))


def test_parse_response_returns_shared_success_result() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"\x20\x01data")

    result = ExampleCodec().parse_response(frame)

    assert result.is_success
    assert result.value == b"data"


def test_parse_response_returns_shared_failure_result() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"\xA0\x01\x03")

    result = ExampleCodec().parse_response(frame)

    assert result.is_failure
    assert result.error_code == 0x03


def test_require_matching_response_raises_codec_error() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"\x40\x01")

    with pytest.raises(UnexpectedResponseError, match="does not match"):
        ExampleCodec().require_matching_response(frame)


def test_request_data_must_be_bytes() -> None:
    with pytest.raises(TypeError, match="must return bytes"):
        InvalidDataCodec().build_request()


@pytest.mark.parametrize(
    ("keyword", "value"),
    [("command", -1), ("command", 256), ("subcommand", -1), ("subcommand", 256)],
)
def test_command_fields_must_fit_in_one_byte(keyword: str, value: int) -> None:
    arguments = {"command": 0x20, "subcommand": 0x01}
    arguments[keyword] = value

    with pytest.raises(ValueError, match="fit in one byte"):
        CommandCodec.__init__(ExampleCodec(), **arguments)


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        CommandCodec.__init__(ExampleCodec(), command=0x20, timeout_seconds=0)
