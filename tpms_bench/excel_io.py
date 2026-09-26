"""Copy the Hamaton database workbook and write bench result columns."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

RESULT_COLUMNS = [
    "Board performance",
    "NOK reason",
    "Battery percentage",
    "Baterry voltage",
    "SDR compare",
    "SDR reason",
    "rtl_433 Decoder",
    "IQ file",
    "Sensor ID",
    "Frequency",
    "Pressure",
    "Temperature",
    "Duration s",
]


DATABASE_HEADERS = [
    "Make",
    "Model",
    "Year From",
    "Year To",
    "Region",
    "Platform",
    "Type",
    "OE supplier",
    "OE Number",
    "Freq",
    "Col11",
    "Col12",
    "Col13",
    "Col14",
    "Col15",
    "CODEA",
    "CODEB",
    "CODEC",
]


def _is_permission_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 13:
        return True
    text = str(exc).lower()
    return "permission denied" in text or "being used by another process" in text


def alternate_workbook_path(preferred: Path) -> Path:
    """Unlocked sibling path when Excel (or another app) holds the preferred file."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return preferred.with_name(f"{preferred.stem}_live_{stamp}{preferred.suffix}")


def save_workbook(wb: Workbook, path: Path) -> Path:
    """Save workbook; if the target is locked (Excel open), write a live alternate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(path)
        return path
    except Exception as exc:
        if not _is_permission_error(exc):
            raise
        alt = alternate_workbook_path(path)
        wb.save(alt)
        return alt


def copy_workbook(source: Path, dest: Path, *, force: bool = False) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if force or not dest.exists():
        try:
            shutil.copy2(source, dest)
            return dest
        except Exception as exc:
            if not _is_permission_error(exc):
                raise
            alt = alternate_workbook_path(dest)
            shutil.copy2(source, alt)
            return alt
    # Resume path: preferred exists but may be locked for later saves — probe write access.
    try:
        with dest.open("a+b"):
            pass
        return dest
    except Exception as exc:
        if not _is_permission_error(exc):
            raise
        alt = alternate_workbook_path(dest)
        shutil.copy2(dest, alt)
        return alt


def create_blank_database(dest: Path) -> Path:
    """Minimal workbook so a run can start from custom opcodes only."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "TPMS Board"
    for col, name in enumerate(DATABASE_HEADERS, start=1):
        if not name.startswith("Col"):
            ws.cell(1, col, name)
    return save_workbook(wb, dest)


def append_manual_code_row(
    ws: Worksheet,
    cols: dict[str, int],
    *,
    code_a: str,
    code_b: str,
    code_c: str,
    label: str = "Manual code",
) -> int:
    row = ws.max_row + 1
    if ws.max_row == 1 and ws.cell(1, 1).value is None:
        row = 2
    ws.cell(row, cols.get("Make", 1), label)
    ws.cell(row, cols.get("Model", 2), "Custom opcode")
    ws.cell(row, cols.get("Year From", 3), "")
    ws.cell(row, cols.get("OE supplier", 8), "Manual")
    ws.cell(row, cols.get("OE Number", 9), "")
    ws.cell(row, cols.get("Freq", 10), "")
    ws.cell(row, cols.get("CODEA", 16), code_a)
    ws.cell(row, cols.get("CODEB", 17), code_b)
    ws.cell(row, cols.get("CODEC", 18), code_c)
    return row


def _header_map(ws: Worksheet) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for cell in ws[1]:
        if cell.value:
            mapping[str(cell.value).strip()] = cell.column
    return mapping


def ensure_result_columns(ws: Worksheet) -> dict[str, int]:
    mapping = _header_map(ws)
    last = max(mapping.values()) if mapping else 1
    for name in RESULT_COLUMNS:
        if name not in mapping:
            last += 1
            ws.cell(1, last, name)
            mapping[name] = last
    return mapping


def parse_code(value) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.lower() in ("none", "nan"):
        return None
    try:
        return int(text, 16)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def load_output(path: Path) -> tuple[Workbook, Worksheet, dict[str, int]]:
    wb = load_workbook(path)
    ws = wb[wb.sheetnames[0]]
    cols = ensure_result_columns(ws)
    return wb, ws, cols


def stamp_board_report_info(path: Path) -> None:
    """Mark the workbook as a TPMS Board report so it is not confused with SDR exports."""
    wb = load_workbook(path)
    if "Report Info" in wb.sheetnames:
        ws = wb["Report Info"]
    else:
        ws = wb.create_sheet("Report Info", 1)
    ws["A1"] = "TPMS Board Report"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Hamaton board validation results — this is not an SDR receiver report"
    ws["A4"] = "Report type"
    ws["B4"] = "TPMS Board (USB-TTL / Hamaton bench) — not SDR Receiver"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 64
    save_workbook(wb, path)


def write_row(ws: Worksheet, cols: dict[str, int], row: int, values: dict[str, object]) -> None:
    for name, value in values.items():
        ws.cell(row, cols[name], value)
