"""Chapter 2.1.2 program-search (LF activate / find sensors)."""

from __future__ import annotations

from dataclasses import dataclass

from hamaton.codec import CommandCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult, SensorReading


@dataclass
class SearchProgress:
    frequency: int
    sensor_count: int
    timed_out: bool


class ProgramSearchCodec(CommandCodec):
    COMMAND = 0x21
    SUBCOMMAND = 0x02
    TIMEOUT_SECONDS = 12.0

    def __init__(self, code_a: int, code_b: int, code_c: int) -> None:
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)
        self.code_a = code_a
        self.code_b = code_b
        self.code_c = code_c

    def build_request_data(self) -> bytes:
        return b"".join(
            value.to_bytes(4, "big") for value in (self.code_a, self.code_b, self.code_c)
        )

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        payload = frame.payload
        if self.is_negative_response(frame):
            error_code = payload[2] if len(payload) > 2 else 0x01
            return CommandResult.failure(error_code, "program search failed")
        if len(payload) < 5:
            raise CodecError("program search response is too short")
        frequency = payload[2]
        if frequency not in SensorReading.supported_frequencies():
            raise CodecError(f"unsupported frequency 0x{frequency:02X}")
        count = payload[3]
        status = payload[4]
        progress = SearchProgress(
            frequency=frequency, sensor_count=count, timed_out=(status == 1)
        )
        if status == 0:
            return CommandResult.pending(value=progress, message="searching")
        return CommandResult.success(progress)
