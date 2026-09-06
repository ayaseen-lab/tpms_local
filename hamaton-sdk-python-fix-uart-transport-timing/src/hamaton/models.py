"""Shared protocol result models."""

from enum import Enum
from typing import Any


class ResultState(Enum):
    """State of a decoded command response."""

    SUCCESS = "success"
    PENDING = "pending"
    FAILURE = "failure"


class CommandResult:
    """Common response state returned by command codecs."""

    def __init__(
        self,
        state: ResultState,
        value: Any = None,
        error_code: int | None = None,
        message: str = "",
    ) -> None:
        if not isinstance(state, ResultState):
            raise TypeError("state must be a ResultState")
        if error_code is not None:
            self._validate_byte(error_code, "error_code")
        if state is ResultState.FAILURE and error_code is None:
            raise ValueError("a failure result requires an error_code")
        if state is not ResultState.FAILURE and error_code is not None:
            raise ValueError("only a failure result may have an error_code")

        self.state = state
        self.value = value
        self.error_code = error_code
        self.message = message

    @property
    def is_success(self) -> bool:
        return self.state is ResultState.SUCCESS

    @property
    def is_pending(self) -> bool:
        return self.state is ResultState.PENDING

    @property
    def is_failure(self) -> bool:
        return self.state is ResultState.FAILURE

    @classmethod
    def success(cls, value: Any = None, message: str = "") -> "CommandResult":
        return cls(ResultState.SUCCESS, value=value, message=message)

    @classmethod
    def pending(cls, value: Any = None, message: str = "") -> "CommandResult":
        return cls(ResultState.PENDING, value=value, message=message)

    @classmethod
    def failure(cls, error_code: int, message: str = "") -> "CommandResult":
        return cls(ResultState.FAILURE, error_code=error_code, message=message)

    @staticmethod
    def _validate_byte(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in one byte")


class SensorReading:
    """Decoded sensor data shared by Trigger and Receive RF.

    Frequency uses the protocol value: 0 for 315 MHz, 1 for 433 MHz, and 2
    for 2.4 GHz. A sensor ID is either four bytes (32 bits) or six bytes
    (48 bits). ``None`` represents an invalid or unavailable measured value.
    """

    FREQUENCY_315_MHZ = 0x00
    FREQUENCY_433_MHZ = 0x01
    FREQUENCY_2400_MHZ = 0x02

    def __init__(
        self,
        frequency: int,
        tire_position: int,
        sensor_id: bytes,
        pressure_kpa: float | None,
        temperature_c: int | None,
        battery_percentage: int | None,
        battery_ok: bool | None,
        rssi: int,
    ) -> None:
        self._validate_byte(frequency, "frequency")
        self._validate_byte(tire_position, "tire_position")
        self._validate_byte(rssi, "rssi")
        if frequency not in self.supported_frequencies():
            raise ValueError("frequency must be 0x00, 0x01, or 0x02")
        if not isinstance(sensor_id, bytes):
            raise TypeError("sensor_id must be bytes")
        if len(sensor_id) not in (4, 6):
            raise ValueError("sensor_id must contain four or six bytes")
        if pressure_kpa is not None and pressure_kpa < 0:
            raise ValueError("pressure_kpa cannot be negative")
        if temperature_c is not None and not isinstance(temperature_c, int):
            raise TypeError("temperature_c must be an integer or None")
        if battery_percentage is not None:
            if not isinstance(battery_percentage, int):
                raise TypeError("battery_percentage must be an integer or None")
            if not 1 <= battery_percentage <= 100:
                raise ValueError("battery_percentage must be between 1 and 100")
        if battery_ok is not None and not isinstance(battery_ok, bool):
            raise TypeError("battery_ok must be a boolean or None")
        if battery_percentage is not None and battery_ok is not None:
            raise ValueError(
                "battery_percentage and battery_ok cannot both contain a value"
            )

        self.frequency = frequency
        self.tire_position = tire_position
        self.sensor_id = sensor_id
        self.pressure_kpa = pressure_kpa
        self.temperature_c = temperature_c
        self.battery_percentage = battery_percentage
        self.battery_ok = battery_ok
        self.rssi = rssi

    @property
    def id_bit_length(self) -> int:
        return len(self.sensor_id) * 8

    @property
    def frequency_mhz(self) -> int:
        frequency_names = {
            self.FREQUENCY_315_MHZ: 315,
            self.FREQUENCY_433_MHZ: 433,
            self.FREQUENCY_2400_MHZ: 2400,
        }
        return frequency_names[self.frequency]

    @staticmethod
    def supported_frequencies() -> tuple[int, int, int]:
        return (
            SensorReading.FREQUENCY_315_MHZ,
            SensorReading.FREQUENCY_433_MHZ,
            SensorReading.FREQUENCY_2400_MHZ,
        )

    @staticmethod
    def _validate_byte(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in one byte")


class VersionInfo:
    """Version values returned by the Chapter 4.0 Query Version command."""

    def __init__(
        self,
        hardware_version: int,
        boot_version: int,
        software_version: int,
        trigger_database_version: int,
        programming_database_version: int,
    ) -> None:
        values = {
            "hardware_version": hardware_version,
            "boot_version": boot_version,
            "software_version": software_version,
            "trigger_database_version": trigger_database_version,
            "programming_database_version": programming_database_version,
        }
        for name, value in values.items():
            if not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{name} must fit in four bytes")

        self.hardware_version = hardware_version
        self.boot_version = boot_version
        self.software_version = software_version
        self.trigger_database_version = trigger_database_version
        self.programming_database_version = programming_database_version

    def as_dict(self) -> dict[str, int]:
        """Return all version fields using their public names."""
        return {
            "hardware_version": self.hardware_version,
            "boot_version": self.boot_version,
            "software_version": self.software_version,
            "trigger_database_version": self.trigger_database_version,
            "programming_database_version": self.programming_database_version,
        }

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VersionInfo) and self.as_dict() == other.as_dict()

    def __repr__(self) -> str:
        fields = ", ".join(
            f"{name}=0x{value:08X}" for name, value in self.as_dict().items()
        )
        return f"VersionInfo({fields})"


class ProgramResult:
    """Successful Chapter 2.1.1 single-sensor programming result."""

    def __init__(self, frequency: int, sensor_id: bytes) -> None:
        if frequency not in SensorReading.supported_frequencies():
            raise ValueError("frequency must be 0x00, 0x01, or 0x02")
        if not isinstance(sensor_id, bytes):
            raise TypeError("sensor_id must be bytes")
        if len(sensor_id) != 4:
            raise ValueError("Program one sensor requires a four-byte sensor_id")

        self.frequency = frequency
        self.sensor_id = sensor_id

    @property
    def frequency_mhz(self) -> int:
        frequency_names = {
            SensorReading.FREQUENCY_315_MHZ: 315,
            SensorReading.FREQUENCY_433_MHZ: 433,
            SensorReading.FREQUENCY_2400_MHZ: 2400,
        }
        return frequency_names[self.frequency]

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ProgramResult)
            and self.frequency == other.frequency
            and self.sensor_id == other.sensor_id
        )

    def __repr__(self) -> str:
        return (
            "ProgramResult("
            f"frequency={self.frequency}, sensor_id={self.sensor_id.hex().upper()}"
            ")"
        )
