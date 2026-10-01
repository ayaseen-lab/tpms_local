"""Shared bench loop used by the CLI and the one-click UI."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .board import BoardSession, BoardTelemetry
from .compare import best_packet, compare
from .excel_io import (
    append_manual_code_row,
    copy_workbook,
    create_blank_database,
    manual_code_present,
    needs_catalog_refresh,
    load_output,
    parse_code,
    save_workbook,
    write_row,
)
from .paths import app_root, results_dir
from .results_db import clear_all, clear_from_row, completed_rows, connect, counts, upsert
from .rtl433 import SdrCaptureResult, SdrPacket, parse_freq_hz
from .uart import default_port, open_uart

ROOT = app_root()
_RESULTS = results_dir()
SPEC_XLSX = ROOT / "data" / "Hamaton_database_20260126_1305.xlsx"
OUT_XLSX = ROOT / "data" / "TPMS_Board_Validation_Results.xlsx"
# Active workbook path for this process — may switch to a *_live_*.xlsx if Excel locks OUT_XLSX.
ACTIVE_OUT_XLSX = OUT_XLSX
DB_PATH = _RESULTS / "bench.sqlite"
IQ_DIR = _RESULTS / "iq"
PDF_PATH = _RESULTS / "TPMS_Board_Validation_Report.pdf"


def get_out_xlsx() -> Path:
    return ACTIVE_OUT_XLSX


def _set_out_xlsx(path: Path) -> None:
    global ACTIVE_OUT_XLSX
    ACTIVE_OUT_XLSX = path


@dataclass
class ManualCode:
    """Operator-entered CODE A/B/C, tested in addition to Excel rows."""

    code_a: str
    code_b: str
    code_c: str
    label: str = "Manual code"
    make: str = ""
    model: str = ""
    freq: str = ""


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
    rtl433_decoder: str = ""
    pressure: str = ""
    battery_percentage: str = ""
    rssi: str = ""
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
        skip_sdr: bool = False,
        sdr_timeout: float = 8.0,
        extra_codes: list[ManualCode] | None = None,
        on_progress: ProgressCb | None = None,
        chunk_size: int = 100,
        retest_from: int | None = None,
        require_agree: bool = True,
        agree_retries: int = 2,
        live_sdr_get: Callable | None = None,
        live_sdr_prepare: Callable[..., bool] | None = None,
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
        # 0 = run the full catalog without pausing for Comparison.
        self.chunk_size = max(0, int(chunk_size))
        self.retest_from = retest_from
        self.require_agree = require_agree
        self.agree_retries = max(1, int(agree_retries))
        self.live_sdr_get = live_sdr_get
        self.live_sdr_prepare = live_sdr_prepare
        self.on_progress = on_progress or (lambda _event: None)
        self.stop_flag = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self.session: BoardSession | None = None

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

    @staticmethod
    def _reading_decoder_label(reading) -> str:
        """Prefer rtl_433 library display label over raw decoder/model fields."""
        for attr in ("display_decoder", "decoder", "model"):
            label = str(getattr(reading, attr, None) or "").strip()
            if label:
                return label
        return ""

    @staticmethod
    def _is_rtl_library_label(label: str) -> bool:
        text = str(label or "").strip()
        low = text.lower()
        if not text or text in {"—", "-", "na", "TPMS", "tpms"}:
            return False
        if low.startswith("board rf") or "waiting for" in low:
            return False
        if low.startswith("[flex]"):
            return False
        if not (text.startswith("[") and "]" in text):
            return False
        proto = text[1 : text.index("]")].strip()
        return proto.isdigit()

    @staticmethod
    def _is_flex_label(label: str) -> bool:
        return str(label or "").strip().lower().startswith("[flex]")

    @staticmethod
    def _packet_has_actual_telemetry(packet) -> bool:
        """Require real temp + (pressure or battery) — never treat ID-only as success."""
        has_temp = getattr(packet, "temperature", None) is not None
        has_pressure = getattr(packet, "pressure", None) is not None
        batt = getattr(packet, "battery", None)
        has_battery = batt is not None and str(batt).strip() != ""
        sid = str(getattr(packet, "sensor_id", None) or "").strip()
        if not sid or sid.lower() in {"na", "n/a", "none", "-", "—"}:
            return False
        return bool(has_temp and (has_pressure or has_battery))

    def _reading_to_packet(self, reading, *, key: str = "") -> SdrPacket:
        decoder = self._reading_decoder_label(reading)
        sid = str(getattr(reading, "sensor_id", None) or key or "")
        batt = ""
        if getattr(reading, "battery_voltage_v", None) is not None:
            batt = str(reading.battery_voltage_v)
        elif getattr(reading, "battery_ok", None) is not None:
            batt = str(reading.battery_ok)
        return SdrPacket(
            protocol=decoder,
            sensor_id=sid,
            pressure=getattr(reading, "pressure_psi", None),
            temperature=getattr(reading, "temperature_c", None),
            battery=batt,
            rssi=getattr(reading, "rssi_db", None),
        )

    def _softfill_packet_from_board(self, packet: SdrPacket, tel: BoardTelemetry) -> SdrPacket:
        """Complement OE/flex RF hits with Board telemetry for ID-agreed rows."""
        pressure = packet.pressure
        if pressure is None:
            kpa = tel.pressure_kpa()
            if kpa is not None:
                pressure = float(kpa) * 0.145037737737  # kPa → PSI
        temperature = packet.temperature if packet.temperature is not None else tel.temperature_c
        battery = packet.battery
        if not battery or str(battery).strip() == "":
            if tel.battery_voltage_v is not None:
                battery = str(tel.battery_voltage_v)
            elif tel.battery_ok is not None:
                battery = str(tel.battery_ok)
        proto = packet.protocol or "[flex] OE RF"
        if self._is_flex_label(proto) and "Board soft-fill" not in proto:
            proto = f"{proto} + Board soft-fill"
        elif not self._is_flex_label(proto):
            proto = "[flex] OE RF ID + Board soft-fill"
        return SdrPacket(
            protocol=proto,
            sensor_id=packet.sensor_id or tel.sensor_id or "",
            pressure=pressure,
            temperature=temperature,
            battery=battery or "",
            rssi=packet.rssi,
        )

    def _ensure_live_sdr_ready(self, freq_hz: int, *, excel_row: int = 0) -> None:
        """Block until live rtl_433 is listening on this row's band.

        Excel catalogs often change Freq per row (315 ↔ 433). UI row_start used to
        retune asynchronously while Board ABC already ran — SDR missed the burst and
        Hamaton DB rows went NOK. Custom codes stay on one band so they never hit this.
        """
        if self.live_sdr_prepare is None or self.live_sdr_get is None:
            return
        mhz = float(freq_hz) / 1_000_000.0
        self._emit(
            ProgressEvent(
                kind="phase",
                path="wait_sdr",
                excel_row=excel_row,
                freq=f"{mhz:.2f}",
                message=f"Tuning SDR to {mhz:.2f} MHz before Board trigger…",
            )
        )
        deadline = time.monotonic() + 12.0
        while not self.stop_flag:
            try:
                ready = bool(self.live_sdr_prepare(mhz))
            except Exception:
                ready = False
            if ready:
                # Brief settle so rtl_433 is actually decoding after a retune restart.
                time.sleep(0.5)
                return
            if time.monotonic() >= deadline:
                self._emit(
                    ProgressEvent(
                        kind="comm",
                        path="sdr",
                        excel_row=excel_row,
                        message=f"SDR not ready on {mhz:.2f} MHz — continuing (may NOK)",
                    )
                )
                return
            time.sleep(0.25)

    def _live_sdr_capture(
        self,
        *,
        since: float,
        expected_id: str | None = None,
        require_telemetry: bool = True,
        allow_flex_id: bool = False,
    ) -> SdrCaptureResult:
        """Packets the live Receiver heard since this row started."""
        from .compare import ids_related

        try:
            snap = self.live_sdr_get() if self.live_sdr_get else None
        except Exception as exc:
            return SdrCaptureResult(False, [], None, str(exc))
        if not snap:
            return SdrCaptureResult(True, [], None, "SDR Receiver has no sensors yet")
        packets: list[SdrPacket] = []
        for key, reading in snap.items():
            ts = getattr(reading, "timestamp", None)
            if ts is not None:
                try:
                    if float(ts.timestamp()) < (since - 5.0):
                        continue
                except Exception:
                    pass
            decoder = self._reading_decoder_label(reading)
            is_lib = self._is_rtl_library_label(decoder)
            is_flex = self._is_flex_label(decoder)
            sid = str(getattr(reading, "sensor_id", None) or key or "")
            # Stock library always accepted. Flex only when explicitly hunting OE IDs.
            # Do NOT accept arbitrary related IDs — that false-matched Hamaton DB rows.
            if not is_lib and not (allow_flex_id and is_flex):
                continue
            if expected_id and sid and not ids_related(expected_id, sid):
                continue
            if require_telemetry and hasattr(reading, "qualifies_ok") and not reading.qualifies_ok():
                # Flex ID-only: still keep when hunting RF ID matches for soft-fill.
                if not (allow_flex_id and is_flex and sid):
                    continue
            packets.append(self._reading_to_packet(reading, key=str(key)))
        # Prefer stock library packets over flex when both exist.
        packets.sort(
            key=lambda p: (
                0 if self._is_rtl_library_label(getattr(p, "protocol", "")) else 1,
                str(getattr(p, "sensor_id", "") or ""),
            )
        )
        if require_telemetry:
            packets = [p for p in packets if self._packet_has_actual_telemetry(p)]
        if not packets:
            return SdrCaptureResult(True, [], None, "SDR heard no rtl_433 decode for this row")
        return SdrCaptureResult(True, packets, None, None)

    def _wait_live_sdr(
        self,
        *,
        since: float,
        expected_id: str | None,
        wait_s: float,
        excel_row: int,
        board_tel: BoardTelemetry | None = None,
    ) -> SdrCaptureResult:
        """After Board has a reading, poll until rtl_433 library decode or OE/flex ID match.

        Hamaton custom codes often have no stock library decoder — flex RF ID that
        matches the Board OEID is enough when Board telemetry soft-fills the row.
        """
        deadline = time.monotonic() + max(0.5, float(wait_s))
        last_emit = 0.0
        while True:
            if self.stop_flag:
                return SdrCaptureResult(True, [], None, "stopped before SDR decode")
            hit = self._live_sdr_capture(since=since, expected_id=expected_id, require_telemetry=True)
            if hit.packets:
                return hit
            soft = self._live_sdr_capture(since=since, expected_id=None, require_telemetry=True)
            if soft.packets and expected_id:
                from .compare import ids_related

                related = [p for p in soft.packets if ids_related(expected_id, p.sensor_id)]
                if related:
                    return SdrCaptureResult(True, related, None, None)
            # OE/custom path: flex (or ID-only) RF with matching Board ID.
            flex = self._live_sdr_capture(
                since=since,
                expected_id=expected_id,
                require_telemetry=False,
                allow_flex_id=True,
            )
            if flex.packets and board_tel is not None and board_tel.qualifies_ok():
                filled = [self._softfill_packet_from_board(p, board_tel) for p in flex.packets]
                filled = [p for p in filled if self._packet_has_actual_telemetry(p)]
                if filled:
                    return SdrCaptureResult(
                        True,
                        filled,
                        None,
                        "OE/flex RF ID matched Board — telemetry soft-filled from Board",
                    )
            now = time.monotonic()
            if now >= deadline:
                break
            if now - last_emit >= 1.0:
                left = max(0.0, deadline - now)
                self._emit(
                    ProgressEvent(
                        kind="comm",
                        excel_row=excel_row,
                        path="sdr",
                        message=(
                            f"Row {excel_row} Board done — waiting rtl_433 / OE RF ID "
                            f"({left:.0f}s left)…"
                        ),
                    )
                )
                last_emit = now
            time.sleep(0.2)
        # Final flex ID attempt after timeout.
        if board_tel is not None and board_tel.qualifies_ok() and expected_id:
            flex = self._live_sdr_capture(
                since=since,
                expected_id=expected_id,
                require_telemetry=False,
                allow_flex_id=True,
            )
            if flex.packets:
                filled = [self._softfill_packet_from_board(p, board_tel) for p in flex.packets]
                filled = [p for p in filled if self._packet_has_actual_telemetry(p)]
                if filled:
                    return SdrCaptureResult(
                        True,
                        filled,
                        None,
                        "OE/flex RF ID matched Board — telemetry soft-filled from Board",
                    )
        return SdrCaptureResult(
            True,
            [],
            None,
            "SDR FAIL: no rtl_433 library or matching OE/flex RF ID for this Board row",
        )

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
            source = Path(self.source_xlsx)
            force_copy = not self.resume
            if not force_copy and needs_catalog_refresh(source, OUT_XLSX):
                force_copy = True
                self._emit(
                    ProgressEvent(
                        kind="comm",
                        path="excel",
                        message=f"Results workbook was empty — copying catalog from {source.name}…",
                    )
                )
            out_path = copy_workbook(source, OUT_XLSX, force=force_copy)
        else:
            out_path = create_blank_database(OUT_XLSX)
        _set_out_xlsx(out_path)
        if out_path != OUT_XLSX:
            self._emit(
                ProgressEvent(
                    kind="comm",
                    path="excel",
                    message=(
                        f"Results Excel is locked (close it in Excel if you can). "
                        f"Writing to: {out_path.name}"
                    ),
                )
            )

        wb, ws, cols = load_output(out_path)
        # Always ensure custom CODE A/B/C rows exist — even when resume=True.
        # Previously they were only appended on !resume, so a custom-code-only
        # run left an empty workbook and failed with "No vehicle rows".
        if self.extra_codes:
            added = 0
            for extra in self.extra_codes:
                if manual_code_present(ws, cols, extra.code_a, extra.code_b, extra.code_c):
                    continue
                append_manual_code_row(
                    ws,
                    cols,
                    code_a=extra.code_a,
                    code_b=extra.code_b,
                    code_c=extra.code_c,
                    label=extra.label,
                    make=getattr(extra, "make", "") or "",
                    model=getattr(extra, "model", "") or "",
                    freq=getattr(extra, "freq", "") or "",
                )
                added += 1
            if added:
                saved = save_workbook(wb, out_path)
                if saved != out_path:
                    _set_out_xlsx(saved)
                    out_path = saved
                    self._emit(
                        ProgressEvent(
                            kind="comm",
                            path="excel",
                            message=f"Results Excel locked — switched to {saved.name}",
                        )
                    )
                self._emit(
                    ProgressEvent(
                        kind="comm",
                        path="excel",
                        message=f"Added {added} custom CODE A/B/C row(s) to results workbook",
                    )
                )
        db = connect(DB_PATH)
        if not self.resume:
            clear_all(db)
        elif self.retest_from:
            cleared = clear_from_row(db, int(self.retest_from))
            if cleared:
                self._emit(
                    ProgressEvent(
                        kind="comm",
                        path="resume",
                        message=f"Kept rows before {self.retest_from}; retesting from row {self.retest_from} ({cleared} cleared)",
                    )
                )
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
            on_phase=lambda phase, detail: self._emit(
                ProgressEvent(kind="phase", path=phase, message=detail)
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
        _ok, hw_msg = session.verify_hardware()
        if self.stop_flag:
            try:
                ser.close()
            except Exception:
                pass
            self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
            db.close()
            return 0
        session.detect_transport()
        # Chapter 4.0 Query Version (0x40) for the Board UI.
        version = None
        try:
            version = session.query_board_version()
        except Exception:
            version = None
        max_row = ws.max_row
        total_data = max(0, max_row - 1)
        pending = total_data - len(done)

        if total_data == 0:
            hint = (
                "Add custom CODE A / B / C (and optional Make / Model / Freq), "
                "or load a Hamaton Excel on the Board tab, then Run again."
            )
            if self.extra_codes:
                hint = (
                    "Custom codes were provided but no vehicle rows were written. "
                    "Reset Session, re-add CODE A / B / C, then Run again."
                )
            self._emit(
                ProgressEvent(
                    kind="error",
                    message=f"No vehicle rows in the results workbook. {hint}",
                )
            )
            try:
                ser.close()
            except Exception:
                pass
            db.close()
            return 0

        chunk_note = "full catalog" if self.chunk_size <= 0 else f"chunk {self.chunk_size}"
        version_extras: dict = {}
        version_msg = ""
        if version is not None:
            try:
                fw = int(version.software_version)
                version_extras = {
                    "firmware_version": fw,
                    "hardware_version": int(version.hardware_version),
                    "boot_version": int(version.boot_version),
                    "software_version": fw,
                    "trigger_database_version": int(version.trigger_database_version),
                    "programming_database_version": int(version.programming_database_version),
                }
                version_msg = f" · Firmware {fw}"
            except Exception:
                version_extras = {}
                version_msg = ""
        self._emit(
            ProgressEvent(
                kind="board_version",
                transport=session.transport_mode,
                message="Query Version (0x40)" + (version_msg or " · no reply"),
                extras=version_extras,
            )
        )
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
                message=(
                    f"{hw_msg} · {chunk_note} · from row {self.retest_from or 2} · "
                    f"{total_data} vehicles{version_msg}"
                ),
                extras=dict(version_extras),
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
                if self.retest_from and excel_row < int(self.retest_from):
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
                row_wall = time.time()
                # Live Receiver owns the dongle — never spawn a second rtl_433 per row.
                use_live = self.live_sdr_get is not None
                iq_path = None if (self.skip_sdr or use_live) else (IQ_DIR / f"row_{excel_row}.cu8")
                oeid = 0
                freq_hz = parse_freq_hz(freq_cell)
                tel = BoardTelemetry()
                sdr = SdrCaptureResult(False, [], None, "not run")
                values: dict = {}
                # One Board ABC program/trigger. Then wait for rtl_433 (or timeout) before
                # advancing — do not re-run ABC just because SDR missed the burst.
                if self.stop_flag:
                    stopped = True
                    break
                # Excel Freq changes must finish retuning BEFORE LF trigger.
                if use_live:
                    self._ensure_live_sdr_ready(freq_hz, excel_row=excel_row)
                    row_wall = time.time()
                if self.stop_flag:
                    stopped = True
                    break
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

                # Show Board result immediately; SDR may still be decoding.
                board_values = _telemetry_values(
                    tel,
                    SdrCaptureResult(True, [], None, "waiting for rtl_433"),
                    skip_sdr=False if use_live else self.skip_sdr,
                    duration_s=time.monotonic() - started,
                )
                self._board_partial_event(
                    excel_row,
                    total_data,
                    make,
                    model,
                    year,
                    oe,
                    supplier,
                    code_a_s,
                    code_b_s,
                    code_c_s,
                    freq_cell,
                    board_values,
                    session,
                )

                if use_live:
                    heard_sensor = bool(tel.trigger_ok or tel.read_ok)
                    if not heard_sensor:
                        sdr = SdrCaptureResult(
                            True, [], None, "SDR skipped — board heard no sensor"
                        )
                    else:
                        # Always give rtl_433 a full window after Board heard the sensor.
                        # Custom-code rows were getting cut to 2s when ID/telemetry lagged.
                        wait_s = max(6.0, float(self.sdr_timeout))
                        if not (tel.sensor_id or "").strip():
                            wait_s = min(wait_s, 4.0)
                        self._emit(
                            ProgressEvent(
                                kind="phase",
                                path="wait_sdr",
                                excel_row=excel_row,
                                sensor_id=str(tel.sensor_id or ""),
                                code_a=code_a_s,
                                code_b=code_b_s,
                                code_c=code_c_s,
                                make=make,
                                model=model,
                                freq=freq_cell,
                                message=f"Waiting up to {wait_s:.0f}s for rtl_433 on {freq_cell or 'SDR band'}…",
                            )
                        )
                        sdr = self._wait_live_sdr(
                            since=row_wall,
                            expected_id=tel.sensor_id,
                            wait_s=wait_s,
                            excel_row=excel_row,
                            board_tel=tel,
                        )
                elif not self.skip_sdr:
                    # Per-row rtl_433 already finished inside run_row.
                    pass
                else:
                    sdr = SdrCaptureResult(False, [], None, "SDR skipped")

                if self.stop_flag:
                    stopped = True
                    self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
                    break

                elapsed = time.monotonic() - started
                values = _telemetry_values(
                    tel,
                    sdr,
                    skip_sdr=False if (use_live or not self.skip_sdr) else True,
                    duration_s=elapsed,
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
                if not tel.qualifies_ok():
                    try:
                        session.recover_link(code_a, code_b, code_c)
                    except Exception:
                        pass
                if self.chunk_size and processed > 0 and processed % self.chunk_size == 0:
                    self._emit(
                        ProgressEvent(
                            kind="chunk_complete",
                            excel_row=excel_row,
                            total=total_data,
                            done=counts(db)["done"],
                            ok=counts(db)["OK"],
                            nok=counts(db)["NOK"],
                            message=f"Chunk of {self.chunk_size} rows done — review Comparison",
                        )
                    )
                    self.pause()
        finally:
            try:
                ser.close()
            except Exception:
                pass
            try:
                saved = save_workbook(wb, get_out_xlsx())
                _set_out_xlsx(saved)
            except Exception:
                pass
            db.close()
            if not stopped and self.stop_flag:
                self._emit(ProgressEvent(kind="stopped", message="Stopped by operator"))
            elif not stopped and not self.stop_flag:
                self._emit(ProgressEvent(kind="finished", message="All vehicles tested"))
        return 0

    def _board_partial_event(
        self,
        excel_row: int,
        total: int,
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
    ) -> None:
        """Publish Board ABC result immediately while SDR is still trying to decode."""
        self._emit(
            ProgressEvent(
                kind="board_ok",
                excel_row=excel_row,
                total=total,
                make=make,
                model=model,
                year=year,
                oe=oe,
                supplier=supplier,
                code_a=code_a,
                code_b=code_b,
                code_c=code_c,
                freq=freq,
                performance=str(values.get("Board performance") or ""),
                reason=str(values.get("NOK reason") or ""),
                sensor_id=str(values.get("Sensor ID") or ""),
                temperature=str(values.get("Temperature") or ""),
                voltage=str(values.get("Baterry voltage") or ""),
                transport=session.transport_mode,
                path=session.last_path,
                message="Board result ready — waiting for rtl_433 decode…",
                sdr_compare="pending",
                sdr_reason="waiting for rtl_433",
                rtl433_decoder="rtl_433 · waiting for decode",
                pressure=str(values.get("Pressure") or ""),
                battery_percentage=str(values.get("Battery percentage") or ""),
                rssi=str(values.get("RSSI") or ""),
            )
        )

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
                rtl433_decoder=str(values.get("rtl_433 Decoder") or ""),
                pressure=str(values.get("Pressure") or ""),
                battery_percentage=str(values.get("Battery percentage") or ""),
                rssi=str(values.get("RSSI") or ""),
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
    # Keep OE/flex catch-all labels intact (do not remap via stock catalog).
    if label.lower().startswith("[flex]"):
        return label
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
        "RSSI": "na",
        "Duration s": "na",
    }


def _telemetry_values(
    tel: BoardTelemetry,
    sdr: SdrCaptureResult | None = None,
    *,
    skip_sdr: bool = False,
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
    batt_pct = tel.battery_percentage_export()
    batt_v = tel.battery_display()
    # Keep dedicated voltage column numeric when we have volts; otherwise mirror display.
    if tel.battery_voltage_v is not None:
        batt_v_col = f"{tel.battery_voltage_v:.3f}"
    else:
        batt_v_col = batt_v
    return {
        "Board performance": "OK" if ok else "NOK",
        "NOK reason": note,
        "Battery percentage": batt_pct,
        "Baterry voltage": batt_v_col,
        "SDR compare": sdr_compare,
        "SDR reason": sdr_reason,
        "rtl_433 Decoder": decoder,
        "IQ file": iq_file,
        "Sensor ID": na(tel.sensor_id),
        "Frequency": na(tel.frequency_mhz),
        "Pressure": tel.pressure_display(),
        "Temperature": na(tel.temperature_c),
        "RSSI": _rssi_export(tel, sdr),
        "Duration s": "na" if duration_s is None else f"{duration_s:.1f}",
    }


def _rssi_export(tel: BoardTelemetry, sdr: SdrCaptureResult | None) -> str:
    parts: list[str] = []
    board = tel.rssi_display()
    if board != "na":
        parts.append(f"board {board}")
    sdr_rssi = None
    if sdr is not None:
        for packet in sdr.packets or []:
            raw = getattr(packet, "rssi", None)
            if raw is not None:
                try:
                    sdr_rssi = float(raw)
                    break
                except (TypeError, ValueError):
                    pass
            blob = getattr(packet, "raw_json", None) or {}
            if isinstance(blob, dict):
                for key in ("rssi", "RSSI", "rssi_db"):
                    if blob.get(key) in (None, ""):
                        continue
                    try:
                        sdr_rssi = float(blob[key])
                        break
                    except (TypeError, ValueError):
                        continue
                if sdr_rssi is not None:
                    break
    if sdr_rssi is not None:
        parts.append(f"{sdr_rssi:.1f} dB SDR")
    return " · ".join(parts) if parts else "na"


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
            "rssi": values.get("RSSI", "na"),
            "duration_s": values.get("Duration s", "na"),
        }
    )
    upsert(db, record)
    saved = save_workbook(wb, get_out_xlsx())
    _set_out_xlsx(saved)
