"""Sensor-reading decoding that also accepts 28-bit sensor IDs.

Many 433 MHz entries (Abarth 595, 695, …) report a 28-bit ID (0x1C) in both the
programming reply and the Trigger/Receive RF reading. The strict SDK parser
raises on anything other than 0x20/0x30, so those real readings were dropped and
the row looked like "board did not acknowledge".
"""

from __future__ import annotations

from hamaton.commands.receive_rf import ReceiveRfCodec
from hamaton.commands.trigger import TriggerCodec
from hamaton.exceptions import CodecError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult, SensorReading
from hamaton.sensor_reading import _parse_battery

# Reported ID bit length -> ID byte count.
ID_BYTE_LENGTHS = {0x1C: 4, 0x20: 4, 0x30: 6}


def parse_sensor_reading(data: bytes) -> SensorReading:
    """Decode a Trigger / Receive RF sensor reading, allowing a 28-bit ID."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if len(data) < 3:
        raise CodecError("sensor reading is too short to contain its header")

    frequency = data[0]
    tire_position = data[1]
    id_bit_length = data[2]
    if frequency not in SensorReading.supported_frequencies():
        raise CodecError(f"unsupported frequency value 0x{frequency:02X}")
    id_byte_length = ID_BYTE_LENGTHS.get(id_bit_length)
    if id_byte_length is None:
        raise CodecError(
            f"sensor ID bit length must be 0x1C, 0x20, or 0x30; "
            f"received 0x{id_bit_length:02X}"
        )

    expected_length = 3 + id_byte_length + 2 + 2 + 1 + 1
    if len(data) != expected_length:
        raise CodecError(
            f"{id_bit_length}-bit sensor reading must contain exactly "
            f"{expected_length} bytes; received {len(data)}"
        )

    offset = 3 + id_byte_length
    sensor_id = data[3:offset]
    raw_pressure = int.from_bytes(data[offset : offset + 2], "big")
    raw_temperature = int.from_bytes(data[offset + 2 : offset + 4], "big")
    raw_battery = data[offset + 4]
    rssi = data[offset + 5]

    battery_percentage, battery_ok = _parse_battery(raw_battery)
    reading = SensorReading(
        frequency=frequency,
        tire_position=tire_position,
        sensor_id=sensor_id,
        pressure_kpa=None if raw_pressure == 0xFFFF else raw_pressure / 100.0,
        temperature_c=None if raw_temperature == 0xFFFF else raw_temperature - 50,
        battery_percentage=battery_percentage,
        battery_ok=battery_ok,
        rssi=rssi,
    )
    reading.reported_id_bits = id_bit_length
    return reading


class SensorTriggerCodec(TriggerCodec):
    """Trigger, tolerating a 28-bit sensor ID in the reading."""

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return self._parse_negative_response(frame.payload)
        return CommandResult.success(parse_sensor_reading(frame.payload[2:]))


class SensorReceiveRfCodec(ReceiveRfCodec):
    """Receive RF, tolerating a 28-bit sensor ID in the reading."""

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return self._parse_negative_response(frame.payload)
        if frame.payload[1] == self.DATA_SUBCOMMAND:
            if not self.enabled:
                raise CodecError("received RF data while disabling the receiver")
            return CommandResult.success(parse_sensor_reading(frame.payload[2:]))
        return self._parse_control_acknowledgement(frame.payload)
