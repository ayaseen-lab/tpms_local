"""Chapter 4.4 TPMS Reset command codec."""

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult


class ResetCodec(CommandCodec):
    """Build and parse the specification Chapter 4.4 TPMS Reset command.

    The board may reset approximately 100 ms after acknowledging this command.
    No additional response is expected after the acknowledgement.
    """

    COMMAND = 0x44
    SUBCOMMAND = 0x01
    TIMEOUT_SECONDS = 2.0

    def __init__(self) -> None:
        super().__init__(self.COMMAND, self.SUBCOMMAND, self.TIMEOUT_SECONDS)

    def build_request_data(self) -> bytes:
        return b""

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Parse the Chapter 4.4 acknowledgement."""
        self.require_matching_response(frame)
        payload = frame.payload
        if self.is_negative_response(frame):
            if len(payload) != 3:
                raise CodecError("Reset negative response must contain an error code")
            return CommandResult.failure(payload[2], "TPMS reset rejected")
        if len(payload) != 2:
            raise CodecError("Reset acknowledgement must contain exactly two bytes")
        return CommandResult.success(message="TPMS reset acknowledged")
