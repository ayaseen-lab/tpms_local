"""Deterministic in-memory transport for tests and offline examples."""

from collections.abc import Iterable

from ..exceptions import TransportClosedError
from .base import HamatonTransport


class MockTransport(HamatonTransport):
    """Record writes and return queued read chunks without hardware."""

    def __init__(
        self,
        read_chunks: Iterable[bytes] | None = None,
        open_immediately: bool = False,
    ) -> None:
        self._is_open = False
        self._read_chunks: list[bytes] = []
        self.writes: list[bytes] = []
        self.read_requests: list[tuple[int, float]] = []
        if read_chunks is not None:
            for chunk in read_chunks:
                self.queue_read(chunk)
        if open_immediately:
            self.open()

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def pending_read_count(self) -> int:
        return len(self._read_chunks)

    def open(self) -> None:
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def write(self, data: bytes) -> None:
        self.validate_write_data(data)
        self._require_open()
        self.writes.append(data)

    def read(self, max_bytes: int, timeout_seconds: float) -> bytes:
        self.validate_read_arguments(max_bytes, timeout_seconds)
        self._require_open()
        self.read_requests.append((max_bytes, timeout_seconds))
        if not self._read_chunks:
            return b""

        chunk = self._read_chunks.pop(0)
        returned = chunk[:max_bytes]
        remainder = chunk[max_bytes:]
        if remainder:
            self._read_chunks.insert(0, remainder)
        return returned

    def queue_read(self, data: bytes) -> None:
        """Append bytes that a later call to ``read`` will return."""
        self.validate_write_data(data)
        if data:
            self._read_chunks.append(data)

    def clear(self) -> None:
        """Discard recorded writes and unread input."""
        self.writes.clear()
        self.read_requests.clear()
        self._read_chunks.clear()

    def _require_open(self) -> None:
        if not self.is_open:
            raise TransportClosedError("mock transport is closed")
