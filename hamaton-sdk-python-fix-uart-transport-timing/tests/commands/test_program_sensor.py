"""Tests for specification Chapter 2.1.1 Program one sensor."""

import pytest

from hamaton.client import HamatonClient
from hamaton.commands.program_sensor import ProgramOneSensorCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame
from hamaton.models import ProgramResult
from hamaton.transports.mock import MockTransport


def board_frame(payload: bytes) -> HamatonFrame:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)


def test_builds_single_sensor_request_with_big_endian_fields() -> None:
    codec = ProgramOneSensorCodec(
        code_a=0x11223344,
        code_b=0x55667788,
        code_c=0x99AABBCC,
        oeid=0xDDEEFF00,
    )

    assert codec.build_request() == bytes.fromhex(
        "3C 11 00 12 21 01 "
        "11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF 00 3E"
    )


def test_oeid_defaults_to_zero_for_automatic_id_creation() -> None:
    codec = ProgramOneSensorCodec(1, 2, 3)

    assert codec.build_request_data()[-4:] == bytes(4)


def test_parses_successful_single_sensor_response() -> None:
    payload = bytes.fromhex("21 01 01 01 01 20 12 34 56 78")

    result = ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))

    assert result.is_success
    assert result.value == ProgramResult(
        frequency=0x01, sensor_id=bytes.fromhex("12 34 56 78")
    )
    assert result.value.frequency_mhz == 433


def test_positive_in_progress_response_is_pending() -> None:
    payload = bytes.fromhex("21 01 01 00 00 00 00 00 00 00")

    result = ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))

    assert result.is_pending
    assert result.message == "programming in progress"


def test_negative_in_progress_response_is_pending() -> None:
    payload = bytes.fromhex("A1 01 01 00 00")

    result = ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))

    assert result.is_pending


@pytest.mark.parametrize(
    ("error_code", "message"),
    [
        (0x01, "no sensor"),
        (0x02, "TRI database not supported"),
        (0x03, "programming failed"),
        (0x04, "sensor type not supported"),
        (0x05, "BLE sensor does not use LF"),
        (0x7F, "unknown programming error"),
    ],
)
def test_negative_error_codes_become_failure_results(
    error_code: int, message: str
) -> None:
    payload = bytes([0xA1, 0x01, 0x01, error_code, 0x00])

    result = ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))

    assert result.is_failure
    assert result.error_code == error_code
    assert result.message == message


def test_client_resets_timeout_after_programming_pending_response() -> None:
    pending = board_frame(bytes.fromhex("21 01 01 00 00 00 00 00 00 00"))
    success = board_frame(bytes.fromhex("21 01 01 01 01 20 12 34 56 78"))
    transport = MockTransport(
        [pending.to_bytes(), success.to_bytes()], open_immediately=True
    )

    result = HamatonClient(transport).execute(ProgramOneSensorCodec(1, 2, 3))

    assert result.is_success
    assert len(transport.read_requests) == 2


@pytest.mark.parametrize("sensor_count", [0, 2])
def test_multi_sensor_response_is_not_implemented(sensor_count: int) -> None:
    payload = bytes([0x21, 0x01, 0x01, 0x01, sensor_count, 0x20]) + bytes(4)

    with pytest.raises(CodecError, match="exactly one sensor"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))


def test_non_32_bit_sensor_id_is_rejected() -> None:
    payload = bytes.fromhex("21 01 01 01 01 30 12 34 56 78")

    with pytest.raises(CodecError, match="32-bit"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))


@pytest.mark.parametrize("state", [0x02, 0xFF])
def test_unknown_programming_state_is_rejected(state: int) -> None:
    payload = bytes([0x21, 0x01, 0x01, state, 0x00, 0, 0, 0, 0, 0])

    with pytest.raises(CodecError, match="unknown.*state"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))


@pytest.mark.parametrize("frequency", [0x03, 0xFF])
def test_unknown_frequency_is_rejected(frequency: int) -> None:
    payload = bytes([0x21, 0x01, frequency, 0x00, 0, 0, 0, 0, 0, 0])

    with pytest.raises(CodecError, match="unsupported frequency"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))


@pytest.mark.parametrize("payload", [b"\x21\x01", b"\x21\x01" + bytes(9)])
def test_positive_response_requires_exact_length(payload: bytes) -> None:
    with pytest.raises(CodecError, match="exactly 10 bytes"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))


@pytest.mark.parametrize("payload", [b"\xA1\x01", b"\xA1\x01" + bytes(4)])
def test_negative_response_requires_exact_length(payload: bytes) -> None:
    with pytest.raises(CodecError, match="exactly 5 bytes"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(board_frame(payload))


def test_negative_response_requires_zero_sensor_count() -> None:
    with pytest.raises(CodecError, match="sensor count must be zero"):
        ProgramOneSensorCodec(1, 2, 3).parse_response(
            board_frame(bytes.fromhex("A1 01 01 03 01"))
        )


@pytest.mark.parametrize("field", ["code_a", "code_b", "code_c", "oeid"])
@pytest.mark.parametrize("value", [-1, 0x100000000])
def test_request_fields_must_fit_in_four_bytes(field: str, value: int) -> None:
    arguments = {"code_a": 1, "code_b": 2, "code_c": 3, "oeid": 4}
    arguments[field] = value

    with pytest.raises(ValueError, match="fit in four bytes"):
        ProgramOneSensorCodec(**arguments)
