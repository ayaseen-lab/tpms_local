"""Chapter 2.7 Cancel action command codec."""

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult


class CancelCodec(CommandCodec):
    """Build and parse the specification Chapter 2.7 Cancel action command.

    Cancel is used to stop Trigger and Program Sensor operations and has a
    one-second response timeout.
    """

    COMMAND = 0x27
    SUBCOMMAND = 0x01
    TIMEOUT_SECONDS = 1.0

    def __init__(self) -> None:
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)

    def build_request_data(self) -> bytes:
        return b""

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Parse the Chapter 2.7 acknowledgement."""
        self.require_matching_response(frame)
        payload = frame.payload
        if self.is_negative_response(frame):
            if len(payload) != 3:
                raise CodecError("Cancel negative response must contain an error code")
            return CommandResult.failure(payload[2], "Cancel action rejected")
        if len(payload) != 2:
            raise CodecError("Cancel acknowledgement must contain exactly two bytes")
        return CommandResult.success(message="action cancelled")
