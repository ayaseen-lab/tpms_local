"""Chapter 2.1.1 Program one sensor command codec."""

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult, ProgramResult, SensorReading


class ProgramOneSensorCodec(CommandCodec):
    """Build and parse Chapter 2.1.1 Program one sensor transactions.

    Request data is CODEA, CODEB, CODEC, and OEID as four unsigned 32-bit,
    big-endian values. OEID may be zero when the board should create an ID.
    Chapter 2.1.2 multi-sensor programming is deliberately not supported.
    """

    COMMAND = 0x21
    SUBCOMMAND = 0x01
    TIMEOUT_SECONDS = 12.0
    RESPONSE_PAYLOAD_LENGTH = 10
    NEGATIVE_PAYLOAD_LENGTH = 5
    ID_BIT_LENGTH = 0x20

    ERROR_MESSAGES = {
        0x01: "no sensor",
        0x02: "TRI database not supported",
        0x03: "programming failed",
        0x04: "sensor type not supported",
        0x05: "BLE sensor does not use LF",
    }

    def __init__(self, code_a: int, code_b: int, code_c: int, oeid: int = 0) -> None:
        self._validate_uint32(code_a, "code_a")
        self._validate_uint32(code_b, "code_b")
        self._validate_uint32(code_c, "code_c")
        self._validate_uint32(oeid, "oeid")
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)
        self.code_a = code_a
        self.code_b = code_b
        self.code_c = code_c
        self.oeid = oeid

    def build_request_data(self) -> bytes:
        return b"".join(
            value.to_bytes(4, "big")
            for value in (self.code_a, self.code_b, self.code_c, self.oeid)
        )

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Parse a Chapter 2.1.1 pending, successful, or negative response."""
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return self._parse_negative_response(frame.payload)
        return self._parse_positive_response(frame.payload)

    def _parse_positive_response(self, payload: bytes) -> CommandResult:
        if len(payload) != self.RESPONSE_PAYLOAD_LENGTH:
            raise CodecError(
                "Program one sensor response payload must contain exactly "
                f"{self.RESPONSE_PAYLOAD_LENGTH} bytes; received {len(payload)}"
            )

        frequency = payload[2]
        self._validate_frequency(frequency)
        programming_state = payload[3]
        sensor_count = payload[4]

        if programming_state == 0x00:
            return CommandResult.pending(message="programming in progress")
        if programming_state != 0x01:
            raise CodecError(
                f"unknown Program one sensor state 0x{programming_state:02X}"
            )
        if sensor_count != 1:
            raise CodecError(
                "Chapter 2.1.1 response must contain exactly one sensor; "
                f"received {sensor_count}"
            )
        if payload[5] != self.ID_BIT_LENGTH:
            raise CodecError(
                "Program one sensor response must contain a 32-bit sensor ID"
            )

        result = ProgramResult(frequency=frequency, sensor_id=payload[6:10])
        return CommandResult.success(result)

    def _parse_negative_response(self, payload: bytes) -> CommandResult:
        if len(payload) != self.NEGATIVE_PAYLOAD_LENGTH:
            raise CodecError(
                "Program one sensor negative response payload must contain exactly "
                f"{self.NEGATIVE_PAYLOAD_LENGTH} bytes; received {len(payload)}"
            )

        self._validate_frequency(payload[2])
        error_code = payload[3]
        if payload[4] != 0:
            raise CodecError(
                "Program one sensor negative response sensor count must be zero"
            )
        if error_code == 0x00:
            return CommandResult.pending(message="programming in progress")

        message = self.ERROR_MESSAGES.get(error_code, "unknown programming error")
        return CommandResult.failure(error_code, message)

    @staticmethod
    def _validate_uint32(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in four bytes")

    @staticmethod
    def _validate_frequency(frequency: int) -> None:
        if frequency not in SensorReading.supported_frequencies():
            raise CodecError(f"unsupported frequency value 0x{frequency:02X}")
