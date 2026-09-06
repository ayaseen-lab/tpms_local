"""CRC8, CRC16 and CRC32 helpers from specification Chapter 5."""


def crc8(data: bytes, remainder: int, polynomial: int) -> int:
    """Return Chapter 5.1 CRC8 with configurable remainder and polynomial."""
    _validate_data(data)
    _validate_parameter(remainder, 0xFF, "remainder")
    _validate_parameter(polynomial, 0xFF, "polynomial")
    checksum = remainder
    for byte in data:
        checksum ^= byte
        for _ in range(8):
            if checksum & 0x80:
                checksum = ((checksum << 1) ^ polynomial) & 0xFF
            else:
                checksum = (checksum << 1) & 0xFF
    return checksum


def crc16(data: bytes, remainder: int, polynomial: int) -> int:
    """Return Chapter 5.2 CRC16 with configurable remainder and polynomial."""
    _validate_data(data)
    _validate_parameter(remainder, 0xFFFF, "remainder")
    _validate_parameter(polynomial, 0xFFFF, "polynomial")
    checksum = remainder
    for byte in data:
        checksum ^= byte << 8
        for _ in range(8):
            if checksum & 0x8000:
                checksum = ((checksum << 1) ^ polynomial) & 0xFFFF
            else:
                checksum = (checksum << 1) & 0xFFFF
    return checksum


def crc32(
    data: bytes,
    remainder: int,
    polynomial: int,
) -> int:
    """Return Chapter 5.2 non-reflected CRC32 without a final XOR."""
    _validate_data(data)
    _validate_parameter(remainder, 0xFFFFFFFF, "remainder")
    _validate_parameter(polynomial, 0xFFFFFFFF, "polynomial")
    checksum = remainder
    for byte in data:
        checksum ^= byte << 24
        for _ in range(8):
            if checksum & 0x80000000:
                checksum = ((checksum << 1) ^ polynomial) & 0xFFFFFFFF
            else:
                checksum = (checksum << 1) & 0xFFFFFFFF
    return checksum


def _validate_data(data: bytes) -> None:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")


def _validate_parameter(value: int, maximum: int, name: str) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and 0x{maximum:X}")
