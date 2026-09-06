"""Run Query Version without hardware using a recorded response frame."""

from hamaton.client import HamatonClient
from hamaton.commands.query_version import QueryVersionCodec
from hamaton.models import VersionInfo
from hamaton.transports.mock import MockTransport


RECORDED_RESPONSE = bytes.fromhex(
    "3C 22 00 16 40 01 "
    "00 00 00 03 "
    "00 00 00 03 "
    "00 00 00 20 "
    "00 00 00 20 "
    "00 00 00 45 "
    "3E"
)


def print_versions(version: VersionInfo) -> None:
    for name, value in version.as_dict().items():
        print(f"{name}: 0x{value:08X} ({value})")


def main() -> None:
    transport = MockTransport([RECORDED_RESPONSE])
    with HamatonClient(transport) as client:
        result = client.execute(QueryVersionCodec())

    print("Transmitted:", transport.writes[0].hex(" ").upper())
    print_versions(result.value)


if __name__ == "__main__":
    main()
