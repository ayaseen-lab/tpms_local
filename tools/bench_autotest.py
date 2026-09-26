"""Headless bench trial: try recovery strategies until several rows pass in a row.

Run:  python tools/bench_autotest.py [rows] [strategy ...]

TX goes out on USB-TTL; board replies are read back over J-Link SWD.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "sdr_ui"),
    str(ROOT / "hamaton-sdk-python-fix-uart-transport-timing" / "src"),
    str(ROOT),
]

from openpyxl import load_workbook  # noqa: E402

from hamaton.commands.receive_rf import ReceiveRfCodec  # noqa: E402
from hamaton.commands.trigger import TriggerCodec  # noqa: E402
from hamaton.models import ProgramResult  # noqa: E402
from tpms_bench.board import BoardSession, generate_unique_oeid  # noqa: E402
from tpms_bench.excel_io import parse_code  # noqa: E402
from tpms_bench.hardware import check_hardware_trio, preferred_usb_ttl_port  # noqa: E402
from tpms_bench.program_one import ProgramSensorCodec  # noqa: E402
from tpms_bench.program_search import ProgramSearchCodec  # noqa: E402
from tpms_bench.uart import open_uart  # noqa: E402

XLSX = Path(
    "/Users/mr.macbook/Downloads/hamaton-sdk-python-fix-uart-transport-timing"
    "/Hamaton_database_20260126_1305.xlsx"
)
PROGRAM_TIMEOUT = 12.0


def log(msg: str) -> None:
    print(msg, flush=True)


def load_rows(count: int) -> list[dict]:
    wb = load_workbook(XLSX, read_only=True)
    ws = wb[wb.sheetnames[0]]
    header = {}
    for idx, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1)), start=1):
        name = str(cell.value or "").strip().upper().replace(" ", "")
        header[name] = idx
    col_a = header.get("CODEA", 16)
    col_b = header.get("CODEB", 17)
    col_c = header.get("CODEC", 18)
    rows: list[dict] = []
    for excel_row in range(2, 2 + count * 6):
        vals = [ws.cell(excel_row, c).value for c in (col_a, col_b, col_c)]
        codes = [parse_code(v) for v in vals]
        if None in codes:
            continue
        rows.append(
            {
                "row": excel_row,
                "make": str(ws.cell(excel_row, header.get("MAKE", 1)).value or ""),
                "model": str(ws.cell(excel_row, header.get("MODEL", 2)).value or ""),
                "codes": tuple(codes),
            }
        )
        if len(rows) >= count:
            break
    wb.close()
    return rows


def wake(session: BoardSession, codes, seconds: float) -> None:
    """LF-wake a sensor with the codes it currently holds."""
    try:
        session.send_codec(ReceiveRfCodec(True, *codes))
        session.send_codec(TriggerCodec(*codes))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            session._read_uart_frames(0.15)
            time.sleep(0.05)
        session.send_codec(ReceiveRfCodec(False, *codes))
    except Exception as exc:
        log(f"      wake error: {exc}")
    session.cancel()


def program_once(session: BoardSession, codes, oeid: int):
    return session.execute(ProgramSensorCodec(*codes, oeid), timeout=PROGRAM_TIMEOUT)


# Each strategy programs one row and returns the CommandResult.
def s_baseline(session, codes, oeid, prev):
    """Exactly what the bench does per row."""
    return session.program(*codes, oeid)


def s_hard_reset(session, codes, oeid, prev):
    session.idle_board(hard=True)
    return program_once(session, codes, oeid)


def s_wake_prev(session, codes, oeid, prev):
    session.idle_board(hard=False)
    if prev:
        wake(session, prev, 3.0)
    return program_once(session, codes, oeid)


def s_wake_new(session, codes, oeid, prev):
    session.idle_board(hard=False)
    wake(session, codes, 3.0)
    return program_once(session, codes, oeid)


def s_search(session, codes, oeid, prev):
    session.idle_board(hard=False)
    try:
        res = session.execute(ProgramSearchCodec(*codes), timeout=10.0)
        log(f"      search: {res.is_success} {res.message or ''}")
    except Exception as exc:
        log(f"      search error: {exc}")
    session.cancel()
    return program_once(session, codes, oeid)


def s_no_idle(session, codes, oeid, prev):
    session._flush_uart()
    return program_once(session, codes, oeid)


def s_wake_prev_reset(session, codes, oeid, prev):
    if prev:
        wake(session, prev, 3.0)
    session.idle_board(hard=True)
    return program_once(session, codes, oeid)


STRATEGIES = {
    "baseline": s_baseline,
    "hard_reset": s_hard_reset,
    "wake_prev": s_wake_prev,
    "wake_new": s_wake_new,
    "search": s_search,
    "no_idle": s_no_idle,
    "wake_prev_reset": s_wake_prev_reset,
}


def run_strategy(name: str, rows: list[dict], used: set[int]) -> list[bool]:
    fn = STRATEGIES[name]
    log(f"\n=== strategy: {name} ===")
    ser = open_uart(preferred_usb_ttl_port())
    session = BoardSession(ser)
    outcomes: list[bool] = []
    try:
        ok, msg = session.verify_hardware()
        log(f"  hardware: {ok} · {msg}")
        session.detect_transport()
        log(f"  transport: {session.transport_mode}")
        prev = None
        for entry in rows:
            oeid = generate_unique_oeid(used)
            used.add(oeid)
            started = time.monotonic()
            try:
                result = fn(session, entry["codes"], oeid, prev)
            except Exception as exc:
                log(f"  row {entry['row']} EXC {exc}")
                outcomes.append(False)
                continue
            took = time.monotonic() - started
            good = result.is_success and isinstance(result.value, ProgramResult)
            sid = result.value.sensor_id.hex().upper() if good else "—"
            log(
                f"  row {entry['row']:>3} {entry['make'][:14]:<14} "
                f"{'OK ' if good else 'NOK'} {took:5.1f}s id={sid} "
                f"{'' if good else (result.message or '')[:44]}"
            )
            outcomes.append(good)
            if good:
                prev = entry["codes"]
    finally:
        try:
            session.idle_board(hard=False)
        except Exception:
            pass
        ser.close()
    return outcomes


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    names = sys.argv[2:] or list(STRATEGIES)

    trio = check_hardware_trio()
    for line in trio.summary_lines():
        log(line)

    rows = load_rows(count)
    log(f"\nrows under test: {[r['row'] for r in rows]}")

    used: set[int] = set()
    for name in names:
        outcomes = run_strategy(name, rows, used)
        passed = sum(1 for o in outcomes if o)
        log(f"  -> {name}: {passed}/{len(outcomes)} programmed")
        if outcomes and all(outcomes):
            log(f"\nWINNER: {name} programmed every row")
            return 0
        time.sleep(1.0)
    log("\nNo strategy programmed every row")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
