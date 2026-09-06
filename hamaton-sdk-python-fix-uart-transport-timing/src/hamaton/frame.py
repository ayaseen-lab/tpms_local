"""UART envelope from specification section 1.2."""

from .exceptions import FrameError, FrameLengthError, FrameTailError


class HamatonFrame:
    """One validated Hamaton UART frame."""

    HEADER = 0x3C
    TAIL = 0x3E
    HOST_ADDRESS = 0x11
    BOARD_ADDRESS = 0x22
    OVERHEAD = 5
    MAX_PAYLOAD_LENGTH = 0xFFFF

    def __init__(self, address: int, payload: bytes) -> None:
        if not isinstance(address, int):
            raise TypeError("address must be an integer")
        if not 0 <= address <= 0xFF:
            raise ValueError("address must fit in one byte")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if len(payload) > self.MAX_PAYLOAD_LENGTH:
            raise FrameLengthError("payload exceeds the two-byte length field")
        self.address = address
        self.payload = payload

    @property
    def command(self) -> int | None:
        return self.payload[0] if self.payload else None

    @property
    def subcommand(self) -> int | None:
        return self.payload[1] if len(self.payload) > 1 else None

    def to_bytes(self) -> bytes:
        length = len(self.payload).to_bytes(2, "big")
        return bytes([self.HEADER, self.address]) + length + self.payload + bytes(
            [self.TAIL]
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "HamatonFrame":
        if not isinstance(raw, bytes):
            raise TypeError("raw must be bytes")
        if len(raw) < cls.OVERHEAD:
            raise FrameLengthError("frame is too short")
        if raw[0] != cls.HEADER:
            raise FrameError(f"invalid header 0x{raw[0]:02X}")
        payload_length = int.from_bytes(raw[2:4], "big")
        expected_length = payload_length + cls.OVERHEAD
        if len(raw) != expected_length:
            raise FrameLengthError(
                f"frame declares {payload_length} payload bytes; "
                f"expected {expected_length} total bytes, received {len(raw)}"
            )
        if raw[-1] != cls.TAIL:
            raise FrameTailError(f"invalid tail 0x{raw[-1]:02X}")
        return cls(raw[1], raw[4:-1])

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, HamatonFrame)
            and self.address == other.address
            and self.payload == other.payload
        )

    def __repr__(self) -> str:
        return f"HamatonFrame(address=0x{self.address:02X}, payload={self.payload!r})"
