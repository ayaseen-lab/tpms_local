"""Tests for specification Chapter 2.8 Receive RF."""

import pytest

from hamaton.client import HamatonClient
from hamaton.commands.receive_rf import ReceiveRfCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame
from hamaton.models import SensorReading
from hamaton.transports.mock import MockTransport


def board_frame(payload: bytes) -> HamatonFrame:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)


def sensor_payload(subcommand: int = 0x02) -> bytes:
    return bytes([0x28, subcommand]) + bytes.fromhex(
        "01 10 20 12 34 56 78 5F E6 00 47 55 50"
    )


def acknowledgement(codec: ReceiveRfCodec) -> HamatonFrame:
    return board_frame(bytes([0x28, 0x01]) + codec.build_request_data())


def test_builds_enable_request_with_abc_codes() -> None:
    codec = ReceiveRfCodec(
        True,
        code_a=0x11223344,
        code_b=0x55667788,
        code_c=0x99AABBCC,
    )

    assert codec.build_request() == bytes.fromhex(
        "3C 11 00 0F 28 01 01 "
        "11 22 33 44 55 66 77 88 99 AA BB CC 3E"
    )


def test_builds_disable_request_with_zero_default_codes() -> None:
    codec = ReceiveRfCodec(False)

    assert codec.build_request_data() == bytes(13)


def test_enable_acknowledgement_is_pending() -> None:
    codec = ReceiveRfCodec(True, 1, 2, 3)

    result = codec.parse_response(acknowledgement(codec))

    assert result.is_pending
    assert "waiting for RF data" in result.message


def test_disable_acknowledgement_completes_transaction() -> None:
    codec = ReceiveRfCodec(False, 1, 2, 3)

    result = codec.parse_response(acknowledgement(codec))

    assert result.is_success
    assert result.message == "receiver disabled"


def test_parses_rf_data_with_shared_sensor_decoder() -> None:
    result = ReceiveRfCodec(True).parse_response(board_frame(sensor_payload()))

    assert result.is_success
    assert isinstance(result.value, SensorReading)
    assert result.value.sensor_id == bytes.fromhex("12 34 56 78")
    assert result.value.pressure_kpa == 245.5


def test_client_waits_for_rf_data_after_enable_acknowledgement() -> None:
    codec = ReceiveRfCodec(True, 1, 2, 3)
    control_acknowledgement = acknowledgement(codec)
    reading = board_frame(sensor_payload())
    transport = MockTransport(
        [control_acknowledgement.to_bytes(), reading.to_bytes()],
        open_immediately=True,
    )

    result = HamatonClient(transport).execute(codec)

    assert result.is_success
    assert result.value.frequency_mhz == 433
    assert len(transport.read_requests) == 2


def test_rf_data_can_arrive_without_separate_acknowledgement() -> None:
    transport = MockTransport(
        [board_frame(sensor_payload()).to_bytes()], open_immediately=True
    )

    result = HamatonClient(transport).execute(ReceiveRfCodec(True))

    assert result.is_success


def test_negative_not_supported_response_becomes_failure() -> None:
    result = ReceiveRfCodec(True).parse_response(
        board_frame(bytes.fromhex("A8 01 01 01"))
    )

    assert result.is_failure
    assert result.error_code == 0x01
    assert result.message == "Receive RF not supported"


def test_unknown_negative_code_is_preserved() -> None:
    result = ReceiveRfCodec(False).parse_response(
        board_frame(bytes.fromhex("A8 01 00 7F"))
    )

    assert result.is_failure
    assert result.error_code == 0x7F
    assert result.message == "unknown Receive RF error"


def test_wrong_acknowledgement_state_is_rejected() -> None:
    codec = ReceiveRfCodec(True, 1, 2, 3)
    wrong_data = bytes([0x00]) + codec.build_request_data()[1:]

    with pytest.raises(CodecError, match="does not match"):
        codec.parse_response(board_frame(bytes([0x28, 0x01]) + wrong_data))


def test_rf_data_is_rejected_while_disabling() -> None:
    with pytest.raises(CodecError, match="while disabling"):
        ReceiveRfCodec(False).parse_response(board_frame(sensor_payload()))


@pytest.mark.parametrize("payload", [b"\x28\x01\x01", b"\xA8\x01\x01"])
def test_malformed_control_responses_are_rejected(payload: bytes) -> None:
    with pytest.raises(CodecError):
        ReceiveRfCodec(True).parse_response(board_frame(payload))


def test_non_boolean_enabled_is_rejected() -> None:
    with pytest.raises(TypeError, match="boolean"):
        ReceiveRfCodec(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["code_a", "code_b", "code_c"])
@pytest.mark.parametrize("value", [-1, 0x100000000])
def test_codes_must_fit_in_four_bytes(field: str, value: int) -> None:
    arguments = {"code_a": 1, "code_b": 2, "code_c": 3}
    arguments[field] = value

    with pytest.raises(ValueError, match="fit in four bytes"):
        ReceiveRfCodec(True, **arguments)
