"""Query a physical Hamaton board over a 3.3 V TTL UART adapter."""

import argparse

from hamaton.client import HamatonClient
from hamaton.commands.query_version import QueryVersionCodec
from hamaton.models import VersionInfo
from hamaton.transports.uart import UartTransport


def print_versions(version: VersionInfo) -> None:
    for name, value in version.as_dict().items():
        print(f"{name}: 0x{value:08X} ({value})")


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Read version information from a Hamaton TPMS board."
    )
    argument_parser.add_argument(
        "port",
        help="Windows COM port connected through a 3.3 V TTL adapter, e.g. COM12",
    )
    argument_parser.add_argument(
        "--baudrate",
        type=int,
        default=UartTransport.DEFAULT_BAUD_RATE,
        help="UART baud rate. Validated boards respond at 115200 baud (section 1.1).",
    )
    arguments = argument_parser.parse_args()

    transport = UartTransport(arguments.port, baudrate=arguments.baudrate)
    with HamatonClient(transport) as client:
        result = client.execute(QueryVersionCodec())

    print_versions(result.value)


if __name__ == "__main__":
    main()
