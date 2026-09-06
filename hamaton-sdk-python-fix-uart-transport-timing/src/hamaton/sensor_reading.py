"""Shared TPMS sensor-reading payload decoder."""

from .exceptions import CodecError
from .models import SensorReading


def parse_sensor_reading(data: bytes) -> SensorReading:
    """Decode the sensor fields shared by Trigger and Receive RF.

    ``data`` starts with frequency, tire position, and ID bit length. It does
    not include a command or subcommand byte. Pressure uses hundredths of kPa;
    temperature uses the protocol's -50 degree offset. The all-ones value marks
    either measurement as unavailable.
    """
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if len(data) < 3:
        raise CodecError("sensor reading is too short to contain its header")

    frequency = data[0]
    tire_position = data[1]
    id_bit_length = data[2]
    if frequency not in SensorReading.supported_frequencies():
        raise CodecError(f"unsupported frequency value 0x{frequency:02X}")
    if id_bit_length == 0x20:
        id_byte_length = 4
    elif id_bit_length == 0x30:
        id_byte_length = 6
    else:
        raise CodecError(
            f"sensor ID bit length must be 0x20 or 0x30; received 0x{id_bit_length:02X}"
        )

    expected_length = 3 + id_byte_length + 2 + 2 + 1 + 1
    if len(data) != expected_length:
        raise CodecError(
            f"{id_bit_length}-bit sensor reading must contain exactly "
            f"{expected_length} bytes; received {len(data)}"
        )

    measurement_offset = 3 + id_byte_length
    sensor_id = data[3:measurement_offset]
    raw_pressure = int.from_bytes(data[measurement_offset : measurement_offset + 2], "big")
    raw_temperature = int.from_bytes(
        data[measurement_offset + 2 : measurement_offset + 4], "big"
    )
    raw_battery = data[measurement_offset + 4]
    rssi = data[measurement_offset + 5]

    pressure_kpa = None if raw_pressure == 0xFFFF else raw_pressure / 100.0
    temperature_c = None if raw_temperature == 0xFFFF else raw_temperature - 50
    battery_percentage, battery_ok = _parse_battery(raw_battery)

    return SensorReading(
        frequency=frequency,
        tire_position=tire_position,
        sensor_id=sensor_id,
        pressure_kpa=pressure_kpa,
        temperature_c=temperature_c,
        battery_percentage=battery_percentage,
        battery_ok=battery_ok,
        rssi=rssi,
    )


def _parse_battery(raw_battery: int) -> tuple[int | None, bool | None]:
    if 1 <= raw_battery <= 100:
        return raw_battery, None
    if raw_battery == 0x00:
        return None, True
    if raw_battery == 0xFE:
        return None, False
    return None, None
