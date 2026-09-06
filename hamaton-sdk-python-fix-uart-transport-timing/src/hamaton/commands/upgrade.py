"""Parameterized codecs for specification Chapters 4.1 through 4.3."""

from enum import IntEnum

from ..codec import CommandCodec
from ..exceptions import CodecError
from ..frame import HamatonFrame
from ..models import CommandResult


class UpgradeTarget(IntEnum):
    """Board component selected by an upgrade command ID."""

    SOFTWARE = 0x41
    TRIGGER_DATABASE = 0x42
    PROGRAMMING_DATABASE = 0x43


class UpgradeStage(IntEnum):
    """The two upgrade steps defined by Chapters 4.1 through 4.3."""

    METADATA = 0x01
    PACKET = 0x02


class UpgradeAcknowledgement:
    """Validated fields echoed by an upgrade acknowledgement."""

    def __init__(
        self,
        target: UpgradeTarget,
        stage: UpgradeStage,
        first_value: int,
        second_value: int,
    ) -> None:
        self.target = target
        self.stage = stage
        self.first_value = first_value
        self.second_value = second_value

    @property
    def file_length(self) -> int | None:
        return self.first_value if self.stage is UpgradeStage.METADATA else None

    @property
    def file_crc32(self) -> int | None:
        return self.second_value if self.stage is UpgradeStage.METADATA else None

    @property
    def total_packets(self) -> int | None:
        return self.first_value if self.stage is UpgradeStage.PACKET else None

    @property
    def sequence_number(self) -> int | None:
        return self.second_value if self.stage is UpgradeStage.PACKET else None


class UpgradeCodec(CommandCodec):
    """One parameterized implementation for command IDs 0x41, 0x42, and 0x43.

    Use :meth:`metadata` for step 1 and :meth:`packet` for step 2. Packet data
    is limited to 512 bytes, sequence numbers start at one, and packet responses
    may be attempted at most three times by a higher-level upgrade coordinator.
    """

    PACKET_DATA_LIMIT = 512
    MAX_PACKET_ATTEMPTS = 3
    PACKET_TIMEOUT_SECONDS = 2.0

    def __init__(
        self,
        target: UpgradeTarget | int,
        stage: UpgradeStage | int,
        data: bytes,
        timeout_seconds: float,
    ) -> None:
        try:
            validated_target = UpgradeTarget(target)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "target must be upgrade command 0x41, 0x42, or 0x43"
            ) from error
        try:
            validated_stage = UpgradeStage(stage)
        except (TypeError, ValueError) as error:
            raise ValueError("stage must be metadata 0x01 or packet 0x02") from error
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")

        super().__init__(int(validated_target), int(validated_stage), timeout_seconds)
        self.target = validated_target
        self.stage = validated_stage
        self.data = data
        if self.stage is UpgradeStage.PACKET:
            self.max_attempts = self.MAX_PACKET_ATTEMPTS
        self._validate_stage_data()

    @classmethod
    def metadata(
        cls,
        target: UpgradeTarget | int,
        file_length: int,
        file_crc32: int,
    ) -> "UpgradeCodec":
        """Build step 1: four-byte file length followed by four-byte CRC32."""
        cls._validate_uint32(file_length, "file_length")
        cls._validate_uint32(file_crc32, "file_crc32")
        validated_target = cls._validate_target(target)
        timeout = 1.0 if validated_target is UpgradeTarget.SOFTWARE else 2.0
        data = file_length.to_bytes(4, "big") + file_crc32.to_bytes(4, "big")
        return cls(validated_target, UpgradeStage.METADATA, data, timeout)

    @classmethod
    def packet(
        cls,
        target: UpgradeTarget | int,
        total_packets: int,
        sequence_number: int,
        data: bytes,
    ) -> "UpgradeCodec":
        """Build step 2: packet counts followed by at most 512 data bytes."""
        cls._validate_uint32(total_packets, "total_packets")
        cls._validate_uint32(sequence_number, "sequence_number")
        if total_packets < 1:
            raise ValueError("total_packets must be at least one")
        if not 1 <= sequence_number <= total_packets:
            raise ValueError("sequence_number must be between one and total_packets")
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        if not 1 <= len(data) <= cls.PACKET_DATA_LIMIT:
            raise ValueError("packet data must contain between 1 and 512 bytes")

        prefix = total_packets.to_bytes(4, "big") + sequence_number.to_bytes(4, "big")
        return cls(target, UpgradeStage.PACKET, prefix + data, cls.PACKET_TIMEOUT_SECONDS)

    @property
    def requires_automatic_reset(self) -> bool:
        """Software upgrades reset automatically; database upgrades do not."""
        return self.target is UpgradeTarget.SOFTWARE

    def build_request_data(self) -> bytes:
        return self.data

    def parse_response(self, frame: HamatonFrame) -> CommandResult:
        """Validate echoed metadata or packet fields and decode packet errors."""
        self.require_matching_response(frame)
        if self.is_negative_response(frame):
            return self._parse_negative_response(frame.payload)
        return CommandResult.success(self._parse_acknowledgement(frame.payload))

    def _parse_acknowledgement(self, payload: bytes) -> UpgradeAcknowledgement:
        if len(payload) != 10:
            raise CodecError("upgrade acknowledgement must contain exactly 10 bytes")
        first_value = int.from_bytes(payload[2:6], "big")
        second_value = int.from_bytes(payload[6:10], "big")
        if payload[2:10] != self.data[:8]:
            raise CodecError("upgrade acknowledgement does not match the request")
        return UpgradeAcknowledgement(
            self.target, self.stage, first_value, second_value
        )

    def _parse_negative_response(self, payload: bytes) -> CommandResult:
        if self.stage is not UpgradeStage.PACKET:
            raise CodecError("metadata upgrade step has no specified negative response")
        if len(payload) != 11:
            raise CodecError(
                "upgrade packet negative response must contain exactly 11 bytes"
            )
        if payload[2:10] != self.data[:8]:
            raise CodecError("upgrade negative response does not match the request")

        error_code = payload[10]
        messages = {0x01: "sequence number incorrect", 0x02: "checksum error"}
        return CommandResult.failure(
            error_code, messages.get(error_code, "unknown upgrade error")
        )

    def _validate_stage_data(self) -> None:
        if self.stage is UpgradeStage.METADATA and len(self.data) != 8:
            raise ValueError("metadata data must contain exactly eight bytes")
        if self.stage is UpgradeStage.PACKET:
            if not 9 <= len(self.data) <= 8 + self.PACKET_DATA_LIMIT:
                raise ValueError("packet data must contain an 8-byte header and payload")

    @staticmethod
    def _validate_target(target: UpgradeTarget | int) -> UpgradeTarget:
        try:
            return UpgradeTarget(target)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "target must be upgrade command 0x41, 0x42, or 0x43"
            ) from error

    @staticmethod
    def _validate_uint32(value: int, name: str) -> None:
        if not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in four bytes")
