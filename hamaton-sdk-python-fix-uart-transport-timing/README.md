# hamaton-sdk-python

Python SDK for communicating with the Hamaton TPMS Board over its 3.3 V TTL UART interface.

The protocol specification is located under docs/specifications/ and should be consulted when implementing or reviewing protocol commands.

This repository initially contains only the agreed project structure and development configuration. Command implementations will be added milestone by milestone.

## Scope

The first SDK version is intended to support the automated TPMS validation bench:

- Query Version — Chapter 4.0
- Program one sensor — Chapter 2.1.1
- Trigger — Chapter 2.0
- Receive RF signal — Chapter 2.8
- Cancel TPMS action — Chapter 2.7
- TPMS reset — Chapter 4.4

The following are intentionally deferred:

- Multi-sensor programming — Chapter 2.1.2
- Enter program interface — Chapter 2.6
- BLE sensor interpretation — Section 6
- Query sensor — Chapter 2.2, unless later required by the bench

## Repository structure

```text
hamaton-sdk-python/
|-- .github/
|   `-- workflows/
|       `-- tests.yml
|-- docs/
|   |-- architecture.md
|   |-- implementation-milestones.md
|   |-- specification-traceability.md
|   `-- specifications/
|       `-- Communication Protocol 260401 RF sniffing.pdf
|-- examples/
|   |-- .gitkeep
|   |-- query_version_offline.py
|   `-- query_version_uart.py
|-- src/
|   `-- hamaton/
|       |-- __init__.py
|       |-- checksums.py
|       |-- client.py
|       |-- codec.py
|       |-- commands/
|       |   |-- __init__.py
|       |   |-- cancel.py
|       |   |-- program_sensor.py
|       |   |-- query_version.py
|       |   |-- receive_rf.py
|       |   |-- reset.py
|       |   |-- trigger.py
|       |   `-- upgrade.py
|       |-- exceptions.py
|       |-- frame.py
|       |-- models.py
|       |-- parser.py
|       |-- sensor_reading.py
|       `-- transports/
|           |-- __init__.py
|           |-- base.py
|           |-- mock.py
|           `-- uart.py
|-- tests/
|   |-- commands/
|   |   |-- .gitkeep
|   |   |-- test_cancel.py
|   |   |-- test_program_sensor.py
|   |   |-- test_query_version.py
|   |   |-- test_receive_rf.py
|   |   |-- test_reset.py
|   |   |-- test_trigger.py
|   |   `-- test_upgrade.py
|   |-- transports/
|   |   |-- .gitkeep
|   |   |-- test_base.py
|   |   |-- test_mock.py
|   |   `-- test_uart.py
|   |-- test_checksums.py
|   |-- test_client.py
|   |-- test_codec.py
|   |-- test_exceptions.py
|   |-- test_frame.py
|   |-- test_models.py
|   |-- test_parser.py
|   `-- test_sensor_reading.py
|-- .gitignore
|-- CODEX_IMPLEMENTATION_BRIEF.md
|-- README.md
`-- pyproject.toml
```

## Development setup

```powershell
cd C:\Dev\hamaton-sdk-python

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[dev]"

pytest
ruff check .
```

Protocol-only use has no required third-party dependency:

```powershell
pip install -e .
```

UART support is optional:

```powershell
pip install -e ".[uart]"
```

## Query Version examples

Run the Chapter 4.0 flow against a recorded response without hardware:

```powershell
.\.venv\Scripts\python.exe examples\query_version_offline.py
```

Query a physical board through a 3.3 V TTL UART adapter:

```powershell
.\.venv\Scripts\python.exe examples\query_version_uart.py COM12
```

If the command times out, see [UART troubleshooting](docs/uart-troubleshooting.md).
Validated boards respond at 115200 baud (specification section 1.1).

## Hardware caution

The specification defines UART with 3.3 V TTL levels. Do not connect a 5 V UART signal directly to the Hamaton TPMS Board.