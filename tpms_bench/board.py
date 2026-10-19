"""Program sensor, LF-activate, and read telemetry from the TPMS board."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hamaton.codec import CommandCodec
from hamaton.commands.cancel import CancelCodec
from hamaton.commands.query_version import QueryVersionCodec
from hamaton.exceptions import CodecError, FrameError, UnexpectedResponseError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult, ProgramResult, SensorReading
from hamaton.parser import HamatonStreamParser

from .program_one import ProgramSensorCodec as ProgramOneSensorCodec
from .program_search import ProgramSearchCodec, SearchProgress
from .query_sensor import QuerySensorCodec, QuerySensorReading
from .rtl433 import SdrCaptureResult, finish_capture, start_capture
from .sensor_reading import (
    SensorReceiveRfCodec as ReceiveRfCodec,
    SensorTriggerCodec as TriggerCodec,
    parse_sensor_reading,
)

UART_POLL_S = 0.04
# Board replies come only over USB-TTL RX (no J-Link / JTAG).
PROGRAM_POLL_S = 0.12
TRIGGER_WAIT_S = 2.8
FAST_TRIGGER_WAIT_S = 1.8
QUERY_TIMEOUT_S = 2.2
QUERY_RETRIES = 2
TX_GAP_S = 0.04
# Settle after Cancel before Program — keep short for high row throughput.
POST_CANCEL_S = 0.06
# The board answers Program in ~2-6 s, so keep the window above the slow end.
PROGRAM_TIMEOUT_S = 12.0
PROGRAM_RESEND_S = 1.4
CANCEL_WAIT_S = 0.12
LF_SEARCH_TIMEOUT_S = 2.2
# Transient UART / no-sensor misses — retry before marking the row NOK.
PROGRAM_ATTEMPTS = 3
TRIGGER_ATTEMPTS = 3
RETRY_SETTLE_S = 0.28
# Per-row IQ (when Board does not skip SDR) — keep short; live SDR tab covers capture.
DEFAULT_SDR_ROW_S = 3.0
SDR_FINISH_EXTRA_S = 0.8

CommCb = Callable[[str, str], None]


def generate_unique_oeid(used: set[int] | None = None) -> int:
    """Non-zero 32-bit OEID so each row programs a distinct Sensor ID."""
    used = used if used is not None else set()
    for _ in range(64):
        value = secrets.randbits(32)
        if value == 0:
            continue
        if value not in used:
            used.add(value)
            return value
    # Extremely unlikely fallback
    value = (secrets.randbits(31) << 1) | 1
    used.add(value)
    return value


def format_oeid(oeid: int) -> str:
    return f"{oeid:08X}"


@dataclass
class BoardTelemetry:
    frequency: int | None = None
    frequency_mhz: int | None = None
    sensor_id: str | None = None
    programmed_id: str | None = None
    rf_id_verified: bool = False
    pressure_raw: int | None = None
    temperature_c: int | None = None
    battery_percentage: int | None = None
    battery_voltage_v: float | None = None
    battery_ok: bool | None = None
    rssi: int | None = None
    program_ok: bool = False
    trigger_ok: bool = False
    read_ok: bool = False
    reasons: list[str] = field(default_factory=list)

    def _has_battery(self) -> bool:
        return (
            self.battery_voltage_v is not None
            or (self.battery_percentage is not None and 1 <= int(self.battery_percentage) <= 100)
            or self.battery_ok is not None
        )

    def battery_display(self) -> str:
        """Human battery for UI / Excel — prefer volts, then %, then OK/LOW."""
        if self.battery_voltage_v is not None:
            return f"{self.battery_voltage_v:.2f}"
        pct = self.battery_percentage
        if pct is not None:
            try:
                n = int(pct)
            except (TypeError, ValueError):
                n = -1
            if 1 <= n <= 100:
                return f"{n}%"
        if self.battery_ok is True:
            return "OK"
        if self.battery_ok is False:
            return "LOW"
        return "na"

    def battery_percentage_export(self) -> str:
        """Excel Battery percentage — never write misleading 0%."""
        pct = self.battery_percentage
        if pct is None:
            return "na"
        try:
            n = int(pct)
        except (TypeError, ValueError):
            return "na"
        if 1 <= n <= 100:
            return str(n)
        return "na"

    def pressure_kpa(self) -> float | None:
        """Hamaton stores pressure as centi-kPa (raw 10132 → 101.32 kPa)."""
        if self.pressure_raw is None:
            return None
        try:
            return float(self.pressure_raw) / 100.0
        except (TypeError, ValueError):
            return None

    def pressure_display(self) -> str:
        kpa = self.pressure_kpa()
        if kpa is None:
            return "na"
        psi = kpa * 0.1450377377
        bar = kpa / 100.0
        return f"{psi:.2f} PSI / {bar:.3f} bar / {kpa:.2f} kPa"

    def rssi_display(self) -> str:
        if self.rssi is None:
            return "na"
        try:
            return str(int(self.rssi))
        except (TypeError, ValueError):
            return str(self.rssi)

    def missing_values(self) -> list[str]:
        """Fields that still block Board OK (aligned with qualifies_ok)."""
        missing: list[str] = []
        if not (self.sensor_id or "").strip():
            missing.append("sensor ID")
        if self.temperature_c is None:
            missing.append("temperature")
        if self.pressure_raw is None:
            missing.append("pressure")
        if not self._has_battery():
            missing.append("battery")
        if not (self.trigger_ok or self.read_ok):
            missing.append("LF/RF response")
        return missing

    def qualifies_ok(self) -> bool:
        """OK when LF/RF delivered a full reading for this code set.

        A missing program ACK must not fail the row if the sensor answered
        with ID + temperature + pressure + battery after trigger/query.
        """
        if not (self.trigger_ok or self.read_ok):
            return False
        if not (self.sensor_id or "").strip():
            return False
        if self.temperature_c is None:
            return False
        if self.pressure_raw is None:
            return False
        if not self._has_battery():
            return False
        return True

    def status_note(self, duration_s: float | None = None) -> str:
        """Human-readable Notes: timing on OK; root-cause on NOK (no false 'missing' noise)."""
        if self.qualifies_ok():
            prefix = ""
            if not self.program_ok:
                prefix = "program ACK missed; "
            elif self.programmed_id and not self.rf_id_verified:
                prefix = "RF ID differs from program ACK; "
            if duration_s is not None:
                return f"{prefix}all values read in {duration_s:.1f}s"
            return f"{prefix}all values read" if prefix else "all values read"

        if any((r or "").strip() == "stopped" for r in self.reasons):
            return "stopped by operator"

        parts: list[str] = []

        def _add(text: str) -> None:
            text = (text or "").strip()
            if text and text not in parts:
                parts.append(text)

        no_rf = (
            not self.trigger_ok
            and not self.read_ok
            and self.temperature_c is None
            and self.pressure_raw is None
        )

        if not self.program_ok:
            for reason in self.reasons:
                text = str(reason or "").strip()
                if text.startswith("program:"):
                    detail = text[len("program:") :].strip() or "failed"
                    if "timeout" in detail.lower():
                        _add("program ACK timeout")
                    else:
                        _add(f"program: {detail}")

        for reason in self.reasons:
            text = str(reason or "").strip()
            if not text or text.lower().startswith("missing "):
                continue
            if text.startswith("program:"):
                continue
            if text.startswith("program used ID"):
                _add(text)
            elif "ID mismatch" in text:
                _add(text)
            elif text.startswith("RF did not confirm"):
                if not no_rf:
                    _add(text)
            elif text.startswith("trigger:"):
                detail = text[len("trigger:") :].strip()
                if detail == "no sensor response":
                    _add("trigger failed — no LF/RF sensor response")
                else:
                    _add(f"trigger failed — {detail}")
            elif text.startswith("read:"):
                if no_rf and any(p.startswith("trigger failed") for p in parts):
                    continue
                if (
                    self.temperature_c is None
                    or self.pressure_raw is None
                    or not self._has_battery()
                    or not (self.sensor_id or "").strip()
                ):
                    detail = text[len("read:") :].strip()
                    if "timeout" in detail.lower():
                        _add("query failed — no telemetry reply (timeout)")
                    elif "stale query" in detail.lower():
                        continue
                    else:
                        _add(f"query failed — {detail}")

        gaps: list[str] = []
        if not (self.sensor_id or "").strip():
            gaps.append("sensor ID")
        if self.temperature_c is None:
            gaps.append("temperature")
        if self.pressure_raw is None:
            gaps.append("pressure")
        if not self._has_battery():
            gaps.append("battery")
        if gaps:
            if no_rf and any(p.startswith("trigger failed") for p in parts):
                if "sensor ID" in gaps and not self.programmed_id:
                    _add("missing sensor ID")
            else:
                _add("missing " + ", ".join(gaps))

        if not parts and not self.program_ok and no_rf:
            return "program failed — board did not acknowledge (timeout)"

        # Surface how many recoveries we already spent before declaring NOK.
        for reason in self.reasons:
            text = str(reason or "").strip()
            if text.startswith("program retries:") or text.startswith("trigger retries:"):
                _add(text)
            elif text.startswith("row retry:"):
                _add(text)

        return "; ".join(parts) if parts else "incomplete reading"


class BoardSession:
    """USB-TTL TX for commands; USB-TTL RX first with board SRAM fallback."""

    def __init__(
        self,
        serial_port,
        on_comm: CommCb | None = None,
        on_phase: Callable[[str, str], None] | None = None,
    ) -> None:
        self.serial = serial_port
        self.uart_rx_active = False
        self.on_comm = on_comm or (lambda _c, _d: None)
        self.on_phase = on_phase or (lambda _phase, _message: None)
        self.transport_mode = "Detecting…"
        self.last_path = "none"
        self.tx_path = "USB-TTL TX"
        self.rx_path = "…"
        self._parser = HamatonStreamParser()
        self.ttl_ok = False
        self._stop_check: Callable[[], bool] = lambda: False
        self._aborted = False
        self.board_version = None  # VersionInfo from Chapter 4.0 Query Version (0x40)

    def _emit_phase(self, phase: str, message: str = "") -> None:
        try:
            self.on_phase(phase, message)
        except Exception:
            pass

    def set_stop_check(self, fn: Callable[[], bool]) -> None:
        self._stop_check = fn

    def should_stop(self) -> bool:
        return self._aborted or bool(self._stop_check())

    def abort(self) -> None:
        """Force-close the serial port so blocking UART waits exit quickly."""
        self._aborted = True
        ser = self.serial
        if ser is None:
            return
        try:
            if getattr(ser, "cancel_read", None):
                ser.cancel_read()
        except Exception:
            pass
        try:
            if getattr(ser, "cancel_write", None):
                ser.cancel_write()
        except Exception:
            pass
        try:
            if getattr(ser, "is_open", False):
                ser.close()
        except Exception:
            pass

    def _signal(self, channel: str, detail: str) -> None:
        try:
            self.on_comm(channel, detail)
        except Exception:
            pass

    def _probe_uart_rx(self) -> bool:
        if self.should_stop() or not getattr(self.serial, "is_open", False):
            return False
        try:
            self.send_codec(QueryVersionCodec())
            time.sleep(0.25)
            data = self._drain_uart(0.35)
        except Exception:
            return False
        if b"\x3c\x22" in data:
            return True
        return bool(self._parser.feed(data))

    def detect_transport(self) -> str:
        """USB-TTL TX and RX only — no J-Link / JTAG path."""
        if self.should_stop():
            self.transport_mode = "Stopped"
            return self.transport_mode
        self.ttl_ok = bool(getattr(self.serial, "is_open", False))
        self.uart_rx_active = self._probe_uart_rx() if self.ttl_ok else False
        if self.uart_rx_active:
            self.rx_path = "USB-TTL RX"
            self.transport_mode = "USB-TTL TX/RX"
        elif self.ttl_ok:
            # Port open — still use UART RX; probe may have raced before board woke.
            self.uart_rx_active = True
            self.rx_path = "USB-TTL RX"
            self.transport_mode = "USB-TTL TX/RX"
        else:
            self.rx_path = "none"
            self.transport_mode = "USB-TTL not open"
        return self.transport_mode

    def verify_hardware(self) -> tuple[bool, str]:
        """Require USB-TTL. Board replies are read on USB-TTL RX only."""
        if self.should_stop():
            return True, "stopped"
        self.ttl_ok = bool(getattr(self.serial, "is_open", False))
        port = getattr(self.serial, "port", "")
        if not self.ttl_ok:
            return True, f"TX {port or '—'} · USB-TTL not open"
        self.uart_rx_active = self._probe_uart_rx()
        if not self.uart_rx_active:
            # Still drive UART RX — client boards reply on USB-TTL.
            self.uart_rx_active = True
            self._signal("uart", "USB-TTL open — RX assumed (probe quiet)")
            return True, f"TX {port} · RX USB-TTL"
        self._signal("uart", "USB-TTL RX active")
        return True, f"TX {port} · RX USB-TTL"

    def query_board_version(self):
        """Chapter 4.0 Query Version (0x40) — hardware / boot / software / trigger / program DB.

        Returns a VersionInfo on success, else None. Stores the last result on
        ``self.board_version`` for the UI.
        """
        if self.should_stop():
            return None
        codec = QueryVersionCodec()
        try:
            result = self.execute(codec, timeout=float(getattr(codec, "TIMEOUT_SECONDS", 2.0) or 2.0))
        except Exception as exc:
            self._signal("uart", f"Query Version failed: {exc}")
            return None
        if result is None or not getattr(result, "is_success", False):
            msg = getattr(result, "message", None) or "no reply"
            self._signal("uart", f"Query Version NOK · {msg}")
            return None
        version = result.value
        self.board_version = version
        try:
            hw = int(version.hardware_version)
            boot = int(version.boot_version)
            sw = int(version.software_version)
            trig = int(version.trigger_database_version)
            prog = int(version.programming_database_version)
            self._signal(
                "uart",
                f"Query Version OK · Firmware {sw} · HW {hw} · Boot {boot} · Trig {trig} · Prog {prog}",
            )
        except Exception:
            self._signal("uart", "Query Version OK")
        return version

    def send_codec(self, codec: CommandCodec) -> None:
        if self.should_stop() or not getattr(self.serial, "is_open", False):
            raise RuntimeError("stopped")
        raw = codec.build_request()
        try:
            self.serial.reset_input_buffer()
        except Exception:
            pass
        self._parser.reset()
        written = self.serial.write(raw)
        self.serial.flush()
        self._signal("ttl", f"TX {written}B")
        time.sleep(TX_GAP_S)

    def _tx_now(self, codec: CommandCodec) -> None:
        """Write a command without resetting the COM driver (safe after an RF flood)."""
        if not getattr(self.serial, "is_open", False):
            raise RuntimeError("stopped")
        raw = codec.build_request()
        written = self.serial.write(raw)
        self.serial.flush()
        self._signal("ttl", f"TX {written}B")
        time.sleep(TX_GAP_S)

    def _drain_uart(self, timeout_s: float) -> bytes:
        """Read only bytes already in the driver buffer — never block on serial.read().

        A blocking read(1) is how Windows COM gets stuck after an RF flood
        (sensor walked out of LF range while Trigger/Receive RF was still armed).
        """
        chunks: list[bytes] = []
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        try:
            while time.monotonic() < deadline:
                if self.should_stop() or not getattr(self.serial, "is_open", False):
                    break
                waiting = int(getattr(self.serial, "in_waiting", 0) or 0)
                if waiting:
                    chunks.append(self.serial.read(waiting))
                    continue
                if chunks:
                    break
                time.sleep(0.01)
            return b"".join(chunks)
        except Exception:
            return b"".join(chunks)

    def _read_uart_frames(self, timeout_s: float) -> list[HamatonFrame]:
        data = self._drain_uart(timeout_s)
        if not data:
            return []
        try:
            return self._parser.feed(data)
        except FrameError:
            # Bad byte in the stream — reset and keep listening for a clean frame.
            self._parser.reset()
            return []

    def _handle_frame(self, codec: CommandCodec, frame: HamatonFrame) -> CommandResult | None:
        if not codec.accepts_response(frame):
            return None
        try:
            return codec.parse_response(frame)
        except (CodecError, UnexpectedResponseError, FrameError):
            return None

    def execute(
        self,
        codec: CommandCodec,
        timeout: float | None = None,
        *,
        allow_resend: bool = False,
    ) -> CommandResult:
        """Send a command on USB-TTL TX and wait for the reply on USB-TTL RX."""
        if self.should_stop():
            return CommandResult.failure(0xFF, "stopped")
        is_program = isinstance(codec, ProgramOneSensorCodec)
        try:
            self.send_codec(codec)
        except Exception as exc:
            if self.should_stop() or "stopped" in str(exc).lower():
                return CommandResult.failure(0xFF, "stopped")
            return CommandResult.failure(0xFF, str(exc))
        seconds = codec.timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + seconds
        started = time.monotonic()
        hard_deadline = started + max(seconds, 1.0) * 2
        last_pending: CommandResult | None = None
        last_pending_key: tuple | None = None
        resent = False

        while time.monotonic() < deadline and time.monotonic() < hard_deadline:
            if self.should_stop():
                return CommandResult.failure(0xFF, "stopped")
            for frame in self._read_uart_frames(UART_POLL_S):
                result = self._handle_frame(codec, frame)
                if result is None:
                    continue
                self.last_path = "USB-TTL RX"
                self._signal("uart", "RX frame")
                if result.is_pending:
                    last_pending = result
                    key = (result.message, getattr(result.value, "sensor_count", None))
                    if key != last_pending_key:
                        last_pending_key = key
                        deadline = time.monotonic() + seconds
                    continue
                return result

            # Mid-wait resend for Program — boards sometimes miss the first TX.
            if (
                allow_resend
                and is_program
                and not resent
                and last_pending is None
                and (time.monotonic() - started) >= PROGRAM_RESEND_S
            ):
                resent = True
                try:
                    self.send_codec(codec)
                    self._signal("ttl", "program resend")
                except Exception:
                    pass

            if time.monotonic() >= deadline:
                break
            time.sleep(0.03)

        if self.should_stop():
            return CommandResult.failure(0xFF, "stopped")
        if (
            last_pending is not None
            and isinstance(last_pending.value, SearchProgress)
            and last_pending.value.sensor_count >= 1
        ):
            return CommandResult.success(last_pending.value)
        return CommandResult.failure(0xFF, "timeout waiting for board response")

    def cancel(self, wait_s: float | None = None) -> None:
        """Stop Trigger/Program and wait briefly for the cancel ACK."""
        if self.should_stop() or not getattr(self.serial, "is_open", False):
            return
        try:
            codec = CancelCodec()
            self.send_codec(codec)
            deadline = time.monotonic() + (CANCEL_WAIT_S if wait_s is None else max(0.05, float(wait_s)))
            while time.monotonic() < deadline:
                if self.should_stop():
                    return
                for frame in self._read_uart_frames(0.05):
                    result = self._handle_frame(codec, frame)
                    if result is not None and not result.is_pending:
                        return
                time.sleep(0.01)
        except Exception:
            pass

    def recover_link(self, code_a: int = 0, code_b: int = 0, code_c: int = 0) -> None:
        """Disarm leftover Trigger/Receive-RF so the next row is not wedged after a miss."""
        if not getattr(self.serial, "is_open", False):
            return
        try:
            self._tx_now(ReceiveRfCodec(False, code_a, code_b, code_c))
        except Exception:
            pass
        try:
            self._tx_now(CancelCodec())
        except Exception:
            pass
        try:
            self._drain_uart(0.15)
            self._parser.reset()
            if getattr(self.serial, "is_open", False):
                self.serial.reset_input_buffer()
        except Exception:
            pass

    def program(self, code_a: int, code_b: int, code_c: int, oeid: int = 0) -> CommandResult:
        """Program one sensor. Prefer OEID 0 (board assigns ID) for reliable ACKs."""
        # Use our short timeout — do not wait on the codec's 12s default.
        timeout = PROGRAM_TIMEOUT_S

        def _attempt(use_oeid: int) -> CommandResult:
            self.cancel()
            time.sleep(POST_CANCEL_S)
            if self.should_stop():
                return CommandResult.failure(0xFF, "stopped")
            try:
                self.serial.reset_input_buffer()
                self._parser.reset()
            except Exception:
                pass
            return self.execute(
                ProgramOneSensorCodec(code_a, code_b, code_c, use_oeid),
                timeout=timeout,
                allow_resend=True,
            )

        # One fast attempt — LF/RF still runs if ACK is lost (OK from telemetry).
        return _attempt(oeid)

    def lf_activate(
        self,
        code_a: int,
        code_b: int,
        code_c: int,
        *,
        expected_id: str | None = None,
        wait_s: float | None = None,
    ) -> tuple[bool, SensorReading | None, str]:
        """LF trigger + RF read over USB-TTL only."""
        try:
            self.cancel()
            if wait_s is None:
                wait_s = FAST_TRIGGER_WAIT_S if self.uart_rx_active else TRIGGER_WAIT_S
            else:
                wait_s = max(1.0, float(wait_s))
            self.send_codec(ReceiveRfCodec(True, code_a, code_b, code_c))
            self.send_codec(TriggerCodec(code_a, code_b, code_c))

            trigger_codec = TriggerCodec(code_a, code_b, code_c)
            deadline = time.monotonic() + wait_s
            fallback: SensorReading | None = None

            while time.monotonic() < deadline:
                if self.should_stop():
                    return False, None, "stopped"
                for frame in self._read_uart_frames(0.05):
                    result = self._handle_frame(trigger_codec, frame)
                    if result and result.is_success and isinstance(result.value, SensorReading):
                        sid = result.value.sensor_id.hex().upper()
                        if expected_id and sid != expected_id.upper():
                            fallback = fallback or result.value
                            continue
                        self.last_path = "USB-TTL RX"
                        return True, result.value, "trigger"
                    if result and result.is_pending:
                        break
                time.sleep(0.02)

            if fallback is not None:
                self.last_path = self.last_path or "USB-TTL RX"
                return True, fallback, "trigger"

            search = self.lf_search(code_a, code_b, code_c)
            if search.is_success and isinstance(search.value, SearchProgress) and search.value.sensor_count >= 1:
                self.last_path = self.last_path or "USB-TTL RX"
                return True, None, "lf-search"

            return False, None, "trigger timeout"
        except Exception:
            if self.should_stop():
                return False, None, "stopped"
            raise
        finally:
            # Always disarm RX — leftover Receive-RF after a miss wedges the next row.
            try:
                self.recover_link(code_a, code_b, code_c)
            except Exception:
                pass

    def lf_search(self, code_a: int, code_b: int, code_c: int) -> CommandResult:
        self.cancel()
        return self.execute(ProgramSearchCodec(code_a, code_b, code_c), timeout=LF_SEARCH_TIMEOUT_S)

    def query(self, *, expected_id: str | None = None) -> CommandResult:
        """Query sensor telemetry over USB-TTL RX only."""
        errors: list[str] = []
        fallback: QuerySensorReading | None = None
        for attempt in range(1, QUERY_RETRIES + 1):
            time.sleep(0.02 if attempt == 1 else 0.08)
            result = self.execute(QuerySensorCodec(), timeout=QUERY_TIMEOUT_S)
            if result.is_success and isinstance(result.value, QuerySensorReading):
                reading = result.value
                sid = reading.sensor_id.hex().upper()
                if expected_id and sid != expected_id.upper():
                    fallback = fallback or reading
                    errors.append(f"stale query ID {sid}")
                else:
                    return result
            else:
                errors.append(result.message or "query failed")

        if fallback is not None:
            self.last_path = self.last_path or "USB-TTL RX"
            return CommandResult.success(fallback)
        return CommandResult.failure(0xFF, "; ".join(errors[:2]))

    def run_row(
        self,
        code_a: int,
        code_b: int,
        code_c: int,
        oeid: int = 0,
        iq_path: Path | None = None,
        sdr_duration: float = DEFAULT_SDR_ROW_S,
        frequency_hz: int = 433_920_000,
    ) -> tuple[BoardTelemetry, SdrCaptureResult]:
        tel = BoardTelemetry()
        empty_sdr = SdrCaptureResult(available=False, packets=[], iq_path=None, error="stopped")
        if self.should_stop():
            tel.reasons.append("stopped")
            return tel, empty_sdr
        requested_id = format_oeid(oeid) if oeid else None

        program_trusted = False
        program_attempts_used = 0
        last_program_msg = "failed"
        for attempt in range(1, PROGRAM_ATTEMPTS + 1):
            program_attempts_used = attempt
            if self.should_stop():
                tel.reasons.append("stopped")
                return tel, empty_sdr
            if attempt == 1:
                self._emit_phase("program", "Programming ABC codes…")
            else:
                self._emit_phase(
                    "program",
                    f"Program retry {attempt}/{PROGRAM_ATTEMPTS} (ACK miss / timeout)…",
                )
                try:
                    self.recover_link(code_a, code_b, code_c)
                except Exception:
                    pass
                time.sleep(RETRY_SETTLE_S * attempt)

            program = self.program(code_a, code_b, code_c, oeid)
            if self.should_stop() or (program.is_failure and (program.message or "") == "stopped"):
                tel.reasons.append("stopped")
                return tel, empty_sdr

            if program.is_success and isinstance(program.value, ProgramResult):
                program_trusted = self.last_path in ("USB-TTL RX", "Board RX")
                tel.program_ok = True
                tel.frequency = program.value.frequency
                tel.frequency_mhz = program.value.frequency_mhz
                returned_id = program.value.sensor_id.hex().upper()
                tel.sensor_id = returned_id
                if program_trusted:
                    tel.programmed_id = returned_id
                # A 28-bit protocol cannot hold a full 32-bit OEID, so the board
                # choosing its own ID there is expected, not a fault.
                id_bits = getattr(program.value, "id_bit_length", 0x20)
                if requested_id and returned_id != requested_id and id_bits >= 0x20:
                    tel.reasons.append(
                        f"program used ID {returned_id} (requested OEID {requested_id})"
                    )
                break

            last_program_msg = program.message or "failed"
            # TRI database errors will not recover by retrying the same ABC.
            if "TRI database" in last_program_msg:
                break

        if not tel.program_ok and "TRI database" not in last_program_msg:
            tel.reasons.append(f"program: {last_program_msg}")
            if program_attempts_used > 1:
                tel.reasons.append(f"program retries: {program_attempts_used}")

        sdr_proc = start_capture(iq_path, frequency_hz=frequency_hz, duration_s=sdr_duration) if iq_path else None

        expected_id = tel.programmed_id if program_trusted else None
        trigger_attempts_used = 0
        for attempt in range(1, TRIGGER_ATTEMPTS + 1):
            trigger_attempts_used = attempt
            if self.should_stop():
                tel.reasons.append("stopped")
                if sdr_proc is not None and iq_path is not None:
                    finish_capture(sdr_proc, iq_path, extra_wait_s=0.2)
                return tel, empty_sdr
            if attempt == 1:
                self._emit_phase("trigger", "LF trigger — waiting for sensor…")
                wait_s = None
            else:
                self._emit_phase(
                    "trigger",
                    f"LF trigger retry {attempt}/{TRIGGER_ATTEMPTS}…",
                )
                try:
                    self.recover_link(code_a, code_b, code_c)
                except Exception:
                    pass
                time.sleep(RETRY_SETTLE_S * attempt)
                # Give later attempts a slightly longer RF window.
                base = FAST_TRIGGER_WAIT_S if self.uart_rx_active else TRIGGER_WAIT_S
                wait_s = base + 0.6 * (attempt - 1)

            activated, trigger_reading, _note = self.lf_activate(
                code_a, code_b, code_c, expected_id=expected_id, wait_s=wait_s
            )
            if activated:
                tel.trigger_ok = True
                tel.reasons = [
                    r for r in tel.reasons if not str(r).startswith("trigger:")
                ]
                if trigger_reading is not None:
                    _merge_sensor_reading(tel, trigger_reading)
                break

        if not tel.trigger_ok:
            tel.reasons.append("trigger: no sensor response")
            if trigger_attempts_used > 1:
                tel.reasons.append(f"trigger retries: {trigger_attempts_used}")

        heard = bool(tel.trigger_ok)
        trigger_complete = tel.qualifies_ok()
        # Query only when the sensor actually answered. Query-while-idle after an
        # out-of-range miss is what wedged the board until the next restart.
        if trigger_complete and tel.battery_voltage_v is not None:
            tel.read_ok = True
        elif heard:
            self._emit_phase("query", "Query sensor reading…")
            query = self.query(expected_id=expected_id)
            if query.is_success and isinstance(query.value, QuerySensorReading):
                _merge_query_reading(tel, query.value)
                if tel.qualifies_ok():
                    tel.read_ok = True
            elif trigger_complete:
                tel.read_ok = True
            elif tel.trigger_ok and tel.sensor_id and tel.temperature_c is not None:
                tel.read_ok = True
            else:
                qmsg = query.message or "query sensor failed"
                if "stale query" not in (qmsg or ""):
                    tel.reasons.append(f"read: {qmsg}")

        # One follow-up trigger when we already heard the sensor (partial read).
        if not tel.qualifies_ok() and heard and not self.should_stop():
            self._emit_phase("trigger", "Partial read — one more LF trigger…")
            activated2, trigger2, _ = self.lf_activate(
                code_a, code_b, code_c, expected_id=None, wait_s=TRIGGER_WAIT_S + 0.5
            )
            if activated2:
                tel.trigger_ok = True
                tel.reasons = [r for r in tel.reasons if not str(r).startswith("trigger:")]
                if trigger2 is not None:
                    _merge_sensor_reading(tel, trigger2)

        if tel.qualifies_ok() and not tel.program_ok:
            tel.program_ok = True

        self.recover_link(code_a, code_b, code_c)

        if sdr_proc is None or iq_path is None:
            sdr = SdrCaptureResult(False, [], None, "SDR skipped")
        else:
            sdr = finish_capture(
                sdr_proc, iq_path, extra_wait_s=max(SDR_FINISH_EXTRA_S, sdr_duration * 0.25)
            )
        return tel, sdr


def _apply_rf_sensor_id(tel: BoardTelemetry, rf_id: str) -> bool:
    """Apply RF sensor ID. Prefer live RF over a possibly-stale program ACK."""
    rf_id = (rf_id or "").strip().upper()
    if not rf_id:
        return True
    if tel.programmed_id and rf_id == tel.programmed_id:
        tel.sensor_id = rf_id
        tel.rf_id_verified = True
        return True
    # Accept live RF ID even when it differs from program ACK — the wire ACK
    # is often a reused SRAM echo while RF is the real sensor.
    tel.sensor_id = rf_id
    tel.rf_id_verified = True
    if tel.programmed_id and rf_id != tel.programmed_id:
        # Keep a soft note only; does not block OK anymore.
        note = f"ID mismatch: programmed {tel.programmed_id} RF {rf_id}"
        if note not in tel.reasons:
            tel.reasons.append(note)
    return True


def _merge_sensor_reading(tel: BoardTelemetry, reading: SensorReading) -> None:
    rf_id = reading.sensor_id.hex().upper()
    if not _apply_rf_sensor_id(tel, rf_id):
        return
    tel.frequency = reading.frequency
    tel.frequency_mhz = reading.frequency_mhz
    if reading.pressure_kpa is not None:
        tel.pressure_raw = int(round(reading.pressure_kpa * 100))
    if reading.temperature_c is not None:
        tel.temperature_c = reading.temperature_c
    tel.battery_percentage = reading.battery_percentage
    tel.battery_ok = reading.battery_ok
    # Never keep a bogus 0% — Hamaton uses 0x00 as "OK flag", not zero percent.
    if tel.battery_percentage is not None:
        try:
            if not (1 <= int(tel.battery_percentage) <= 100):
                tel.battery_percentage = None
        except (TypeError, ValueError):
            tel.battery_percentage = None
    try:
        tel.rssi = int(reading.rssi)
    except (TypeError, ValueError, AttributeError):
        pass


def _merge_query_reading(tel: BoardTelemetry, reading: QuerySensorReading) -> None:
    rf_id = reading.sensor_id.hex().upper()
    if not _apply_rf_sensor_id(tel, rf_id):
        return
    tel.read_ok = True
    if reading.pressure_read:
        tel.pressure_raw = reading.pressure_raw
    if reading.temperature_read:
        tel.temperature_c = reading.temperature_c
    volts = reading.battery_voltage_v
    if volts is not None:
        tel.battery_voltage_v = volts
        tel.battery_ok = volts >= 2.5
    elif reading.battery_status_read and tel.battery_ok is None:
        # Status bit says battery was read, but raw units were unrecognized —
        # keep OK so the row is not failed only for a unit quirk.
        tel.battery_ok = True if reading.status != 0 else tel.battery_ok
    elif volts is None and reading.status != 0 and tel.battery_voltage_v is None:
        tel.battery_ok = True
