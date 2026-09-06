# Codex implementation brief

Implement this repository milestone by milestone.

Use `Communication Protocol 260401 RF sniffing.pdf` as the source specification.

## Non-negotiable architecture

- `frame.py` is the UART envelope model.
- `parser.py` is a stateful byte-stream frame parser.
- `codec.py` defines the command codec abstraction.
- `client.py` owns send/read/timeout/pending-response orchestration.
- `models.py` owns shared result types, including `SensorReading`.
- `checksums.py` owns CRC8/16/32.
- `transports/uart.py` depends on optional `pyserial`.
- tests mirror the source tree one-to-one.

## Initial command scope

Implement:

- 4.0 Query Version
- 2.1.1 Program one sensor
- 2.0 Trigger
- 2.8 Receive RF
- 2.7 Cancel action
- 4.4 Reset

Do not implement:

- 2.1.2 Multi-sensor programming
- 2.6 Enter program interface
- Section 6 BLE interpretation
- 2.2 Query sensor unless explicitly requested later

## Coding style

Use beginner-readable Python:

- explicit classes and `__init__()`;
- no dataclasses initially;
- clear type hints;
- small methods;
- descriptive local variables;
- specification references in public command docstrings;
- no command-to-command imports.

Run tests and Ruff after each milestone.
