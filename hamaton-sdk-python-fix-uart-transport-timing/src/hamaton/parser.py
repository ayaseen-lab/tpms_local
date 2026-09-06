"""Stateful parser for a stream of Hamaton UART bytes."""

from .exceptions import FrameLengthError, FrameTailError
from .frame import HamatonFrame


class HamatonStreamParser:
    """Buffer partial input and extract complete validated frames."""

    def __init__(
        self,
        max_payload_length: int = HamatonFrame.MAX_PAYLOAD_LENGTH,
    ) -> None:
        if not 0 <= max_payload_length <= HamatonFrame.MAX_PAYLOAD_LENGTH:
            raise ValueError("max_payload_length must be between 0 and 65535")
        self.max_payload_length = max_payload_length
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> bytes:
        return bytes(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[HamatonFrame]:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        self._buffer.extend(data)
        frames = []

        while self._buffer:
            header_index = self._buffer.find(HamatonFrame.HEADER)
            if header_index < 0:
                self._buffer.clear()
                break
            if header_index:
                del self._buffer[:header_index]
            if len(self._buffer) < 4:
                break

            payload_length = int.from_bytes(self._buffer[2:4], "big")
            if payload_length > self.max_payload_length:
                del self._buffer[0]
                raise FrameLengthError(
                    f"declared payload length {payload_length} exceeds parser limit "
                    f"{self.max_payload_length}",
                    parsed_frames=frames,
                )
            total_length = payload_length + HamatonFrame.OVERHEAD
            if len(self._buffer) < total_length:
                break
            raw = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]
            if raw[-1] != HamatonFrame.TAIL:
                raise FrameTailError(
                    f"invalid tail 0x{raw[-1]:02X}",
                    parsed_frames=frames,
                )
            frames.append(HamatonFrame.from_bytes(raw))

        return frames
