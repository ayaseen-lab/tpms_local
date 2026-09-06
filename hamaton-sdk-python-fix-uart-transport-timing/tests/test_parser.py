"""Tests for stateful UART stream framing."""

import pytest

from hamaton.exceptions import FrameLengthError, FrameTailError
from hamaton.frame import HamatonFrame
from hamaton.parser import HamatonStreamParser


def make_frame(payload: bytes) -> bytes:
    return HamatonFrame(HamatonFrame.BOARD_ADDRESS, payload).to_bytes()


def test_partial_frame_across_several_feed_calls() -> None:
    parser = HamatonStreamParser()
    raw = make_frame(b"\x40\x01")

    assert parser.feed(raw[:1]) == []
    assert parser.feed(raw[1:4]) == []
    frames = parser.feed(raw[4:])

    assert len(frames) == 1
    assert frames[0].payload == b"\x40\x01"
    assert parser.buffered_bytes == b""


def test_multiple_frames_in_one_chunk() -> None:
    parser = HamatonStreamParser()

    frames = parser.feed(make_frame(b"\x27\x01") + make_frame(b"\x44\x01"))

    assert [frame.payload for frame in frames] == [b"\x27\x01", b"\x44\x01"]


def test_garbage_before_header_is_discarded() -> None:
    parser = HamatonStreamParser()

    frames = parser.feed(b"garbage\x00\xFF" + make_frame(b"\x40\x01"))

    assert len(frames) == 1
    assert frames[0].payload == b"\x40\x01"


def test_garbage_without_header_is_not_buffered() -> None:
    parser = HamatonStreamParser()

    assert parser.feed(b"garbage") == []
    assert parser.buffered_bytes == b""


def test_declared_length_above_configured_limit_is_rejected() -> None:
    parser = HamatonStreamParser(max_payload_length=16)

    with pytest.raises(FrameLengthError, match="exceeds parser limit"):
        parser.feed(bytes.fromhex("3C 22 00 11"))


def test_invalid_tail_is_detected_when_frame_becomes_complete() -> None:
    parser = HamatonStreamParser()
    raw = make_frame(b"\x40\x01")[:-1] + b"\x00"

    assert parser.feed(raw[:-1]) == []
    with pytest.raises(FrameTailError, match="tail"):
        parser.feed(raw[-1:])


def test_incomplete_frame_remains_buffered() -> None:
    parser = HamatonStreamParser()
    raw = make_frame(b"\x28\x02\x01")

    parser.feed(raw[:-2])

    assert parser.buffered_bytes == raw[:-2]


def test_reset_discards_buffered_partial_frame() -> None:
    parser = HamatonStreamParser()
    parser.feed(make_frame(b"\x40\x01")[:3])

    parser.reset()

    assert parser.buffered_bytes == b""


def test_default_limit_accepts_payload_larger_than_4096_bytes() -> None:
    parser = HamatonStreamParser()
    payload = bytes(5000)

    frames = parser.feed(make_frame(payload))

    assert len(frames) == 1
    assert frames[0].payload == payload


def test_bad_tail_exception_preserves_frames_parsed_before_error() -> None:
    parser = HamatonStreamParser()
    valid = make_frame(b"\x40\x01")
    bad_tail = make_frame(b"\x44\x01")[:-1] + b"\x00"

    with pytest.raises(FrameTailError) as raised:
        parser.feed(valid + bad_tail)

    assert [frame.payload for frame in raised.value.parsed_frames] == [b"\x40\x01"]


def test_bad_length_exception_preserves_frames_parsed_before_error() -> None:
    parser = HamatonStreamParser(max_payload_length=16)
    valid = make_frame(b"\x40\x01")
    excessive_length_prefix = bytes.fromhex("3C 22 00 11")

    with pytest.raises(FrameLengthError) as raised:
        parser.feed(valid + excessive_length_prefix)

    assert [frame.payload for frame in raised.value.parsed_frames] == [b"\x40\x01"]
