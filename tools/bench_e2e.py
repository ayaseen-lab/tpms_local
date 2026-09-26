"""End-to-end bench run for the first rows: program, LF trigger, read, SDR.

Run:  python tools/bench_e2e.py [rows]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "sdr_ui"),
    str(ROOT / "hamaton-sdk-python-fix-uart-transport-timing" / "src"),
    str(ROOT),
]

from tpms_bench.hardware import check_hardware_trio, preferred_usb_ttl_port  # noqa: E402
from tpms_bench.rtl433 import free_dongle  # noqa: E402
from tpms_bench.runner import BenchRunner, ProgressEvent, reset_session_db  # noqa: E402

XLSX = Path(
    "/Users/mr.macbook/Downloads/hamaton-sdk-python-fix-uart-transport-timing"
    "/Hamaton_database_20260126_1305.xlsx"
)


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 4

    trio = check_hardware_trio()
    for line in trio.summary_lines():
        print(line, flush=True)

    free_dongle()
    reset_session_db()

    runner = BenchRunner(
        port=preferred_usb_ttl_port(),
        source_xlsx=XLSX,
        resume=False,
        skip_sdr=False,
        on_progress=lambda e: None,
    )

    done: list[ProgressEvent] = []

    def on_progress(event: ProgressEvent) -> None:
        if event.kind == "started":
            print(f"started: {event.message}", flush=True)
        elif event.kind == "row_done":
            done.append(event)
            print(
                f"row {event.excel_row:>3} {event.performance:<3} "
                f"id={event.sensor_id or '—':<9} {event.temperature or '—':>4}C "
                f"{event.voltage or '—':>6}V  sdr={event.sdr_compare or '—':<8} "
                f"{(event.duration_s or 0):5.1f}s  {event.reason or ''}\n"
                f"        sdr_reason: {event.sdr_reason or '—'}",
                flush=True,
            )
            if len(done) >= limit:
                runner.request_stop()
        elif event.kind in ("error", "stopped", "finished"):
            print(f"{event.kind}: {event.message}", flush=True)

    runner.on_progress = on_progress
    try:
        runner.run()
    except Exception as exc:
        print(f"RUN ERROR: {type(exc).__name__}: {exc}", flush=True)
        return 1

    ok = sum(1 for e in done if e.performance == "OK")
    print(f"\n{ok}/{len(done)} rows OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
