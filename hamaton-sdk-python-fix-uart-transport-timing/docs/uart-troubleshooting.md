# UART troubleshooting

## Symptom: `query_version_uart.py` times out while `tools/uart_raw_test.py` works

### Root cause

Hardware validation confirmed that **115200 baud** is the only working line rate.
Rates tested manually in `tools/uart_raw_test.py` were 9600, 19200, 38400, 57600,
115200, and 230400. Only at **115200** did the CH340 RX LED blink and a valid
`3C 22 …` response arrive.

The SDK already opened the port at 115200 baud, so baud rate was **not** the
failure. The timeout came from **post-write timing** and **read strategy**:

| Setting | `uart_raw_test.py` | SDK before fix | Impact |
|---|---|---|---|
| Baud rate | 115200 (validated) | 115200 | Same — not the cause |
| Port read timeout at open | 2 s | 0 (per-read timeout applied later) | Not a root cause |
| Post-write delay | `time.sleep(0.2)` | none | **Primary failure.** The board needs time to produce a reply before the first read. |
| Read strategy | `read_all()` | single `read(max_bytes)` | **Secondary.** `read_all()` drains the full adapter buffer in one call. |
| `reset_input_buffer()` | before write | before write | Same behavior |
| `flush()` | after write | after write | Same behavior |
| Flow control | pyserial defaults (off) | pyserial defaults (off) | Same behavior |

The Hamaton frame bytes are identical in both paths (`3C 11 00 02 40 01 3E`).
Only the timing after write and how incoming bytes are drained differed.

### Fix

`UartTransport` now applies a **200 ms post-write delay** and drains
`in_waiting` after the first received byte, matching the working raw test.
Baud rate remains **115200** per specification section 1.1.

```python
from hamaton.transports.uart import UartTransport

transport = UartTransport("COM5")
```

Override baud rate only when your adapter or board requires it:

```powershell
python examples/query_version_uart.py COM5 --baudrate 115200
```

### Validating baud rate

Change `baudrate` in `tools/uart_raw_test.py` and look for:

1. CH340 RX LED activity after the request is sent
2. A response beginning with `3C 22`

If neither occurs, the baud rate does not match the board.
