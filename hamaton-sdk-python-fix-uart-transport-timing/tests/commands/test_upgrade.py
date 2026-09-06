"""Tests for specification Chapters 4.1 through 4.3 upgrade architecture."""

import pytest

from hamaton.commands.upgrade import (
    UpgradeAcknowledgement,
    UpgradeCodec,
    UpgradeStage,
    UpgradeTarget,
)
from hamaton.exceptions import CodecError, UnexpectedResponseError
from hamaton.frame import HamatonFrame


def board_frame(payload: bytes) -> HamatonFrame:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)


@pytest.mark.parametrize(
    ("target", "timeout"),
    [
        (UpgradeTarget.SOFTWARE, 1.0),
        (UpgradeTarget.TRIGGER_DATABASE, 2.0),
        (UpgradeTarget.PROGRAMMING_DATABASE, 2.0),
    ],
)
def test_builds_metadata_step_for_every_target(
    target: UpgradeTarget, timeout: float
) -> None:
    codec = UpgradeCodec.metadata(target, 0x00100000, 0x12345678)

    frame = HamatonFrame.from_bytes(codec.build_request())

    assert frame.payload == bytes([target, 0x01]) + bytes.fromhex(
        "00 10 00 00 12 34 56 78"
    )
    assert codec.stage is UpgradeStage.METADATA
    assert codec.timeout_seconds == timeout


def test_metadata_acknowledgement_echoes_length_and_crc32() -> None:
    codec = UpgradeCodec.metadata(0x42, 512, 0x89ABCDEF)
    response = board_frame(bytes.fromhex("42 01 00 00 02 00 89 AB CD EF"))

    result = codec.parse_response(response)

    assert result.is_success
    assert isinstance(result.value, UpgradeAcknowledgement)
    assert result.value.file_length == 512
    assert result.value.file_crc32 == 0x89ABCDEF
    assert result.value.total_packets is None


def test_builds_packet_step_with_big_endian_counts() -> None:
    codec = UpgradeCodec.packet(0x43, total_packets=3, sequence_number=2, data=b"chunk")

    frame = HamatonFrame.from_bytes(codec.build_request())

    assert frame.payload == bytes.fromhex("43 02 00 00 00 03 00 00 00 02") + b"chunk"
    assert codec.stage is UpgradeStage.PACKET
    assert codec.timeout_seconds == 2.0
    assert codec.MAX_PACKET_ATTEMPTS == 3
    assert codec.max_attempts == 3


def test_packet_acknowledgement_echoes_counts() -> None:
    codec = UpgradeCodec.packet(0x41, 3, 2, b"chunk")
    response = board_frame(bytes.fromhex("41 02 00 00 00 03 00 00 00 02"))

    result = codec.parse_response(response)

    assert result.value.total_packets == 3
    assert result.value.sequence_number == 2
    assert result.value.file_length is None


@pytest.mark.parametrize(
    ("error_code", "message"),
    [(0x01, "sequence number incorrect"), (0x02, "checksum error"), (0x7F, "unknown upgrade error")],
)
def test_packet_negative_codes_are_decoded(error_code: int, message: str) -> None:
    codec = UpgradeCodec.packet(0x42, 3, 2, b"chunk")
    response = board_frame(
        bytes.fromhex("C2 02 00 00 00 03 00 00 00 02") + bytes([error_code])
    )

    result = codec.parse_response(response)

    assert result.is_failure
    assert result.error_code == error_code
    assert result.message == message


def test_packet_data_accepts_actual_length_up_to_512_bytes() -> None:
    assert len(UpgradeCodec.packet(0x41, 1, 1, b"x").data) == 9
    assert len(UpgradeCodec.packet(0x41, 1, 1, bytes(512)).data) == 520


@pytest.mark.parametrize("data", [b"", bytes(513)])
def test_packet_data_rejects_lengths_outside_specification(data: bytes) -> None:
    with pytest.raises(ValueError, match="between 1 and 512"):
        UpgradeCodec.packet(0x41, 1, 1, data)


@pytest.mark.parametrize(
    ("total_packets", "sequence_number"), [(0, 1), (3, 0), (3, 4)]
)
def test_packet_sequence_is_one_based_and_within_total(
    total_packets: int, sequence_number: int
) -> None:
    with pytest.raises(ValueError):
        UpgradeCodec.packet(0x41, total_packets, sequence_number, b"data")


@pytest.mark.parametrize("target", [0x00, 0x40, 0x44, 0x141])
def test_rejects_command_ids_outside_upgrade_range(target: int) -> None:
    with pytest.raises(ValueError, match="0x41, 0x42, or 0x43"):
        UpgradeCodec.metadata(target, 1, 2)


def test_acknowledgement_must_match_request_fields() -> None:
    codec = UpgradeCodec.packet(0x43, 3, 2, b"chunk")

    with pytest.raises(CodecError, match="does not match"):
        codec.parse_response(
            board_frame(bytes.fromhex("43 02 00 00 00 03 00 00 00 01"))
        )


def test_packet_negative_response_must_match_request_fields() -> None:
    codec = UpgradeCodec.packet(0x43, 3, 2, b"chunk")

    with pytest.raises(CodecError, match="does not match"):
        codec.parse_response(
            board_frame(bytes.fromhex("C3 02 00 00 00 03 00 00 00 01 01"))
        )


def test_metadata_negative_response_is_not_defined_by_specification() -> None:
    codec = UpgradeCodec.metadata(0x41, 100, 0x12345678)

    with pytest.raises(CodecError, match="no specified negative"):
        codec.parse_response(board_frame(bytes.fromhex("C1 01 01")))


def test_response_must_match_target_and_stage() -> None:
    codec = UpgradeCodec.packet(0x41, 1, 1, b"data")

    with pytest.raises(UnexpectedResponseError):
        codec.parse_response(board_frame(bytes.fromhex("42 02")))
    with pytest.raises(UnexpectedResponseError):
        codec.parse_response(board_frame(bytes.fromhex("41 01")))


def test_only_software_target_resets_automatically() -> None:
    assert UpgradeCodec.packet(0x41, 1, 1, b"data").requires_automatic_reset
    assert not UpgradeCodec.packet(0x42, 1, 1, b"data").requires_automatic_reset
    assert not UpgradeCodec.packet(0x43, 1, 1, b"data").requires_automatic_reset
