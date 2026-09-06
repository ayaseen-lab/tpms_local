"""Tests for specification Chapter 2.0 Trigger."""

import pytest

from hamaton.client import HamatonClient
from hamaton.commands.trigger import TriggerCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame
from hamaton.models import SensorReading
from hamaton.transports.mock import MockTransport


def board_frame(payload: bytes) -> HamatonFrame:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)


def test_builds_trigger_request_with_default_trigger_time() -> None:
    codec = TriggerCodec(0x11223344, 0x55667788, 0x99AABBCC)

    assert codec.build_request() == bytes.fromhex(
        "3C 11 00 0F 20 01 5A "
        "11 22 33 44 55 66 77 88 99 AA BB CC 3E"
    )


def test_builds_trigger_request_with_custom_trigger_time() -> None:
    codec = TriggerCodec(1, 2, 3, trigger_time=0x20)

    assert codec.build_request_data()[0] == 0x20


def test_parses_successful_trigger_sensor_reading() -> None:
    payload = bytes.fromhex(
        "20 01 01 10 20 12 34 56 78 5F E6 00 47 55 50"
    )

    result = TriggerCodec(1, 2, 3).parse_response(board_frame(payload))

    assert result.is_success
    assert isinstance(result.value, SensorReading)
    assert result.value.sensor_id == bytes.fromhex("12 34 56 78")
    assert result.value.pressure_kpa == 245.5
    assert result.value.temperature_c == 21


def test_parses_trigger_response_with_48_bit_sensor_id() -> None:
    payload = bytes.fromhex(
        "20 01 02 00 30 01 02 03 04 05 06 27 10 00 32 64 40"
    )

    result = TriggerCodec(1, 2, 3).parse_response(board_frame(payload))

    assert result.value.id_bit_length == 48
    assert result.value.sensor_id == bytes.fromhex("01 02 03 04 05 06")


def test_pending_trigger_response_resets_client_timeout() -> None:
    pending = board_frame(bytes.fromhex("A0 01 04 10 00"))
    success = board_frame(
        bytes.fromhex("20 01 01 10 20 12 34 56 78 5F E6 00 47 55 50")
    )
    transport = MockTransport(
        [pending.to_bytes(), success.to_bytes()], open_immediately=True
    )

    result = HamatonClient(transport).execute(TriggerCodec(1, 2, 3))

    assert result.is_success
    assert len(transport.read_requests) == 2


@pytest.mark.parametrize(
    ("error_code", "message"),
    [
        (0x01, "trigger excitation failed"),
        (0x02, "trigger library not supported"),
        (0x03, "CODEA/CODEB/CODEC parsing error"),
        (0x7F, "unknown trigger error"),
    ],
)
def test_negative_trigger_codes_become_failure_results(
    error_code: int, message: str
) -> None:
    result = TriggerCodec(1, 2, 3).parse_response(
        board_frame(bytes([0xA0, 0x01, 0x04, 0x10, error_code]))
    )

    assert result.is_failure
    assert result.error_code == error_code
    assert result.message == message


def test_negative_response_uses_fifth_byte_as_status() -> None:
    result = TriggerCodec(1, 2, 3).parse_response(
        board_frame(bytes.fromhex("A0 01 04 10 03"))
    )

    assert result.is_failure
    assert result.error_code == 0x03


@pytest.mark.parametrize("payload", [b"\xA0\x01", bytes.fromhex("A0 01 04 10 00 00")])
def test_negative_response_requires_exact_shape(payload: bytes) -> None:
    with pytest.raises(CodecError, match="exactly five bytes"):
        TriggerCodec(1, 2, 3).parse_response(board_frame(payload))


@pytest.mark.parametrize("frequency", [0x00, 0x01, 0x02, 0x06])
def test_negative_response_uses_specification_frequency_codes(frequency: int) -> None:
    with pytest.raises(CodecError, match="0x03, 0x04, or 0x05"):
        TriggerCodec(1, 2, 3).parse_response(
            board_frame(bytes([0xA0, 0x01, frequency, 0x10, 0x01]))
        )


@pytest.mark.parametrize("field", ["code_a", "code_b", "code_c"])
@pytest.mark.parametrize("value", [-1, 0x100000000])
def test_codes_must_fit_in_four_bytes(field: str, value: int) -> None:
    arguments = {"code_a": 1, "code_b": 2, "code_c": 3}
    arguments[field] = value

    with pytest.raises(ValueError, match="fit in four bytes"):
        TriggerCodec(**arguments)


@pytest.mark.parametrize("trigger_time", [-1, 256])
def test_trigger_time_must_fit_in_one_byte(trigger_time: int) -> None:
    with pytest.raises(ValueError, match="fit in one byte"):
        TriggerCodec(1, 2, 3, trigger_time=trigger_time)
