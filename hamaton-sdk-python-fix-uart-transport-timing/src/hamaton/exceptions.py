"""Exceptions raised by the Hamaton SDK."""


class HamatonError(Exception):
    """Base class for all SDK errors."""


class FrameError(HamatonError):
    """A UART frame is malformed."""

    def __init__(
        self,
        message: str,
        parsed_frames: list[object] | None = None,
    ) -> None:
        super().__init__(message)
        self.parsed_frames = tuple(parsed_frames or [])


class FrameLengthError(FrameError):
    """A frame declares an invalid payload length."""


class FrameTailError(FrameError):
    """A complete frame does not end with the expected tail byte."""


class CodecError(HamatonError):
    """A command codec could not build or interpret protocol data."""


class UnexpectedResponseError(CodecError):
    """A response does not belong to the codec parsing it."""


class TransportError(HamatonError):
    """A transport cannot be opened or used."""


class TransportClosedError(TransportError):
    """A transport operation requires an open connection."""


class CommandTimeoutError(HamatonError, TimeoutError):
    """A command did not reach a terminal response before its deadline."""
