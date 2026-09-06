"""Chapter 2.8 Receive RF command codec."""

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult
from ..sensor_reading import parse_sensor_reading


class ReceiveRfCodec(CommandCodec):
    """Build and parse specification Chapter 2.8 Receive RF transactions.

    Enabling first produces a control acknowledgement with subcommand 0x01,
    followed by sensor data with subcommand 0x02. The acknowledgement is a
    pending result so the client continues waiting with a reset timeout.
    Disabling completes when its control acknowledgement is received.
    """

    COMMAND = 0x28
    SUBCOMMAND = 0x01
    DATA_SUBCOMMAND = 0x02
    TIMEOUT_SECONDS = 12.0
    NOT_SUPPORTED = 0x01

    def __init__(
        self,
        enabled: bool,
        code_a: int = 0,
        code_b: int = 0,
        code_c: int = 0,
    ) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self._validate_uint32(code_a, "code_a")
        self._validate_uint32(code_b, "code_b")
        self._validate_uint32(code_c, "code_c")
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)
        self.enabled = enabled
        self.code_a = code_a
        self.code_b = code_b
        self.code_c = code_c

    def build_request_data(self) -> bytes:
        codes = b"".join(
            value.to_bytes(4, "big")
            for value in (self.code_a, self.code_b, self.code_c)
        )
        return bytes([int(self.enabled)]) + codes

    def accepts_response(self, frame: HamatonFrame) -> bool:
        """Accept both the control response and asynchronous RF data."""
        if not isinstance(frame, HamatonFrame):
            raise TypeError("frame must be a HamatonFrame")
        if frame.address != HamatonFrame.BOARD_ADDRESS or len(frame.payload) < 2:
            return False

        command = frame.payload[0]
        subcommand = frame.payload[1]
        if command == self.COMMAND:
            return subcommand in (self.SUBCOMMAND, self.DATA_SUBCOMMAND)
        return command == (self.COMMAND | self.ERROR_OFFSET) and (
            subcommand == self.SUBCOMMAND
        )

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Parse a Chapter 2.8 control, negative, or RF-data response."""
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return self._parse_negative_response(frame.payload)
        if frame.payload[1] == self.DATA_SUBCOMMAND:
            if not self.enabled:
                raise CodecError("received RF data while disabling the receiver")
            return CommandResult.success(parse_sensor_reading(frame.payload[2:]))
        return self._parse_control_acknowledgement(frame.payload)

    def _parse_control_acknowledgement(self, payload: bytes) -> CommandResult:
        if len(payload) != 15:
            raise CodecError(
                "Receive RF acknowledgement must contain exactly 15 bytes"
            )
        if payload[2:] != self.build_request_data():
            raise CodecError("Receive RF acknowledgement does not match the request")
        if self.enabled:
            return CommandResult.pending(message="receiver enabled; waiting for RF data")
        return CommandResult.success(message="receiver disabled")

    def _parse_negative_response(self, payload: bytes) -> CommandResult:
        if len(payload) != 4:
            raise CodecError(
                "Receive RF negative response payload must contain exactly four bytes"
            )
        if payload[2] != int(self.enabled):
            raise CodecError("Receive RF negative response has the wrong on/off state")

        error_code = payload[3]
        message = (
            "Receive RF not supported"
            if error_code == self.NOT_SUPPORTED
            else "unknown Receive RF error"
        )
        return CommandResult.failure(error_code, message)

    @staticmethod
    def _validate_uint32(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in four bytes")
