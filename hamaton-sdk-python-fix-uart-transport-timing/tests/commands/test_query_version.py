"""Tests for specification Chapter 4.0 Query Version."""

import pytest

from hamaton.commands.query_version import QueryVersionCodec
from hamaton.exceptions import CodecError, UnexpectedResponseError
from hamaton.frame import HamatonFrame
from hamaton.models import VersionInfo


RECORDED_RESPONSE = bytes.fromhex(
    "3C 22 00 16 40 01 "
    "00 00 00 03 "
    "00 00 00 03 "
    "00 00 00 20 "
    "00 00 00 20 "
    "00 00 00 45 "
    "3E"
)


def test_builds_specification_query_version_request() -> None:
    assert QueryVersionCodec().build_request() == bytes.fromhex(
        "3C 11 00 02 40 01 3E"
    )


def test_parses_recorded_query_version_response() -> None:
    frame = HamatonFrame.from_bytes(RECORDED_RESPONSE)

    result = QueryVersionCodec().parse_response(frame)

    assert result.is_success
    assert result.value == VersionInfo(
        hardware_version=3,
        boot_version=3,
        software_version=32,
        trigger_database_version=32,
        programming_database_version=69,
    )


def test_parses_each_version_as_unsigned_big_endian() -> None:
    payload = bytes.fromhex(
        "40 01 01020304 11223344 8090A0B0 C0D0E0F0 FFFFFFFF"
    )

    result = QueryVersionCodec().parse_response(
        HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)
    )

    assert result.value.as_dict() == {
        "hardware_version": 0x01020304,
        "boot_version": 0x11223344,
        "software_version": 0x8090A0B0,
        "trigger_database_version": 0xC0D0E0F0,
        "programming_database_version": 0xFFFFFFFF,
    }


def test_negative_response_becomes_failure_result() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"\xC0\x01\x07")

    result = QueryVersionCodec().parse_response(frame)

    assert result.is_failure
    assert result.error_code == 0x07
    assert result.message == "Query Version rejected"


@pytest.mark.parametrize("payload", [b"\x40\x01", b"\x40\x01" + bytes(21)])
def test_positive_response_requires_exact_payload_length(payload: bytes) -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)

    with pytest.raises(CodecError, match="exactly 22 bytes"):
        QueryVersionCodec().parse_response(frame)


def test_negative_response_requires_error_code() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"\xC0\x01")

    with pytest.raises(CodecError, match="no error code"):
        QueryVersionCodec().parse_response(frame)


def test_wrong_command_is_rejected() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"\x44\x01")

    with pytest.raises(UnexpectedResponseError):
        QueryVersionCodec().parse_response(frame)
