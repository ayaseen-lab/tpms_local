"""Shared abstraction for Hamaton command codecs."""

from abc import ABC, abstractmethod

from .exceptions import UnexpectedResponseError
from .frame import HamatonFrame
from .models import CommandResult


class CommandCodec(ABC):
    """Build a command request and decode its matching response.

    Command modules provide only command-specific data and response parsing.
    UART framing remains the responsibility of :class:`HamatonFrame`, while
    send/read/timeout orchestration remains the responsibility of the client.
    """

    ERROR_OFFSET = 0x80

    def __init__(
        self,
        command: int,
        subcommand: int = 0x01,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._validate_byte(command, "command")
        self._validate_byte(subcommand, "subcommand")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        self.command = command
        self.subcommand = subcommand
        self.timeout_seconds = float(timeout_seconds)
        self.max_attempts = 1

    @abstractmethod
    def build_request_data(self) -> bytes:
        """Return bytes placed after command and subcommand in the request."""

    def build_request_frame(self) -> HamatonFrame:
        """Build the complete host frame for this command."""
        request_data = self.build_request_data()
        if not isinstance(request_data, bytes):
            raise TypeError("build_request_data() must return bytes")

        payload = bytes([self.command, self.subcommand]) + request_data
        return HamatonFrame(HamatonFrame.HOST_ADDRESS, payload)

    def build_request(self) -> bytes:
        """Build request bytes ready to be written to a transport."""
        return self.build_request_frame().to_bytes()

    def accepts_response(self, frame: HamatonFrame) -> bool:
        """Return whether a board frame belongs to this command."""
        if not isinstance(frame, HamatonFrame):
            raise TypeError("frame must be a HamatonFrame")
        if frame.address != HamatonFrame.BOARD_ADDRESS:
            return False
        if len(frame.payload) < 2:
            return False

        response_command = frame.payload[0]
        valid_commands = (self.command, self.command | self.ERROR_OFFSET)
        return (
            response_command in valid_commands
            and frame.payload[1] == self.subcommand
        )

    def require_matching_response(self, frame: HamatonFrame) -> None:
        """Raise when a frame cannot be parsed by this codec."""
        if not self.accepts_response(frame):
            raise UnexpectedResponseError(
                f"frame does not match command 0x{self.command:02X} "
                f"subcommand 0x{self.subcommand:02X}"
            )

    def is_negative_response(self, frame: HamatonFrame) -> bool:
        """Return whether an accepted frame uses the command error offset."""
        self.require_matching_response(frame)
        return frame.payload[0] == (self.command | self.ERROR_OFFSET)

    @abstractmethod
    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Decode one matching board frame into a shared or typed result."""

    @staticmethod
    def _validate_byte(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in one byte")
