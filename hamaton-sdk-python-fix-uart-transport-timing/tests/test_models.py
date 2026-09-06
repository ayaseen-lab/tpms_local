"""Tests for shared command result and sensor models."""

import pytest

from hamaton.models import (
    CommandResult,
    ProgramResult,
    ResultState,
    SensorReading,
    VersionInfo,
)


def make_reading(**overrides: object) -> SensorReading:
    values = {
        "frequency": SensorReading.FREQUENCY_433_MHZ,
        "tire_position": 0x10,
        "sensor_id": bytes.fromhex("12 34 56 78"),
        "pressure_kpa": 245.5,
        "temperature_c": 21,
        "battery_percentage": 85,
        "battery_ok": None,
        "rssi": 72,
    }
    values.update(overrides)
    return SensorReading(**values)  # type: ignore[arg-type]


def test_command_result_factories_create_each_shared_state() -> None:
    success = CommandResult.success(value="reading")
    pending = CommandResult.pending(message="triggering")
    failure = CommandResult.failure(0x03, message="parsing error")

    assert success.state is ResultState.SUCCESS
    assert success.is_success and not success.is_pending and not success.is_failure
    assert success.value == "reading"
    assert pending.state is ResultState.PENDING
    assert pending.is_pending
    assert failure.state is ResultState.FAILURE
    assert failure.is_failure
    assert failure.error_code == 0x03


def test_failure_requires_error_code() -> None:
    with pytest.raises(ValueError, match="requires an error_code"):
        CommandResult(ResultState.FAILURE)


def test_non_failure_cannot_contain_error_code() -> None:
    with pytest.raises(ValueError, match="only a failure"):
        CommandResult(ResultState.SUCCESS, error_code=1)


def test_sensor_reading_exposes_derived_protocol_values() -> None:
    reading = make_reading()

    assert reading.frequency_mhz == 433
    assert reading.id_bit_length == 32
    assert reading.sensor_id == bytes.fromhex("12 34 56 78")
    assert reading.pressure_kpa == 245.5
    assert reading.battery_percentage == 85


def test_six_byte_sensor_id_reports_48_bits() -> None:
    reading = make_reading(sensor_id=bytes.fromhex("01 02 03 04 05 06"))

    assert reading.id_bit_length == 48


@pytest.mark.parametrize("frequency", [-1, 3, 256])
def test_sensor_frequency_must_be_a_supported_protocol_value(frequency: int) -> None:
    with pytest.raises(ValueError):
        make_reading(frequency=frequency)


@pytest.mark.parametrize("sensor_id", [b"", b"123", b"12345", b"1234567"])
def test_sensor_id_must_be_four_or_six_bytes(sensor_id: bytes) -> None:
    with pytest.raises(ValueError, match="four or six"):
        make_reading(sensor_id=sensor_id)


@pytest.mark.parametrize("battery_percentage", [0, 101])
def test_battery_percentage_must_be_in_specification_range(
    battery_percentage: int,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        make_reading(battery_percentage=battery_percentage)


def test_battery_may_be_reported_as_ok_status_instead_of_percentage() -> None:
    reading = make_reading(battery_percentage=None, battery_ok=True)

    assert reading.battery_percentage is None
    assert reading.battery_ok is True


def test_battery_percentage_and_status_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="cannot both"):
        make_reading(battery_percentage=80, battery_ok=True)


def test_invalid_measurements_may_be_none() -> None:
    reading = make_reading(
        pressure_kpa=None,
        temperature_c=None,
        battery_percentage=None,
        battery_ok=None,
    )

    assert reading.pressure_kpa is None
    assert reading.temperature_c is None


def test_version_info_exposes_named_fields_and_dictionary() -> None:
    version = VersionInfo(1, 2, 3, 4, 5)

    assert version.hardware_version == 1
    assert version.boot_version == 2
    assert version.software_version == 3
    assert version.trigger_database_version == 4
    assert version.programming_database_version == 5
    assert version.as_dict() == {
        "hardware_version": 1,
        "boot_version": 2,
        "software_version": 3,
        "trigger_database_version": 4,
        "programming_database_version": 5,
    }


def test_version_info_repr_formats_four_byte_hex_values() -> None:
    assert "software_version=0x00000003" in repr(VersionInfo(1, 2, 3, 4, 5))


@pytest.mark.parametrize("value", [-1, 0x100000000])
def test_version_fields_must_fit_in_four_bytes(value: int) -> None:
    with pytest.raises(ValueError, match="fit in four bytes"):
        VersionInfo(value, 2, 3, 4, 5)


def test_program_result_exposes_single_sensor_data() -> None:
    result = ProgramResult(0x01, bytes.fromhex("12 34 56 78"))

    assert result.frequency == 0x01
    assert result.frequency_mhz == 433
    assert result.sensor_id == bytes.fromhex("12 34 56 78")


def test_program_result_requires_single_32_bit_sensor_id() -> None:
    with pytest.raises(ValueError, match="four-byte"):
        ProgramResult(0x01, bytes(6))
