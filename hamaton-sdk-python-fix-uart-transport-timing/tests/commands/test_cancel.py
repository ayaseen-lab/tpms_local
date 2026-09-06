"""Tests for specification Chapter 2.7 Cancel action."""

import pytest

from hamaton.commands.cancel import CancelCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame


def board_frame(payload: bytes) -> HamatonFrame:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload)


def test_builds_cancel_request() -> None:
    codec = CancelCodec()

    assert codec.build_request() == bytes.fromhex("3C 11 00 02 27 01 3E")
    assert codec.timeout_seconds == 1.0


def test_parses_cancel_acknowledgement() -> None:
    result = CancelCodec().parse_response(board_frame(b"\x27\x01"))

    assert result.is_success
    assert result.message == "action cancelled"


def test_preserves_cancel_negative_error_code() -> None:
    result = CancelCodec().parse_response(board_frame(b"\xA7\x01\x04"))

    assert result.is_failure
    assert result.error_code == 0x04
    assert result.message == "Cancel action rejected"


@pytest.mark.parametrize("payload", [b"\x27\x01\x00", b"\xA7\x01"])
def test_rejects_malformed_cancel_response(payload: bytes) -> None:
    with pytest.raises(CodecError):
        CancelCodec().parse_response(board_frame(payload))
