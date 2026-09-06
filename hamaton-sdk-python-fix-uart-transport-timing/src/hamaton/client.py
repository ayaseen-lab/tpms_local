"""Application-facing Hamaton transaction engine."""

import time
from types import TracebackType
from typing import Callable

from .codec import CommandCodec
from .exceptions import CommandTimeoutError
from .models import CommandResult
from .parser import HamatonStreamParser
from .transports.base import HamatonTransport


Clock = Callable[[], float]


class HamatonClient:
    """Execute command codecs over one synchronous byte transport.

    One client handles one transaction at a time. A pending response restarts
    the complete command timeout, as required for long-running Trigger and
    Program Sensor operations.
    """

    def __init__(
        self,
        transport: HamatonTransport,
        parser: HamatonStreamParser | None = None,
        read_size: int = 256,
        clock: Clock | None = None,
    ) -> None:
        if not isinstance(transport, HamatonTransport):
            raise TypeError("transport must be a HamatonTransport")
        if not isinstance(read_size, int):
            raise TypeError("read_size must be an integer")
        if read_size <= 0:
            raise ValueError("read_size must be greater than zero")

        self.transport = transport
        self.parser = parser or HamatonStreamParser()
        self.read_size = read_size
        self._clock = clock or time.monotonic

    @property
    def is_open(self) -> bool:
        return self.transport.is_open

    def open(self) -> None:
        self.transport.open()

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "HamatonClient":
        self.open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def execute(self, codec: CommandCodec) -> CommandResult:
        """Send one command and wait for its terminal response.

        The transport must already be open. Frames for other commands are
        ignored. When the matching codec returns ``PENDING``, the deadline is
        reset to the codec's complete timeout rather than merely extended by
        the time remaining from the original request.
        """
        if not isinstance(codec, CommandCodec):
            raise TypeError("codec must be a CommandCodec")

        self.parser.reset()
        request = codec.build_request()
        attempt = 1
        self.transport.write(request)
        deadline = self._clock() + codec.timeout_seconds

        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                if attempt >= codec.max_attempts:
                    self._raise_timeout(codec)
                attempt += 1
                self.parser.reset()
                self.transport.write(request)
                deadline = self._clock() + codec.timeout_seconds
                continue

            received = self.transport.read(self.read_size, remaining)
            if not received:
                if attempt >= codec.max_attempts:
                    self._raise_timeout(codec)
                attempt += 1
                self.parser.reset()
                self.transport.write(request)
                deadline = self._clock() + codec.timeout_seconds
                continue

            frames = self.parser.feed(received)
            for frame in frames:
                if not codec.accepts_response(frame):
                    continue

                result = codec.parse_response(frame)
                if not isinstance(result, CommandResult):
                    raise TypeError("parse_response() must return CommandResult")
                if result.is_pending:
                    deadline = self._clock() + codec.timeout_seconds
                    continue
                return result

    @staticmethod
    def _raise_timeout(codec: CommandCodec) -> None:
        raise CommandTimeoutError(
            f"command 0x{codec.command:02X} did not complete within "
            f"{codec.timeout_seconds:g} seconds"
        )
