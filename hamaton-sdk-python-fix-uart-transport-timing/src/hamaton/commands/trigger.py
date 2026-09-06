"""Chapter 2.0 Trigger command codec."""

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult
from ..sensor_reading import parse_sensor_reading


class TriggerCodec(CommandCodec):
    """Build and parse specification Chapter 2.0 Trigger transactions.

    The request contains trigger time followed by CODEA, CODEB, and CODEC.
    Successful sensor fields are decoded by the same shared parser used by
    Receive RF. A pending response restarts the 12-second client timeout.
    """

    COMMAND = 0x20
    SUBCOMMAND = 0x01
    TIMEOUT_SECONDS = 12.0
    DEFAULT_TRIGGER_TIME = 0x5A

    ERROR_MESSAGES = {
        0x01: "trigger excitation failed",
        0x02: "trigger library not supported",
        0x03: "CODEA/CODEB/CODEC parsing error",
    }
    NEGATIVE_PAYLOAD_LENGTH = 5
    NEGATIVE_FREQUENCIES = (0x03, 0x04, 0x05)

    def __init__(
        self,
        code_a: int,
        code_b: int,
        code_c: int,
        trigger_time: int = DEFAULT_TRIGGER_TIME,
    ) -> None:
        self._validate_uint32(code_a, "code_a")
        self._validate_uint32(code_b, "code_b")
        self._validate_uint32(code_c, "code_c")
        self._validate_byte(trigger_time, "trigger_time")
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)
        self.code_a = code_a
        self.code_b = code_b
        self.code_c = code_c
        self.trigger_time = trigger_time

    def build_request_data(self) -> bytes:
        codes = b"".join(
            value.to_bytes(4, "big")
            for value in (self.code_a, self.code_b, self.code_c)
        )
        return bytes([self.trigger_time]) + codes

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Parse a Chapter 2.0 sensor reading, pending, or failure response."""
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return self._parse_negative_response(frame.payload)

        reading = parse_sensor_reading(frame.payload[2:])
        return CommandResult.success(reading)

    def _parse_negative_response(self, payload: bytes) -> CommandResult:
        if len(payload) != self.NEGATIVE_PAYLOAD_LENGTH:
            raise CodecError(
                "Trigger negative response payload must contain exactly five bytes"
            )
        if payload[2] not in self.NEGATIVE_FREQUENCIES:
            raise CodecError(
                "Trigger negative response frequency must be 0x03, 0x04, or 0x05"
            )

        error_code = payload[4]
        if error_code == 0x00:
            return CommandResult.pending(message="trigger already in progress")

        message = self.ERROR_MESSAGES.get(error_code, "unknown trigger error")
        return CommandResult.failure(error_code, message)

    @staticmethod
    def _validate_uint32(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in four bytes")
