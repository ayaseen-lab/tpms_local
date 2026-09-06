"""Tests for specification Chapter 5 checksum helpers."""

import pytest

from hamaton.checksums import crc8, crc16, crc32


def test_crc8_standard_check_value() -> None:
    assert crc8(b"123456789", 0x00, 0x07) == 0xF4


def test_crc16_ccitt_false_standard_check_value() -> None:
    assert crc16(b"123456789", 0xFFFF, 0x1021) == 0x29B1


def test_crc32_non_reflected_standard_check_value() -> None:
    assert crc32(b"123456789", 0xFFFFFFFF, 0x04C11DB7) == 0x0376E6E7


def test_empty_data_checksum_initial_values() -> None:
    assert crc8(b"", 0x00, 0x07) == 0x00
    assert crc16(b"", 0xFFFF, 0x1021) == 0xFFFF
    assert crc32(b"", 0xFFFFFFFF, 0x04C11DB7) == 0xFFFFFFFF


def test_checksums_preserve_leading_zero_bytes() -> None:
    assert crc8(b"\x00\x01", 0x00, 0x07) == 0x07
    assert crc16(b"\x00\x01", 0xFFFF, 0x1021) == 0x0D2E
    assert crc32(b"\x00\x01", 0xFFFFFFFF, 0x04C11DB7) == 0x047679CA


def test_specification_parameters_are_configurable() -> None:
    data = b"123456789"

    assert crc8(data, remainder=0x5A, polynomial=0x31) == 0x94
    assert crc16(data, remainder=0x0000, polynomial=0x8005) == 0xFEE8
    assert crc32(data, remainder=0x00000000, polynomial=0x1EDC6F41) == 0xC052A8C8


@pytest.mark.parametrize(
    ("checksum", "maximum"),
    [(crc8, 0xFF), (crc16, 0xFFFF), (crc32, 0xFFFFFFFF)],
)
def test_checksum_parameters_must_fit_algorithm_width(
    checksum: object, maximum: int
) -> None:
    with pytest.raises(ValueError):
        checksum(b"data", remainder=maximum + 1, polynomial=1)  # type: ignore[operator]
    with pytest.raises(ValueError):
        checksum(b"data", remainder=0, polynomial=-1)  # type: ignore[operator]


@pytest.mark.parametrize("checksum", [crc8, crc16, crc32])
def test_checksum_input_must_be_bytes(checksum: object) -> None:
    with pytest.raises(TypeError, match="data must be bytes"):
        checksum(bytearray(b"data"), 0, 1)  # type: ignore[operator]
