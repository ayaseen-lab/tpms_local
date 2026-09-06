"""Tests for sensor reading decoding shared by Trigger and Receive RF."""

import pytest

from hamaton.exceptions import CodecError
from hamaton.sensor_reading import parse_sensor_reading


def test_parses_32_bit_sensor_reading_with_measurements() -> None:
    data = bytes.fromhex("01 10 20 12 34 56 78 5F E6 00 47 55 50")

    reading = parse_sensor_reading(data)

    assert reading.frequency == 0x01
    assert reading.frequency_mhz == 433
    assert reading.tire_position == 0x10
    assert reading.sensor_id == bytes.fromhex("12 34 56 78")
    assert reading.id_bit_length == 32
    assert reading.pressure_kpa == 245.5
    assert reading.temperature_c == 21
    assert reading.battery_percentage == 85
    assert reading.battery_ok is None
    assert reading.rssi == 0x50


def test_parses_48_bit_sensor_id() -> None:
    data = bytes.fromhex("02 00 30 01 02 03 04 05 06 27 10 00 32 64 40")

    reading = parse_sensor_reading(data)

    assert reading.frequency_mhz == 2400
    assert reading.sensor_id == bytes.fromhex("01 02 03 04 05 06")
    assert reading.id_bit_length == 48
    assert reading.pressure_kpa == 100.0
    assert reading.temperature_c == 0
    assert reading.battery_percentage == 100


def test_all_ones_measurements_are_unavailable() -> None:
    data = bytes.fromhex("00 21 20 AA BB CC DD FF FF FF FF 32 30")

    reading = parse_sensor_reading(data)

    assert reading.pressure_kpa is None
    assert reading.temperature_c is None


@pytest.mark.parametrize(
    ("raw_battery", "percentage", "battery_ok"),
    [(0x00, None, True), (0xFE, None, False), (0xFF, None, None)],
)
def test_parses_battery_status_encodings(
    raw_battery: int,
    percentage: int | None,
    battery_ok: bool | None,
) -> None:
    data = bytes.fromhex("01 10 20 12 34 56 78 00 64 00 46 00 50")
    data = data[:-2] + bytes([raw_battery, data[-1]])

    reading = parse_sensor_reading(data)

    assert reading.battery_percentage == percentage
    assert reading.battery_ok is battery_ok


@pytest.mark.parametrize("id_bits", [0x00, 0x10, 0x28, 0x40])
def test_rejects_unknown_sensor_id_bit_length(id_bits: int) -> None:
    data = bytes([0x01, 0x10, id_bits]) + bytes(10)

    with pytest.raises(CodecError, match="0x20 or 0x30"):
        parse_sensor_reading(data)


@pytest.mark.parametrize("frequency", [0x03, 0xFF])
def test_rejects_unknown_frequency(frequency: int) -> None:
    data = bytes([frequency]) + bytes.fromhex("10 20 12 34 56 78 00 64 00 46 50 40")

    with pytest.raises(CodecError, match="unsupported frequency"):
        parse_sensor_reading(data)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x01\x10",
        bytes.fromhex("01 10 20 12 34 56 78"),
        bytes.fromhex("01 10 20 12 34 56 78 00 64 00 46 50 40 00"),
    ],
)
def test_rejects_incomplete_or_trailing_sensor_data(data: bytes) -> None:
    with pytest.raises(CodecError):
        parse_sensor_reading(data)
