"""Chapter 2.2 Query Sensor codec."""

from __future__ import annotations

from dataclasses import dataclass

from hamaton.codec import CommandCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult


@dataclass
class QuerySensorReading:
    sensor_id: bytes
    pressure_raw: int
    temperature_raw: int
    voltage_raw: int
    acceleration_raw: int
    appcode: bytes
    status: int
    test_info: bytes

    @property
    def temperature_c(self) -> int | None:
        if self.temperature_raw == 0xFFFF:
            return None
        return self.temperature_raw - 50

    @property
    def pressure_read(self) -> bool:
        return self.pressure_raw != 0xFFFF

    @property
    def temperature_read(self) -> bool:
        return self.temperature_raw != 0xFFFF

    @property
    def battery_voltage_v(self) -> float | None:
        """Decode Query Sensor voltage_raw into volts.

        Hamaton frames usually send millivolts (1500–4500). Some firmwares
        use 10 mV / centivolt units (150–450 → 1.50–4.50 V). Treat 0 / 0xFFFF
        as not present — never invent 0.000 V.
        """
        if self.voltage_raw in (0, 0xFFFF):
            return None
        raw = int(self.voltage_raw)
        if 1500 <= raw <= 4500:
            return round(raw / 1000.0, 3)
        if 150 <= raw <= 450:
            return round(raw / 100.0, 3)
        # Tenths of a volt (e.g. 29 → 2.9 V) — rare but seen on some OE sensors.
        if 15 <= raw <= 45:
            return round(raw / 10.0, 3)
        return None

    @property
    def battery_status_read(self) -> bool:
        return self.voltage_raw not in (0, 0xFFFF) or self.status != 0


class QuerySensorCodec(CommandCodec):
    COMMAND = 0x22
    SUBCOMMAND = 0x01
    TIMEOUT_SECONDS = 12.0
    RESPONSE_PAYLOAD_LENGTH = 22

    def __init__(self) -> None:
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)

    def build_request_data(self) -> bytes:
        return b""

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        payload = frame.payload
        if self.is_negative_response(frame):
            error_code = payload[2] if len(payload) > 2 else 0x01
            return CommandResult.failure(error_code, "query sensor failed")
        if len(payload) != self.RESPONSE_PAYLOAD_LENGTH:
            raise CodecError(
                "Query sensor payload must contain 22 bytes; "
                f"received {len(payload)}"
            )
        reading = QuerySensorReading(
            sensor_id=payload[2:6],
            pressure_raw=int.from_bytes(payload[6:8], "big"),
            temperature_raw=int.from_bytes(payload[8:10], "big"),
            voltage_raw=int.from_bytes(payload[10:12], "big"),
            acceleration_raw=int.from_bytes(payload[12:14], "big"),
            appcode=payload[14:17],
            status=payload[17],
            test_info=payload[18:22],
        )
        return CommandResult.success(reading)
