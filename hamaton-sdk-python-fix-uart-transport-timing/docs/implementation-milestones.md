# Implementation milestones

## Milestone 1 — Core framing

Implement and test:

- `frame.py`
- `parser.py`
- `exceptions.py`

Acceptance:

- partial frames across several `feed()` calls;
- multiple frames in one chunk;
- garbage before header;
- invalid length and invalid tail detection.

## Milestone 2 — Codec and models

Implement and test:

- `codec.py`
- `models.py`
- `SensorReading`
- shared command result states

## Milestone 3 — Transport layer

Implement and test:

- `transports/base.py`
- `transports/mock.py`
- `transports/uart.py`

`pyserial` must remain optional.

## Milestone 4 — Client transaction engine

Implement:

- generic command execution;
- timeout handling;
- pending-response timeout reset;
- mock-transport tests.

## Milestone 5 — Query Version

Implement Chapter 4.0 and physical/offline examples.

## Milestone 6 — Program one sensor

Implement Chapter 2.1.1 only.

Do not implement Chapter 2.1.2.

## Milestone 7 — Trigger

Implement Chapter 2.0 and shared `SensorReading` parsing.

## Milestone 8 — Receive RF, Cancel and Reset

Implement Chapters 2.8, 2.7 and 4.4.

## Milestone 9 — Checksums and upgrade architecture

Implement Chapter 5 checksums.

Add one parameterized `commands/upgrade.py` architecture for command IDs 0x41, 0x42 and 0x43.
