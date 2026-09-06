# Specification traceability

Specification:

`Communication Protocol 260401 RF sniffing.pdf`

| Section | Feature | Initial status | Notes |
|---|---|---:|---|
| 1.0 | UART communication mode | Planned | 3.3 V TTL |
| 1.1 | 115200 baud, 8N1 | Planned | UART optional extra; validated on hardware (see `docs/uart-troubleshooting.md`) |
| 1.2 | Frame structure | Planned | Header/address/length/payload/tail |
| 2.0 | Trigger | Planned | Required by automated bench |
| 2.1.1 | Program one sensor | Planned | Required by automated bench |
| 2.1.2 | Multi-sensor program | Deferred | Not required |
| 2.2 | Query sensor | Deferred | Add only if bench requires it |
| 2.6 | Enter program interface | Deferred | Appcode offsets not confirmed |
| 2.7 | Cancel action | Planned | Required for safe recovery |
| 2.8 | Receive RF | Planned | Shares `SensorReading` with Trigger |
| 4.0 | Query Version | First command | Initial hardware test |
| 4.1–4.3 | Upgrade commands | Future | One parameterized implementation |
| 4.4 | Reset | Planned | Board may reset after ~100 ms |
| 5.1–5.2 | CRC8/16/32 | Planned | Implement in `checksums.py` |
| 6 | BLE sensor 2.4G | Deferred | Generic applicability unconfirmed |
