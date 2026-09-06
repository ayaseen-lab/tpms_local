"""Tests for the Milestone 1 exception hierarchy."""

from hamaton.exceptions import (
    CodecError,
    CommandTimeoutError,
    FrameError,
    FrameLengthError,
    FrameTailError,
    HamatonError,
    TransportClosedError,
    TransportError,
    UnexpectedResponseError,
)


def test_specific_frame_errors_are_frame_errors() -> None:
    assert issubclass(FrameLengthError, FrameError)
    assert issubclass(FrameTailError, FrameError)


def test_frame_and_codec_errors_are_sdk_errors() -> None:
    assert issubclass(FrameError, HamatonError)
    assert issubclass(CodecError, HamatonError)
    assert issubclass(UnexpectedResponseError, CodecError)


def test_closed_transport_error_is_a_transport_and_sdk_error() -> None:
    assert issubclass(TransportError, HamatonError)
    assert issubclass(TransportClosedError, TransportError)


def test_command_timeout_is_an_sdk_and_standard_timeout_error() -> None:
    assert issubclass(CommandTimeoutError, HamatonError)
    assert issubclass(CommandTimeoutError, TimeoutError)


def test_frame_error_preserves_completed_frames() -> None:
    completed_frame = object()

    error = FrameError("bad frame", parsed_frames=[completed_frame])

    assert error.parsed_frames == (completed_frame,)
