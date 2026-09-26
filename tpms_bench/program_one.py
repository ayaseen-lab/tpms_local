"""Chapter 2.1.1 programming that also accepts short sensor IDs.

Several 433 MHz entries (Abarth 595, 695, …) program successfully but report a
28-bit sensor ID. The strict SDK codec raises on anything other than 32 bits, so
those real successes were dropped and surfaced as "board did not acknowledge".
"""

from __future__ import annotations

from hamaton.commands.program_sensor import ProgramOneSensorCodec
from hamaton.exceptions import CodecError
from hamaton.models import CommandResult, ProgramResult

# Bit lengths the board is allowed to report for a four-byte sensor ID.
ACCEPTED_ID_BIT_LENGTHS = (0x1C, 0x20)


class ProgramSensorCodec(ProgramOneSensorCodec):
    """Program one sensor, tolerating 28-bit as well as 32-bit sensor IDs."""

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

        id_bit_length = payload[5]
        if id_bit_length not in ACCEPTED_ID_BIT_LENGTHS:
            raise CodecError(
                f"unsupported sensor ID bit length 0x{id_bit_length:02X}"
            )

        result = ProgramResult(frequency=frequency, sensor_id=payload[6:10])
        result.id_bit_length = id_bit_length
        return CommandResult.success(result)
