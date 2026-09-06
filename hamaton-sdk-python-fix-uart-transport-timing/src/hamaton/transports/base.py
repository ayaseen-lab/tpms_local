"""Hardware-independent byte transport contract."""

from abc import ABC, abstractmethod
from types import TracebackType


class HamatonTransport(ABC):
    """Synchronous byte-stream transport used by the Hamaton client."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Return whether the transport is ready for input and output."""

    @abstractmethod
    def open(self) -> None:
        """Open the transport."""

    @abstractmethod
    def close(self) -> None:
        """Close the transport. Calling this repeatedly must be safe."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Write every byte in ``data`` or raise a transport error."""

    @abstractmethod
    def read(self, max_bytes: int, timeout_seconds: float) -> bytes:
        """Read up to ``max_bytes``, returning empty bytes on timeout."""

    def __enter__(self) -> "HamatonTransport":
        self.open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @staticmethod
    def validate_write_data(data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")

    @staticmethod
    def validate_read_arguments(max_bytes: int, timeout_seconds: float) -> None:
        if not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
