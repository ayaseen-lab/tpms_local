"""Tests for the UART frame envelope."""

import pytest

from hamaton.exceptions import FrameError, FrameLengthError, FrameTailError
from hamaton.frame import HamatonFrame


def test_frame_round_trip() -> None:
    frame = HamatonFrame(HamatonFrame.HOST_ADDRESS, b"\x40\x01")

    raw = frame.to_bytes()

    assert raw == bytes.fromhex("3C 11 00 02 40 01 3E")
    assert HamatonFrame.from_bytes(raw) == frame
    assert frame.command == 0x40
    assert frame.subcommand == 0x01


def test_empty_payload_round_trip() -> None:
    frame = HamatonFrame(HamatonFrame.BOARD_ADDRESS, b"")

    assert HamatonFrame.from_bytes(frame.to_bytes()) == frame
    assert frame.command is None
    assert frame.subcommand is None


@pytest.mark.parametrize("address", [-1, 256])
def test_address_must_fit_in_one_byte(address: int) -> None:
    with pytest.raises(ValueError):
        HamatonFrame(address, b"")


def test_invalid_header_is_rejected() -> None:
    with pytest.raises(FrameError, match="header"):
        HamatonFrame.from_bytes(bytes.fromhex("00 11 00 02 40 01 3E"))


def test_declared_length_mismatch_is_rejected() -> None:
    with pytest.raises(FrameLengthError, match="declares 3"):
        HamatonFrame.from_bytes(bytes.fromhex("3C 11 00 03 40 01 3E"))


def test_invalid_tail_is_rejected() -> None:
    with pytest.raises(FrameTailError, match="tail"):
        HamatonFrame.from_bytes(bytes.fromhex("3C 11 00 02 40 01 00"))
