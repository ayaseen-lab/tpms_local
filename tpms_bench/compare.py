"""Compare TPMS board telemetry with rtl_433 JSON (OK/NOK agreement).

Pass/fail is Sensor ID match plus OK/NOK completeness in the same Board
trigger/capture window. Numeric equality of pressure/temperature/battery is
intentionally out of scope — Board UART/query and SDR RF decode are different
paths and will often report different values even seconds apart.
"""

from __future__ import annotations

from .board import BoardTelemetry
from .rtl433 import SdrCaptureResult, SdrPacket


def norm_id(value: str | None) -> str:
    if not value:
        return ""
    return value.replace(" ", "").replace("0x", "").replace("0X", "").upper().lstrip("0") or "0"


# Back-compat alias used by older call sites / tests
_norm_id = norm_id


def best_packet(capture: SdrCaptureResult, expected_id: str | None) -> SdrPacket | None:
    if not capture.packets:
        return None
    want = norm_id(expected_id)
    for packet in capture.packets:
        if want and norm_id(packet.sensor_id) == want:
            return packet
    return capture.packets[0]


def packet_result(packet: SdrPacket | None) -> tuple[str, str]:
    """Map an SDR packet to OK/NOK using the same completeness rule as the SDR UI."""
    if packet is None:
        return "NOK", "SDR did not decode matching ID"
    sid = (packet.sensor_id or "").strip()
    if not sid or sid.lower() in {"none", "unknown", "n/a", "na", "-", "—"}:
        return "NOK", "missing sensor ID"
    has_temp = packet.temperature is not None
    has_pressure = packet.pressure is not None
    has_battery = packet.battery is not None and str(packet.battery).strip() != ""
    if sid and has_temp and (has_pressure or has_battery):
        return "OK", ""
    missing: list[str] = []
    if not has_temp:
        missing.append("temperature")
    if not has_pressure and not has_battery:
        missing.append("pressure or battery")
    return "NOK", "missing " + " + ".join(missing) if missing else "incomplete telemetry"


def board_result(board: BoardTelemetry) -> tuple[str, str]:
    if board.qualifies_ok():
        return "OK", ""
    reason = board.status_note()
    return "NOK", reason or "incomplete reading"


def compare(board: BoardTelemetry, capture: SdrCaptureResult) -> tuple[str, str]:
    """Return (SUCCESS|FAIL, reason) for ID + OK/NOK agreement in the live window.

    Does not compare pressure/temperature/battery magnitudes — those often differ
    between Board and SDR and must not drive PASS/FAIL.
    """
    b_ok, b_reason = board_result(board)

    if not capture.available:
        return "FAIL", capture.error or "SDR unavailable"
    if capture.error and not capture.packets:
        return "FAIL", capture.error

    packet = best_packet(capture, board.sensor_id)
    if packet is None:
        return "FAIL", f"DISAGREE: board={b_ok} sdr=NOK (no TPMS packet decoded)"

    if board.sensor_id and packet.sensor_id:
        if norm_id(board.sensor_id) != norm_id(packet.sensor_id):
            return (
                "FAIL",
                f"DISAGREE: ID mismatch board={board.sensor_id} sdr={packet.sensor_id}",
            )
    elif board.sensor_id and not packet.sensor_id:
        return "FAIL", f"DISAGREE: board={b_ok} sdr=NOK (rtl_433 packet has no sensor ID)"
    elif not board.sensor_id:
        return "FAIL", "board has no sensor ID to compare"

    s_ok, s_reason = packet_result(packet)
    if b_ok == s_ok:
        return "SUCCESS", f"AGREE: both {b_ok}"
    detail = s_reason or b_reason
    suffix = f" ({detail})" if detail else ""
    return "FAIL", f"DISAGREE: board={b_ok} sdr={s_ok}{suffix}"
