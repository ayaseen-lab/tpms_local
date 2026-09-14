"""Shared bench loop used by the CLI and the one-click UI."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .board import BoardSession, BoardTelemetry, generate_unique_oeid
from .compare import best_packet, compare
from .excel_io import append_manual_code_row, copy_workbook, create_blank_database, load_output, parse_code, write_row
from .paths import app_root, results_dir
from .results_db import clear_all, completed_rows, connect, counts, upsert
from .rtl433 import SdrCaptureResult, parse_freq_hz
from .uart import default_port, open_uart

ROOT = app_root()
_RESULTS = results_dir()
SPEC_XLSX = ROOT / "docs" / "specifications" / "Hamaton_database_20260126_1305.xlsx"
OUT_XLSX = _RESULTS / "TPMS_Board_Validation_Results.xlsx"
DB_PATH = _RESULTS / "bench.sqlite"
IQ_DIR = _RESULTS / "iq"
PDF_PATH = _RESULTS / "TPMS_Board_Validation_Report.pdf"


@dataclass
class ManualCode:
    """Operator-entered CODE A/B/C, tested in addition to Excel rows."""

    code_a: str
    code_b: str
    code_c: str
    label: str = "Manual code"


@dataclass
class ProgressEvent:
    kind: str
    excel_row: int = 0
    total: int = 0
    pending: int = 0
    done: int = 0
    ok: int = 0
    nok: int = 0
    skip: int = 0
    make: str = ""
    model: str = ""
    year: str = ""
    oe: str = ""
    supplier: str = ""
    code_a: str = ""
    code_b: str = ""
    code_c: str = ""
    freq: str = ""
    performance: str = ""
    reason: str = ""
    sensor_id: str = ""
    temperature: str = ""
    voltage: str = ""
    transport: str = ""
    path: str = ""
    message: str = ""
    sdr_compare: str = ""
    sdr_reason: str = ""
    pressure: str = ""
    battery_percentage: str = ""
    duration_s: float | None = None
    extras: dict = field(default_factory=dict)


ProgressCb = Callable[[ProgressEvent], None]


def na(value) -> str:
    return "na" if value is None or value == "" else str(value)


class BenchRunner:
    def __init__(
        self,
        port: str | None = None,
        source_xlsx: Path | None = None,
        resume: bool = True,
        skip_sdr: bool = True,
        sdr_timeout: float = 15.0,
        extra_codes: list[ManualCode] | None = None,
        on_progress: ProgressCb | None = None,
    ) -> None:
        self.port = port or default_port()
        self.extra_codes = extra_codes or []
        if source_xlsx is not None:
            self.source_xlsx = source_xlsx
        elif SPEC_XLSX.exists() and not self.extra_codes:
            self.source_xlsx = SPEC_XLSX
        else:
            self.source_xlsx = None
        self.resume = resume
        self.skip_sdr = skip_sdr
        self.sdr_timeout = sdr_timeout
        self.on_progress = on_progress or (lambda _event: None)
        self.stop_flag = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self.session: BoardSession | None = None
        self._used_oeids: set[int] = set()

    def pause(self) -> None:
        """Pause the bench loop between rows."""
        self._pause_event.clear()
        self._emit(ProgressEvent(kind="paused", message="Test paused"))

    def resume_run(self) -> None:
        """Resume the bench loop."""
        self._pause_event.set()
        self._emit(ProgressEvent(kind="resumed", message="Test resumed"))

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def request_stop(self) -> None:
        self.stop_flag = True
        self._pause_event.set()
        self._emit(ProgressEvent(kind="stopping", message="Stopping test..."))
        session = self.session
        if session is not None:
            try:
                session.abort()
            except Exception:
                pass

    def _emit(self, event: ProgressEvent) -> None:
        self.on_progress(event)

    def _open_uart_interruptible(self):
        """Open COM without blocking Stop forever when the port hangs."""
        result: list = []
        error: list[BaseException] = []

        def _open() -> None:
            try:
                result.append(open_uart(self.port))
            except BaseException as exc:  # noqa: BLE001 — surface to caller
                error.append(exc)

        opener = threading.Thread(target=_open, daemon=True, name="open-uart")
        opener.start()
        while opener.is_alive():
            if self.stop_flag:
                raise RuntimeError(f"Stopped while opening {self.port}")
            opener.join(0.15)
        if error:
            raise error[0]
        if not result:
            raise RuntimeError(f"Could not open serial port {self.port}")
        return result[0]

    def run(self) -> int:
        has_excel = bool(self.source_xlsx and Path(self.source_xlsx).exists())
        if not has_excel and not self.extra_codes:
            raise FileNotFoundError("Select an Excel database or enter custom CODE A / B / C.")

        if has_excel:
            copy_workbook(Path(self.source_xlsx), OUT_XLSX, force=not self.resume)
        else:
            create_blank_database(OUT_XLSX)

        wb, ws, cols = load_output(OUT_XLSX)
        if self.extra_codes and not self.resume:
            for extra in self.extra_codes:
                append_manual_code_row(
                    ws,
                    cols,
                    code_a=extra.code_a,
                    code_b=extra.code_b,
                    code_c=extra.code_c,
                    label=extra.label,
                )
            wb.save(OUT_XLSX)
        db = connect(DB_PATH)
        if not self.resume:
            clear_all(db)
        done = completed_rows(db) if self.resume else set()
        stats = counts(db)
        if self.stop_flag:
            self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
            db.close()
            return 0
        ser = self._open_uart_interruptible()
        session = BoardSession(
            ser,
            on_comm=lambda channel, detail: self._emit(
                ProgressEvent(kind="comm", path=channel, message=detail)
            ),
        )
        session.set_stop_check(lambda: self.stop_flag)
        self.session = session
        if self.stop_flag:
            try:
                ser.close()
            except Exception:
                pass
            self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
            db.close()
            return 0
        ok, hw_msg = session.verify_hardware()
        if self.stop_flag or hw_msg == "stopped":
            try:
                ser.close()
            except Exception:
                pass
            self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
            db.close()
            return 0
        if not ok:
            try:
                ser.close()
            except Exception:
                pass
            raise RuntimeError(f"Hardware check failed: {hw_msg}")
        session.detect_transport()
        max_row = ws.max_row
        total_data = max(0, max_row - 1)
        pending = total_data - len(done)

        self._emit(
            ProgressEvent(
                kind="started",
                total=total_data,
                pending=pending,
                done=stats["done"],
                ok=stats["OK"],
                nok=stats["NOK"],
                skip=stats["SKIP"],
                transport=session.transport_mode,
                message=f"Hardware OK · {hw_msg} · {total_data} vehicles loaded",
            )
        )

        processed = 0
        stopped = False
        try:
            for excel_row in range(2, max_row + 1):
                if self.stop_flag:
                    stopped = True
                    self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
                    break

                while not self._pause_event.is_set():
                    if self.stop_flag:
                        break
                    time.sleep(0.1)

                if self.stop_flag:
                    stopped = True
                    self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
                    break

                if excel_row in done:
                    continue

                make = str(ws.cell(excel_row, cols.get("Make", 1)).value or "")
                model = str(ws.cell(excel_row, cols.get("Model", 2)).value or "")
                year = str(ws.cell(excel_row, cols.get("Year From", 3)).value or "")
                supplier = str(ws.cell(excel_row, cols.get("OE supplier", 8)).value or "").strip()
                oe = str(ws.cell(excel_row, cols.get("OE Number", 9)).value or "")
                freq_cell = str(ws.cell(excel_row, cols.get("Freq", 10)).value or "")
                code_a = parse_code(ws.cell(excel_row, cols.get("CODEA", 16)).value)
                code_b = parse_code(ws.cell(excel_row, cols.get("CODEB", 17)).value)
                code_c = parse_code(ws.cell(excel_row, cols.get("CODEC", 18)).value)
                code_a_s = "" if code_a is None else f"{code_a:08X}"
                code_b_s = "" if code_b is None else f"{code_b:08X}"
                code_c_s = "" if code_c is None else f"{code_c:08X}"

                stats = counts(db)
                pending_now = total_data - stats["done"]
                self._emit(
                    ProgressEvent(
                        kind="row_start",
                        excel_row=excel_row,
                        total=total_data,
                        pending=pending_now,
                        done=stats["done"],
                        ok=stats["OK"],
                        nok=stats["NOK"],
                        skip=stats["SKIP"],
                        make=make,
                        model=model,
                        year=year,
                        oe=oe,
                        supplier=supplier,
                        code_a=code_a_s,
                        code_b=code_b_s,
                        code_c=code_c_s,
                        freq=freq_cell,
                        message=f"Testing {make} {model}",
                    )
                )

                record = {
                    "excel_row": excel_row,
                    "make": make,
                    "model": model,
                    "oe": oe,
                    "supplier": supplier,
                    "code_a": code_a_s,
                    "code_b": code_b_s,
                    "code_c": code_c_s,
                }

                if None in (code_a, code_b, code_c):
                    values = _blank_result("NOK", "missing CODEA/CODEB/CODEC")
                    values["Duration s"] = "0"
                    _commit(ws, cols, excel_row, values, record, db, wb)
                    self._result_event(
                        excel_row, total_data, db, make, model, year, oe, supplier,
                        code_a_s, code_b_s, code_c_s, freq_cell, values, session,
                        duration_s=0.0,
                    )
                    processed += 1
                    continue

                started = time.monotonic()
                iq_path = None if self.skip_sdr else (IQ_DIR / f"row_{excel_row}.cu8")
                oeid = generate_unique_oeid(self._used_oeids)
                freq_hz = parse_freq_hz(freq_cell)
                tel, sdr = session.run_row(
                    code_a,
                    code_b,
                    code_c,
                    oeid=oeid,
                    iq_path=iq_path,
                    sdr_duration=self.sdr_timeout,
                    frequency_hz=freq_hz,
                )
                if self.stop_flag or "stopped" in (tel.reasons or []):
                    stopped = True
                    self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
                    break
                elapsed = time.monotonic() - started
                values = _telemetry_values(
                    tel, sdr, skip_sdr=self.skip_sdr, duration_s=elapsed
                )
                _commit(ws, cols, excel_row, values, record, db, wb)
                self._result_event(
                    excel_row,
                    total_data,
                    db,
                    make,
                    model,
                    year,
                    oe,
                    supplier,
                    code_a_s,
                    code_b_s,
                    code_c_s,
                    freq_cell,
                    values,
                    session,
                    extra=str(values.get("NOK reason") or f"{elapsed:.0f}s"),
                    duration_s=elapsed,
                )
                processed += 1
        finally:
            try:
                ser.close()
            except Exception:
                pass
            try:
                wb.save(OUT_XLSX)
            except Exception:
                pass
            db.close()
            if not stopped and self.stop_flag:
                self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
            elif not stopped and not self.stop_flag:
                self._emit(ProgressEvent(kind="finished", message="All vehicles tested"))
        return 0

    def _result_event(
        self,
        excel_row: int,
        total: int,
        db,
        make: str,
        model: str,
        year: str,
        oe: str,
        supplier: str,
        code_a: str,
        code_b: str,
        code_c: str,
        freq: str,
        values: dict,
        session: BoardSession,
        extra: str = "",
        duration_s: float | None = None,
    ) -> None:
        stats = counts(db)
        if duration_s is None:
            raw = values.get("Duration s")
            try:
                duration_s = float(raw) if raw not in (None, "", "na") else None
            except (TypeError, ValueError):
                duration_s = None
        self._emit(
            ProgressEvent(
                kind="row_done",
                excel_row=excel_row,
                total=total,
                pending=max(0, total - stats["done"]),
                done=stats["done"],
                ok=stats["OK"],
                nok=stats["NOK"],
                skip=stats["SKIP"],
                make=make,
                model=model,
                year=year,
                oe=oe,
                supplier=supplier,
                code_a=code_a,
                code_b=code_b,
                code_c=code_c,
                freq=freq,
                performance=str(values["Board performance"]),
                reason=str(values.get("NOK reason") or ""),
                sensor_id=str(values.get("Sensor ID") or ""),
                temperature=str(values.get("Temperature") or ""),
                voltage=str(values.get("Baterry voltage") or ""),
                transport=session.transport_mode,
                path=session.last_path,
                message=extra,
                sdr_compare=str(values.get("SDR compare") or ""),
                sdr_reason=str(values.get("SDR reason") or ""),
                pressure=str(values.get("Pressure") or ""),
                battery_percentage=str(values.get("Battery percentage") or ""),
                duration_s=duration_s,
            )
        )


def reset_session_db() -> None:
    """Clear persisted results for a fresh session."""
    db = connect(DB_PATH)
    clear_all(db)
    db.close()


def _decoder_from_sdr(sdr: SdrCaptureResult | None, sensor_id: str | None) -> str:
    if sdr is None or not sdr.packets:
        return "na"
    packet = best_packet(sdr, sensor_id)
    if packet is None:
        return "na"
    label = (packet.protocol or "").strip()
    if not label:
        return "na"
    # Enrich short labels like "[123] Jansite" using the rtl_433 library catalog.
    try:
        from config import format_rtl433_decoder
        import re

        match = re.match(r"\[(\d+)\]\s*(.*)", label)
        if match:
            return format_rtl433_decoder(int(match.group(1)), match.group(2) or None)
        return format_rtl433_decoder(None, label)
    except Exception:
        return label


def _blank_result(performance: str, reason: str) -> dict:
    return {
        "Board performance": performance,
        "NOK reason": reason,
        "Battery percentage": "na",
        "Baterry voltage": "na",
        "SDR compare": "na",
        "SDR reason": "na",
        "rtl_433 Decoder": "na",
        "IQ file": "na",
        "Sensor ID": "na",
        "Frequency": "na",
        "Pressure": "na",
        "Temperature": "na",
        "Duration s": "na",
    }


def _telemetry_values(
    tel: BoardTelemetry,
    sdr: SdrCaptureResult | None = None,
    *,
    skip_sdr: bool = True,
    duration_s: float | None = None,
) -> dict:
    ok = tel.qualifies_ok()
    if skip_sdr or sdr is None:
        sdr_compare, sdr_reason, iq_file = "na", "SDR skipped", "na"
        decoder = "na"
    else:
        sdr_compare, sdr_reason = compare(tel, sdr)
        iq_file = na(sdr.iq_path)
        decoder = _decoder_from_sdr(sdr, tel.sensor_id)
        if sdr.iq_path and (not sdr.packets) and sdr.error:
            # Keep the IQ path visible in the SDR reason for offline replay.
            if sdr.iq_path not in (sdr_reason or ""):
                sdr_reason = f"{sdr_reason}; IQ {sdr.iq_path}".strip("; ")
    note = tel.status_note(duration_s)
    return {
        "Board performance": "OK" if ok else "NOK",
        "NOK reason": note,
        "Battery percentage": na(tel.battery_percentage),
        "Baterry voltage": "na" if tel.battery_voltage_v is None else f"{tel.battery_voltage_v:.3f}",
        "SDR compare": sdr_compare,
        "SDR reason": sdr_reason,
        "rtl_433 Decoder": decoder,
        "IQ file": iq_file,
        "Sensor ID": na(tel.sensor_id),
        "Frequency": na(tel.frequency_mhz),
        "Pressure": na(tel.pressure_raw),
        "Temperature": na(tel.temperature_c),
        "Duration s": "na" if duration_s is None else f"{duration_s:.1f}",
    }


def _commit(ws, cols, excel_row, values, record, db, wb) -> None:
    write_row(ws, cols, excel_row, values)
    record.update(
        {
            "board_performance": values["Board performance"],
            "nok_reason": values["NOK reason"],
            "battery_percentage": values["Battery percentage"],
            "battery_voltage": values["Baterry voltage"],
            "sdr_compare": values["SDR compare"],
            "sdr_reason": values["SDR reason"],
            "rtl433_decoder": values.get("rtl_433 Decoder", "na"),
            "iq_file": values["IQ file"],
            "sensor_id": values["Sensor ID"],
            "frequency": values["Frequency"],
            "pressure": values["Pressure"],
            "temperature": values["Temperature"],
            "duration_s": values.get("Duration s", "na"),
        }
    )
    upsert(db, record)
    wb.save(OUT_XLSX)
