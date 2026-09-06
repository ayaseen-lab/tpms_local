"""Tests for specification Chapter 4.4 TPMS Reset."""

import pytest

from hamaton.commands.reset import ResetCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame


def board_frame(payload: bytes) -> HamatonFrame:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)


def test_builds_reset_request() -> None:
    codec = ResetCodec()

    assert codec.build_request() == bytes.fromhex("3C 11 00 02 44 01 3E")
    assert codec.timeout_seconds == 2.0


def test_parses_reset_acknowledgement() -> None:
    result = ResetCodec().parse_response(board_frame(b"\x44\x01"))

    assert result.is_success
    assert result.message == "TPMS reset acknowledged"


def test_preserves_reset_negative_error_code() -> None:
    result = ResetCodec().parse_response(board_frame(b"\xC4\x01\x03"))

    assert result.is_failure
    assert result.error_code == 0x03
    assert result.message == "TPMS reset rejected"


@pytest.mark.parametrize("payload", [b"\x44\x01\x00", b"\xC4\x01"])
def test_rejects_malformed_reset_response(payload: bytes) -> None:
    with pytest.raises(CodecError):
        ResetCodec().parse_response(board_frame(payload))
