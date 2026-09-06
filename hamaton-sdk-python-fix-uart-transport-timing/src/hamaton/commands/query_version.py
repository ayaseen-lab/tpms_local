"""Chapter 4.0 Query Version command codec."""

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult, VersionInfo


class QueryVersionCodec(CommandCodec):
    """Build and parse the specification Chapter 4.0 Query Version command.

    A successful response contains command and subcommand bytes followed by
    five unsigned four-byte, big-endian version values: hardware, boot,
    software, trigger database, and programming database.
    """

    COMMAND = 0x40
    SUBCOMMAND = 0x01
    TIMEOUT_SECONDS = 2.0
    RESPONSE_PAYLOAD_LENGTH = 22

    def __init__(self) -> None:
        super().__init__(
            command=self.COMMAND,
            subcommand=self.SUBCOMMAND,
            timeout_seconds=self.TIMEOUT_SECONDS,
        )

    def build_request_data(self) -> bytes:
        return b""

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Parse a Chapter 4.0 response into a typed ``VersionInfo`` result."""
        self.require_matching_response(frame)
        payload = frame.payload

        if self.is_negative_response(frame):
            if len(payload) < 3:
                raise CodecError("Query Version negative response has no error code")
            return CommandResult.failure(payload[2], "Query Version rejected")

        if len(payload) != self.RESPONSE_PAYLOAD_LENGTH:
            raise CodecError(
                "Query Version response payload must contain exactly 22 bytes; "
                f"received {len(payload)}"
            )

        version_values = []
        for offset in range(2, self.RESPONSE_PAYLOAD_LENGTH, 4):
            version_values.append(int.from_bytes(payload[offset : offset + 4], "big"))

        version = VersionInfo(
            hardware_version=version_values[0],
            boot_version=version_values[1],
            software_version=version_values[2],
            trigger_database_version=version_values[3],
            programming_database_version=version_values[4],
        )
        return CommandResult.success(version)
