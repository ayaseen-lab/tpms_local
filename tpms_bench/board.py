"""Program sensor, LF-activate, and read telemetry from the TPMS board."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hamaton.codec import CommandCodec
from hamaton.commands.cancel import CancelCodec
from hamaton.commands.program_sensor import ProgramOneSensorCodec
from hamaton.commands.query_version import QueryVersionCodec
from hamaton.commands.receive_rf import ReceiveRfCodec
from hamaton.commands.trigger import TriggerCodec
from hamaton.exceptions import CodecError, FrameError, UnexpectedResponseError
from hamaton.frame import HamatonFrame
from hamaton.models import CommandResult, ProgramResult, SensorReading
from hamaton.parser import HamatonStreamParser
from hamaton.sensor_reading import parse_sensor_reading

from . import jlink_ram
from .program_search import ProgramSearchCodec, SearchProgress
from .query_sensor import QuerySensorCodec, QuerySensorReading
from .rtl433 import SdrCaptureResult, finish_capture, start_capture

UART_POLL_S = 0.10
JLINK_POLL_S = 2.0
TRIGGER_WAIT_S = 12.0
FAST_TRIGGER_WAIT_S = 8.0
QUERY_TIMEOUT_S = 6.0
QUERY_RETRIES = 3
TX_GAP_S = 0.08

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
    program_ok: bool = False
    trigger_ok: bool = False
    read_ok: bool = False
    reasons: list[str] = field(default_factory=list)

    def _has_battery(self) -> bool:
        return (
            self.battery_percentage is not None
            or self.battery_voltage_v is not None
            or self.battery_ok is not None
        )

    def missing_values(self) -> list[str]:
        """Fields that still block Board OK (aligned with qualifies_ok)."""
        if not self.program_ok:
            return ["program success"]
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
        if self.programmed_id and not self.rf_id_verified:
            missing.append(f"RF confirm of ID {self.programmed_id}")
        return missing

    def qualifies_ok(self) -> bool:
        """OK only when program succeeded and all core values were read."""
        if not self.program_ok:
            return False
        if self.programmed_id and not self.rf_id_verified:
            return False
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
            if duration_s is not None:
                return f"all values read in {duration_s:.1f}s"
            return "all values read"

        if any((r or "").strip() == "stopped" for r in self.reasons):
            return "stopped by operator"

        if not self.program_ok:
            for reason in self.reasons:
                text = str(reason or "").strip()
                if text.startswith("program:"):
                    detail = text[len("program:") :].strip() or "failed"
                    if "timeout" in detail.lower():
                        return "program failed — board did not acknowledge (timeout)"
                    return f"program failed — {detail}"
            return "program failed — sensor ID not written"

        parts: list[str] = []

        def _add(text: str) -> None:
            text = (text or "").strip()
            if text and text not in parts:
                parts.append(text)

        no_rf = not self.trigger_ok and not self.read_ok and self.temperature_c is None and self.pressure_raw is None

        for reason in self.reasons:
            text = str(reason or "").strip()
            if not text or text.lower().startswith("missing "):
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
            # Avoid repeating the same story after a clear trigger failure.
            if no_rf and any(p.startswith("trigger failed") for p in parts):
                if "sensor ID" in gaps and not self.programmed_id:
                    _add("missing sensor ID")
            else:
                _add("missing " + ", ".join(gaps))

        if self.programmed_id and not self.rf_id_verified and not no_rf:
            if not any("confirm" in p.lower() or "mismatch" in p.lower() for p in parts):
                _add(f"RF did not confirm programmed ID {self.programmed_id}")

        return "; ".join(parts) if parts else "incomplete reading"


class BoardSession:
    """USB-TTL TX for commands; USB-TTL RX first with board SRAM fallback."""

    def __init__(self, serial_port, on_comm: CommCb | None = None) -> None:
        self.serial = serial_port
        self.uart_rx_active = False
        self.jlink_enabled = True
        self.on_comm = on_comm or (lambda _c, _d: None)
        self.transport_mode = "Detecting…"
        self.last_path = "none"
        self.tx_path = "USB-TTL TX"
        self.rx_path = "…"
        self._parser = HamatonStreamParser()
        self.jlink_ok = False
        self.ttl_ok = False
        self._stop_check: Callable[[], bool] = lambda: False
        self._aborted = False

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
        if self.should_stop():
            self.transport_mode = "Stopped"
            return self.transport_mode
        dump = jlink_ram.dump_sram_result()
        self.jlink_ok = dump.ok
        self.jlink_enabled = dump.ok
        self.uart_rx_active = self._probe_uart_rx()
        self.ttl_ok = self.serial.is_open

        if self.uart_rx_active and self.jlink_ok:
            self.rx_path = "USB-TTL RX + Board fallback"
            self.transport_mode = "USB-TTL TX/RX"
        elif self.uart_rx_active:
            self.rx_path = "USB-TTL RX"
            self.transport_mode = "USB-TTL TX/RX"
        elif self.jlink_ok:
            self.rx_path = "Board RX"
            self.transport_mode = "USB-TTL TX · Board RX"
        else:
            self.transport_mode = "USB-TTL TX · no reply path detected"
        return self.transport_mode

    def verify_hardware(self) -> tuple[bool, str]:
        """Require USB-TTL TX open and at least one RX path (USB-TTL RX or J-Link).

        J-Link is optional. A missing/unplugged programmer must not fail the check
        when Query Version already returns over USB-TTL.
        """
        if self.should_stop():
            return False, "stopped"
        issues: list[str] = []
        if not self.serial.is_open:
            issues.append(f"USB-TTL port {self.serial.port} not open")
        else:
            self.ttl_ok = True

        if self.should_stop():
            return False, "stopped"
        dump = jlink_ram.dump_sram_result()
        self.jlink_ok = dump.ok
        self.jlink_enabled = dump.ok
        if dump.ok:
            self._signal("jlink", f"SRAM {len(dump.blob)} bytes")
        else:
            # Soft warning only — do not fail the bench when UART RX works.
            self._signal("jlink", dump.message)

        if self.should_stop():
            return False, "stopped"
        self.uart_rx_active = self._probe_uart_rx()
        if not self.uart_rx_active and not self.jlink_ok:
            detail = dump.message if dump.message else "no board reply path"
            issues.append(
                "No USB-TTL RX reply and no J-Link RX path "
                f"({detail}). Use the CH340/USB-TTL COM port (not J-Link CDC UART), "
                "confirm 115200 baud cable to the board, or connect the SEGGER programmer."
            )

        if issues:
            return False, "; ".join(issues)
        if self.uart_rx_active and self.jlink_ok:
            rx = "USB-TTL RX + J-Link"
        elif self.uart_rx_active:
            rx = "USB-TTL RX"
        else:
            rx = "J-Link RX"
        return True, f"TX {self.serial.port} · RX {rx}"

    def send_codec(self, codec: CommandCodec) -> None:
        if self.should_stop() or not getattr(self.serial, "is_open", False):
            raise RuntimeError("stopped")
        raw = codec.build_request()
        self.serial.reset_input_buffer()
        self._parser.reset()
        written = self.serial.write(raw)
        self.serial.flush()
        self._signal("ttl", f"TX {written}B")
        time.sleep(TX_GAP_S)

    def _drain_uart(self, timeout_s: float) -> bytes:
        old = self.serial.timeout
        chunks: list[bytes] = []
        try:
            self.serial.timeout = max(0.03, timeout_s)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                waiting = self.serial.in_waiting or 0
                if waiting:
                    chunks.append(self.serial.read(waiting))
                else:
                    byte = self.serial.read(1)
                    if byte:
                        chunks.append(byte)
                    elif chunks:
                        break
            return b"".join(chunks)
        except Exception:
            return b"".join(chunks)
        finally:
            self.serial.timeout = old

    def _read_uart_frames(self, timeout_s: float) -> list[HamatonFrame]:
        data = self._drain_uart(timeout_s)
        if not data:
            return []
        return self._parser.feed(data)

    def _handle_frame(self, codec: CommandCodec, frame: HamatonFrame) -> CommandResult | None:
        if not codec.accepts_response(frame):
            return None
        try:
            return codec.parse_response(frame)
        except (CodecError, UnexpectedResponseError, FrameError):
            return None

    def _jlink_before(self) -> set[tuple[int, bytes]]:
        if not self.jlink_enabled:
            return set()
        dump = jlink_ram.dump_sram_result()
        if dump.ok:
            self._signal("jlink", "snap")
            return jlink_ram.snapshot_keys(dump.blob)
        return set()

    def _frames_from_blob(self, blob: bytes, before: set[tuple[int, bytes]]) -> list[HamatonFrame]:
        """Frames that appeared after the pre-command SRAM snapshot."""
        return jlink_ram.new_board_frames(blob, before)

    def _poll_jlink(
        self,
        codec: CommandCodec,
        before: set[tuple[int, bytes]],
    ) -> CommandResult | None:
        if not self.jlink_enabled:
            return None
        dump = jlink_ram.dump_sram_result()
        if not dump.ok:
            return None
        self._signal("jlink", f"{len(dump.blob)}B")

        # Prefer truly new SRAM frames first.
        for frame in reversed(self._frames_from_blob(dump.blob, before)):
            result = self._handle_frame(codec, frame)
            if result is None:
                continue
            self.last_path = "Board RX"
            return result

        # Fallback: board often reuses the same SRAM slot. Accept codec matches
        # that are pending/failure, or success that is new / matches requested OEID.
        # Never return a stale success that belongs to a previous row's ID.
        extracted = jlink_ram.extract_frames(dump.blob, HamatonFrame.BOARD_ADDRESS)
        for offset, frame in reversed(extracted[-24:]):
            key = (offset, frame.to_bytes())
            result = self._handle_frame(codec, frame)
            if result is None:
                continue
            if key in before and result.is_success:
                if (
                    isinstance(codec, ProgramOneSensorCodec)
                    and codec.oeid
                    and isinstance(result.value, ProgramResult)
                ):
                    got = int.from_bytes(result.value.sensor_id, "big")
                    if got == codec.oeid:
                        self.last_path = "Board RX"
                        return result
                continue
            self.last_path = "Board RX"
            return result
        return None

    def _trigger_reading_from_ram(
        self,
        blob: bytes,
        before: set[tuple[int, bytes]] | None = None,
        *,
        expected_id: str | None = None,
    ) -> SensorReading | None:
        before = before or set()
        trigger_codec = TriggerCodec(0, 0, 0)
        reading: SensorReading | None = None
        for offset, frame in jlink_ram.extract_frames(blob, HamatonFrame.BOARD_ADDRESS):
            if before and (offset, frame.to_bytes()) in before:
                continue
            payload = frame.payload
            if len(payload) < 2:
                continue
            cmd, sub = payload[0], payload[1]
            candidate: SensorReading | None = None
            if cmd == 0x28 and sub == 0x02:
                try:
                    candidate = parse_sensor_reading(payload[2:])
                except CodecError:
                    continue
            elif cmd in (0x20, 0xA0) and sub == 0x01:
                try:
                    result = trigger_codec.parse_response(frame)
                except (CodecError, UnexpectedResponseError):
                    continue
                if result.is_success and isinstance(result.value, SensorReading):
                    candidate = result.value
            if candidate is None:
                continue
            if expected_id:
                if candidate.sensor_id.hex().upper() != expected_id.upper():
                    continue
            reading = candidate
        return reading

    def _query_from_ram(
        self,
        blob: bytes,
        before: set[tuple[int, bytes]] | None = None,
        *,
        expected_id: str | None = None,
    ) -> QuerySensorReading | None:
        before = before or set()
        codec = QuerySensorCodec()
        for offset, frame in reversed(jlink_ram.extract_frames(blob, HamatonFrame.BOARD_ADDRESS)):
            if before and (offset, frame.to_bytes()) in before:
                continue
            payload = frame.payload
            if len(payload) < 2:
                continue
            if payload[0] not in (0x22, 0xA2) or payload[1] != 0x01:
                continue
            result = self._handle_frame(codec, frame)
            if result and result.is_success and isinstance(result.value, QuerySensorReading):
                reading = result.value
                if expected_id and reading.sensor_id.hex().upper() != expected_id.upper():
                    continue
                return reading
        return None

    def execute(
        self,
        codec: CommandCodec,
        timeout: float | None = None,
        jlink_poll_s: float = JLINK_POLL_S,
    ) -> CommandResult:
        if self.should_stop():
            return CommandResult.failure(0xFF, "stopped")
        # J-Link snapshot is slow — only take it when UART RX is unavailable.
        # With USB-TTL RX, prefer UART and use J-Link as a late fallback.
        before = (
            self._jlink_before()
            if (self.jlink_enabled and not self.uart_rx_active)
            else set()
        )
        try:
            self.send_codec(codec)
        except Exception as exc:
            if self.should_stop() or "stopped" in str(exc).lower():
                return CommandResult.failure(0xFF, "stopped")
            return CommandResult.failure(0xFF, str(exc))
        seconds = codec.timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + seconds
        last_pending: CommandResult | None = None
        last_jlink = 0.0
        uart_miss_since = time.monotonic()

        while time.monotonic() < deadline:
            if self.should_stop():
                return CommandResult.failure(0xFF, "stopped")
            for frame in self._read_uart_frames(UART_POLL_S):
                uart_miss_since = time.monotonic()
                result = self._handle_frame(codec, frame)
                if result is None:
                    continue
                self.last_path = "USB-TTL RX"
                if result.is_pending:
                    last_pending = result
                    deadline = time.monotonic() + seconds
                    continue
                return result

            need_jlink = (
                self.jlink_enabled
                and (not self.uart_rx_active or (time.monotonic() - uart_miss_since) > 0.8)
            )
            if need_jlink and (time.monotonic() - last_jlink) >= jlink_poll_s:
                last_jlink = time.monotonic()
                result = self._poll_jlink(codec, before)
                if result is not None:
                    if result.is_pending:
                        last_pending = result
                        deadline = time.monotonic() + seconds
                    else:
                        return result

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

    def cancel(self) -> None:
        if self.should_stop() or not getattr(self.serial, "is_open", False):
            return
        try:
            self.send_codec(CancelCodec())
            time.sleep(0.05)
        except Exception:
            pass

    def program(self, code_a: int, code_b: int, code_c: int, oeid: int = 0) -> CommandResult:
        self.cancel()
        if self.should_stop():
            return CommandResult.failure(0xFF, "stopped")
        timeout = max(15.0, ProgramOneSensorCodec.TIMEOUT_SECONDS)
        result = self.execute(
            ProgramOneSensorCodec(code_a, code_b, code_c, oeid),
            timeout=timeout,
        )
        if self.should_stop() or (result.is_failure and (result.message or "") == "stopped"):
            return CommandResult.failure(0xFF, "stopped")
        # One retry on timeout — boards often miss the first program after cancel.
        if result.is_failure and "timeout" in (result.message or "").lower():
            self.cancel()
            time.sleep(0.25)
            if self.should_stop():
                return CommandResult.failure(0xFF, "stopped")
            result = self.execute(
                ProgramOneSensorCodec(code_a, code_b, code_c, oeid),
                timeout=timeout,
            )
            if result.is_success:
                return result
            if self.should_stop() or (result.is_failure and (result.message or "") == "stopped"):
                return CommandResult.failure(0xFF, "stopped")
            # Last resort: auto-ID (OEID 0) so we can still collect telemetry values.
            if oeid:
                self.cancel()
                time.sleep(0.25)
                if self.should_stop():
                    return CommandResult.failure(0xFF, "stopped")
                auto = self.execute(
                    ProgramOneSensorCodec(code_a, code_b, code_c, 0),
                    timeout=timeout,
                )
                if auto.is_success:
                    return auto
        return result

    def lf_activate(
        self,
        code_a: int,
        code_b: int,
        code_c: int,
        *,
        expected_id: str | None = None,
    ) -> tuple[bool, SensorReading | None, str]:
        self.cancel()
        wait_s = FAST_TRIGGER_WAIT_S if self.uart_rx_active else TRIGGER_WAIT_S
        before = (
            self._jlink_before()
            if (self.jlink_enabled and not self.uart_rx_active)
            else set()
        )

        self.send_codec(ReceiveRfCodec(True, code_a, code_b, code_c))
        self.send_codec(TriggerCodec(code_a, code_b, code_c))

        trigger_codec = TriggerCodec(code_a, code_b, code_c)
        deadline = time.monotonic() + wait_s
        last_jlink = 0.0

        while time.monotonic() < deadline:
            if self.should_stop():
                return False, None, "stopped"
            for frame in self._read_uart_frames(0.15):
                result = self._handle_frame(trigger_codec, frame)
                if result and result.is_success and isinstance(result.value, SensorReading):
                    self.last_path = "USB-TTL RX"
                    return True, result.value, "trigger"
                if result and result.is_pending:
                    break

            if self.jlink_enabled and (time.monotonic() - last_jlink) >= (0.5 if self.uart_rx_active else JLINK_POLL_S):
                last_jlink = time.monotonic()
                dump = jlink_ram.dump_sram_result()
                if dump.ok:
                    # Without a pre-snapshot (USB-TTL RX path), only accept RAM
                    # readings that match the programmed OEID — never a stale ID.
                    reading = self._trigger_reading_from_ram(
                        dump.blob,
                        before if before else None,
                        expected_id=expected_id,
                    )
                    if reading is not None:
                        self.last_path = "Board RX"
                        return True, reading, "trigger"
                    for frame in reversed(self._frames_from_blob(dump.blob, before)):
                        result = self._handle_frame(trigger_codec, frame)
                        if result and result.is_success and isinstance(result.value, SensorReading):
                            if expected_id and result.value.sensor_id.hex().upper() != expected_id.upper():
                                continue
                            self.last_path = "Board RX"
                            return True, result.value, "trigger"

            time.sleep(0.05)

        search = self.lf_search(code_a, code_b, code_c)
        if search.is_success and isinstance(search.value, SearchProgress) and search.value.sensor_count >= 1:
            self.last_path = self.last_path or "Board RX"
            return True, None, "lf-search"

        return False, None, "trigger timeout"

    def lf_search(self, code_a: int, code_b: int, code_c: int) -> CommandResult:
        self.cancel()
        return self.execute(ProgramSearchCodec(code_a, code_b, code_c), timeout=10.0)

    def query(self, *, expected_id: str | None = None) -> CommandResult:
        errors: list[str] = []
        for attempt in range(1, QUERY_RETRIES + 1):
            time.sleep(0.15 if attempt == 1 else 0.35)
            before = (
                self._jlink_before()
                if (self.jlink_enabled and not self.uart_rx_active)
                else set()
            )
            result = self.execute(QuerySensorCodec(), timeout=QUERY_TIMEOUT_S, jlink_poll_s=1.0)
            if result.is_success and isinstance(result.value, QuerySensorReading):
                return result
            errors.append(result.message or "query failed")

            if self.jlink_enabled:
                dump = jlink_ram.dump_sram_result()
                if dump.ok:
                    reading = self._query_from_ram(
                        dump.blob,
                        before if before else None,
                        expected_id=expected_id,
                    )
                    if reading is not None:
                        self.last_path = "Board RX"
                        return CommandResult.success(reading)

        return CommandResult.failure(0xFF, "; ".join(errors[:2]))

    def run_row(
        self,
        code_a: int,
        code_b: int,
        code_c: int,
        oeid: int = 0,
        iq_path: Path | None = None,
        sdr_duration: float = 15.0,
        frequency_hz: int = 433_920_000,
    ) -> tuple[BoardTelemetry, SdrCaptureResult]:
        tel = BoardTelemetry()
        empty_sdr = SdrCaptureResult(available=False, packets=[], iq_path=None, error="stopped")
        if self.should_stop():
            tel.reasons.append("stopped")
            return tel, empty_sdr
        requested_id = format_oeid(oeid) if oeid else None

        program = self.program(code_a, code_b, code_c, oeid)
        if self.should_stop() or (program.is_failure and (program.message or "") == "stopped"):
            tel.reasons.append("stopped")
            return tel, empty_sdr
        if program.is_success and isinstance(program.value, ProgramResult):
            tel.program_ok = True
            tel.frequency = program.value.frequency
            tel.frequency_mhz = program.value.frequency_mhz
            returned_id = program.value.sensor_id.hex().upper()
            tel.sensor_id = returned_id
            tel.programmed_id = returned_id
            if requested_id and returned_id != requested_id:
                tel.reasons.append(
                    f"program used ID {returned_id} (requested OEID {requested_id})"
                )
        else:
            msg = program.message or "failed"
            if "TRI database" not in msg:
                tel.reasons.append(f"program: {msg}")
            # Do not set programmed_id on failure — that forced false "RF confirm" NOKs.
            # Skip trigger/query/SDR — root cause is already program failure.
            return tel, SdrCaptureResult(False, [], None, "SDR skipped — program failed")

        sdr_proc = start_capture(iq_path, frequency_hz=frequency_hz, duration_s=sdr_duration) if iq_path else None

        expected_id = tel.programmed_id
        activated, trigger_reading, _note = self.lf_activate(
            code_a, code_b, code_c, expected_id=expected_id
        )
        if activated:
            tel.trigger_ok = True
            if trigger_reading is not None:
                _merge_sensor_reading(tel, trigger_reading)
        else:
            tel.reasons.append("trigger: no sensor response")

        query = self.query(expected_id=expected_id)
        if query.is_success and isinstance(query.value, QuerySensorReading):
            _merge_query_reading(tel, query.value)
        elif tel.trigger_ok and tel.sensor_id and tel.temperature_c is not None:
            tel.read_ok = True
        else:
            qmsg = query.message or "query sensor failed"
            tel.reasons.append(f"read: {qmsg}")

        if tel.program_ok and tel.programmed_id and not tel.rf_id_verified:
            tel.reasons.append(
                f"RF did not confirm programmed ID {tel.programmed_id}"
            )

        self.send_codec(ReceiveRfCodec(False, code_a, code_b, code_c))
        self.cancel()

        if sdr_proc is None or iq_path is None:
            sdr = SdrCaptureResult(False, [], None, "SDR skipped")
        else:
            sdr = finish_capture(sdr_proc, iq_path, extra_wait_s=sdr_duration + 5)
        return tel, sdr


def _apply_rf_sensor_id(tel: BoardTelemetry, rf_id: str) -> None:
    """Keep the programmed OEID as Sensor ID; RF must match it for verification."""
    rf_id = (rf_id or "").strip().upper()
    if not rf_id:
        return
    if tel.programmed_id:
        if rf_id == tel.programmed_id:
            tel.sensor_id = rf_id
            tel.rf_id_verified = True
        else:
            tel.reasons.append(
                f"ID mismatch: programmed {tel.programmed_id} RF {rf_id}"
            )
            # Do not overwrite with the old physical-sensor ID.
            tel.sensor_id = tel.programmed_id
    else:
        tel.sensor_id = rf_id
        tel.rf_id_verified = True


def _merge_sensor_reading(tel: BoardTelemetry, reading: SensorReading) -> None:
    tel.frequency = reading.frequency
    tel.frequency_mhz = reading.frequency_mhz
    _apply_rf_sensor_id(tel, reading.sensor_id.hex().upper())
    if reading.pressure_kpa is not None:
        tel.pressure_raw = int(round(reading.pressure_kpa * 100))
    if reading.temperature_c is not None:
        tel.temperature_c = reading.temperature_c
    tel.battery_percentage = reading.battery_percentage
    tel.battery_ok = reading.battery_ok


def _merge_query_reading(tel: BoardTelemetry, reading: QuerySensorReading) -> None:
    tel.read_ok = True
    _apply_rf_sensor_id(tel, reading.sensor_id.hex().upper())
    if reading.pressure_read:
        tel.pressure_raw = reading.pressure_raw
    if reading.temperature_read:
        tel.temperature_c = reading.temperature_c
    tel.battery_voltage_v = reading.battery_voltage_v
    if reading.battery_voltage_v is None and reading.status != 0:
        tel.battery_ok = True
    elif reading.battery_voltage_v is not None:
        tel.battery_ok = reading.battery_voltage_v >= 2.5
