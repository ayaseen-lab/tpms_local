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


def related_ids(value: str | None) -> set[str]:
    """Board OEID and rtl_433 often disagree by bit-shift; keep a family of candidates."""
    raw = str(value or "").replace(" ", "").replace("0x", "").replace("0X", "").upper()
    if not raw or raw in {"NA", "N/A", "NONE", "-", "—"}:
        return set()
    out: set[str] = {raw, norm_id(raw)}
    try:
        num = int(raw, 16) & 0xFFFFFFFF
    except ValueError:
        return {x for x in out if x}
    for shift in range(0, 8):
        out.add(f"{(num << shift) & 0xFFFFFFFF:08X}")
        out.add(f"{(num >> shift) & 0xFFFFFFFF:08X}")
    out.add(f"{num & 0x0FFFFFFF:08X}")
    out.add(f"{num & 0x00FFFFFF:08X}")
    out.add(f"{(num << 4) & 0xFFFFFFFF:08X}")
    out.add(f"{(num >> 4) & 0xFFFFFFFF:08X}")
    return {norm_id(x) for x in out if x}


def ids_related(a: str | None, b: str | None) -> bool:
    """True when two IDs are the same sensor under different rtl_433 / Board views."""
    left = str(a or "").replace(" ", "").replace("0x", "").replace("0X", "").upper()
    right = str(b or "").replace(" ", "").replace("0x", "").replace("0X", "").upper()
    if not left or not right:
        return False
    if related_ids(left) & related_ids(right):
        return True
    # Shared hex tail — Board OEID often drops/changes high nibbles vs OTA
    # (e.g. Board 004211BA vs rtl/flex D8C411BA → both end in 11BA).
    for n in (6, 5, 4):
        if len(left) >= n and len(right) >= n and left[-n:] == right[-n:]:
            return True
    # Low 16/24-bit equality on parsed ints (high byte OE/protocol prefix differs).
    try:
        la = int(left, 16) & 0xFFFFFFFF
        rb = int(right, 16) & 0xFFFFFFFF
    except ValueError:
        return False
    if (la & 0xFFFF) == (rb & 0xFFFF) and (la & 0xFFFF) != 0:
        return True
    if (la & 0xFFFFFF) == (rb & 0xFFFFFF) and (la & 0xFFFFFF) != 0:
        return True
    return False


def best_packet(capture: SdrCaptureResult, expected_id: str | None) -> SdrPacket | None:
    if not capture.packets:
        return None
    want = norm_id(expected_id)
    if want:
        for packet in capture.packets:
            if norm_id(packet.sensor_id) == want:
                return packet
        for packet in capture.packets:
            if ids_related(expected_id, packet.sensor_id):
                return packet
    return capture.packets[0]


def packet_result(packet: SdrPacket | None) -> tuple[str, str]:
    """Map an SDR packet to OK/NOK.

    Stock library decodes are preferred. OE/Hamaton bursts often only appear as
    flex with an RF ID — those are OK once they carry real telemetry (or Board
    soft-fill) so custom-code Board rows are not stuck NOK forever.
    """
    if packet is None:
        return "NOK", "SDR did not decode matching ID"
    proto = (packet.protocol or "").strip().lower()
    if "waiting for" in proto:
        return "NOK", "waiting for rtl_433 decode"
    sid = (packet.sensor_id or "").strip()
    if not sid or sid.lower() in {"none", "unknown", "n/a", "na", "-", "—"}:
        return "NOK", "missing sensor ID"
    has_temp = packet.temperature is not None
    has_pressure = packet.pressure is not None
    has_battery = packet.battery is not None and str(packet.battery).strip() != ""
    if sid and has_temp and (has_pressure or has_battery):
        label = (packet.protocol or "").strip()
        if label.lower().startswith("[flex]"):
            return "OK", "OE/flex RF ID + telemetry"
        if label.startswith("[") and "]" in label:
            mid = label[1 : label.index("]")].strip()
            if not mid.isdigit() and mid.lower() != "flex":
                return "NOK", "not a stock rtl_433 library decoder"
        return "OK", ""
    missing: list[str] = []
    if not has_temp:
        missing.append("temperature")
    if not has_pressure and not has_battery:
        missing.append("pressure or battery")
    if proto.startswith("[flex]"):
        return "NOK", "flex ID only — no telemetry yet"
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
        return "na", capture.error or "SDR unavailable"
    if capture.error and not capture.packets:
        err = capture.error or ""
        low = err.lower()
        # Explicit post-Board wait timeout → SDR FAIL (Board may still be OK).
        if "sdr fail" in low or "no rtl_433" in low or "decode timeout" in low:
            return "FAIL", err
        # Live Receiver still warming up after a replug — do not fail the row.
        if "no packets" in low and "warming" in low:
            return "na", err
        if "has no sensors yet" in low:
            return "na", err
        return "FAIL", err or "SDR heard no rtl_433 decode"

    packet = best_packet(capture, board.sensor_id)
    if packet is None:
        return "FAIL", f"DISAGREE: board={b_ok} sdr=NOK (no TPMS packet decoded)"

    if board.sensor_id and packet.sensor_id:
        if norm_id(board.sensor_id) != norm_id(packet.sensor_id) and not ids_related(
            board.sensor_id, packet.sensor_id
        ):
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
