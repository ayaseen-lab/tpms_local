# Architecture

## Main separation of responsibilities

```text
Application
    |
HamatonClient
    |
Command codec
    |
Transport
    |
UART byte stream
    |
HamatonStreamParser
    |
HamatonFrame
```

## Modules

### `frame.py`

Owns the raw UART frame envelope:

```text
header + address + payload length + payload + tail
```

It does not understand command meanings, retries, timeouts, or UART transport.

### `parser.py`

Owns stateful stream framing.

It buffers partial UART input, discards leading garbage, extracts complete frames, and preserves incomplete data for the next call.

It does not interpret pending, positive, or negative command responses.

### `codec.py`

Defines the shared command-codec contract.

Each command codec builds request bytes and parses a command-specific payload into a typed result.

### `client.py`

Owns transaction orchestration:

- build request;
- send through transport;
- read bytes;
- feed parser;
- pass payload to codec;
- apply timeout and pending-response policy;
- return typed results.

The 12-second timeout-reset behavior for pending Trigger and Program Sensor responses belongs here.

### `models.py`

Contains shared protocol result objects such as `SensorReading`.

### `checksums.py`

Contains CRC8, CRC16, and CRC32 implementations from Chapter 5.

### `transports/`

Contains hardware-independent transport abstractions and UART/mock implementations.

### `commands/`

Contains one module per implemented specification command, except Upgrade, which is parameterized in one shared module.
