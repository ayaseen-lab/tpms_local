"""Export session readings to Excel."""

from datetime import datetime
from itertools import groupby
from pathlib import Path
from statistics import fmean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from rtl433_runner import TelemetryReading

REPORT_KIND = "SDR Receiver Report"
REPORT_SUBTITLE = "RTL-SDR / rtl_433 telemetry session — this is not a TPMS board report"

HEADER_FILL = PatternFill("solid", fgColor="1A365D")
HEADER_FONT = Font(bold=True, color="FFFFFF")
PRIMARY_FILL = PatternFill("solid", fgColor="2B4C7E")
PRIMARY_FONT = Font(bold=True, color="FFFFFF", size=12)
OK_FILL = PatternFill("solid", fgColor="ECFDF5")
LOW_FILL = PatternFill("solid", fgColor="FEF2F2")
WARN_FILL = PatternFill("solid", fgColor="FFF7ED")

READING_HEADERS = [
  "Sensor ID",
  "Timestamp",
  "Brand/Type",
  "Result",
  "Pressure (PSI)",
  "Temperature (°C)",
  "Battery",
  "Seconds since first",
  "NOK reason",
]

AVERAGE_HEADERS = [
  "Sensor ID",
  "Brand/Type",
  "Readings",
  "Result",
  "Avg Pressure (PSI)",
  "Avg Temperature (°C)",
  "Min Pressure (PSI)",
  "Max Pressure (PSI)",
  "First Reading",
  "Last Reading",
  "Time to OK (s)",
  "Span (s)",
  "NOK reason",
]


def _format_seconds(seconds: Optional[float]) -> str:
  if seconds is None:
    return "—"
  value = max(0.0, float(seconds))
  if value < 60:
    return f"{value:.1f}"
  mins, rem = divmod(int(round(value)), 60)
  return f"{mins}m {rem:02d}s"


def _group_timing(group_rows: List[TelemetryReading]) -> Tuple[Optional[float], float]:
  """Return (time_to_ok_s, span_s) from first to last packet; time_to_ok freezes at first OK."""
  ordered = sorted(group_rows, key=lambda r: r.timestamp)
  first = ordered[0].timestamp
  last = ordered[-1].timestamp
  span = max(0.0, (last - first).total_seconds())
  acc = ordered[0]
  time_to_ok: Optional[float] = None
  if acc.qualifies_ok():
    time_to_ok = 0.0
  else:
    for reading in ordered[1:]:
      acc = acc.merged_with(reading)
      if acc.qualifies_ok():
        time_to_ok = max(0.0, (reading.timestamp - first).total_seconds())
        break
  if time_to_ok is None:
    # Prefer acquire_seconds from live merge if present on latest merged sensor.
    for reading in reversed(ordered):
      if reading.acquire_seconds is not None:
        time_to_ok = float(reading.acquire_seconds)
        break
  return time_to_ok, span


def _result_status(reading: TelemetryReading) -> str:
  return "OK" if reading.qualifies_ok() else "NOK"


def _merged_sensor(group_rows: List[TelemetryReading]) -> TelemetryReading:
  acc = group_rows[0]
  for reading in group_rows[1:]:
    acc = acc.merged_with(reading)
  return acc


def _brand_type(reading: TelemetryReading) -> str:
  brand = (reading.model or "Unknown").strip() or "Unknown"
  kind = (reading.sensor_type or "").strip()
  if kind and kind.upper() != brand.upper():
    return f"{brand} / {kind}"
  return brand


def _sensor_id_sort_key(sensor_id: str) -> Tuple[int, int, str]:
  sid = str(sensor_id or "")
  if sid.isdigit():
    return (0, int(sid), sid)
  return (1, 0, sid.lower())


def _sorted_readings(readings: List[TelemetryReading]) -> List[TelemetryReading]:
  return sorted(
    readings,
    key=lambda r: (
      _sensor_id_sort_key(r.sensor_id),
      _brand_type(r).lower(),
      r.timestamp,
    ),
  )


def _round(val: Optional[float], digits: int) -> Optional[float]:
  if val is None:
    return None
  return round(float(val), digits)


def _style_header(ws: Worksheet, headers: List[str]) -> None:
  for col, title in enumerate(headers, start=1):
    cell = ws.cell(row=1, column=col, value=title)
    cell.fill = HEADER_FILL
    cell.font = HEADER_FONT
    cell.alignment = Alignment(horizontal="center")


def _set_widths(ws: Worksheet, widths: Dict[int, float]) -> None:
  for col, width in widths.items():
    ws.column_dimensions[get_column_letter(col)].width = width


def _iter_id_groups(readings: List[TelemetryReading]) -> Iterable[Tuple[str, List[TelemetryReading]]]:
  ordered = _sorted_readings(readings)
  for sensor_id, group in groupby(ordered, key=lambda r: r.sensor_id):
    yield sensor_id, list(group)


def _average_rows(readings: List[TelemetryReading]) -> List[List[Any]]:
  rows: List[List[Any]] = []
  for sensor_id, group_rows in _iter_id_groups(readings):
    psis = [r.psi for r in group_rows if r.psi is not None]
    temps = [r.temperature_c for r in group_rows if r.temperature_c is not None]
    brands: List[str] = []
    for reading in group_rows:
      label = _brand_type(reading)
      if label not in brands:
        brands.append(label)
    first_ts = min(r.timestamp for r in group_rows)
    last_ts = max(r.timestamp for r in group_rows)
    time_to_ok, span = _group_timing(group_rows)
    merged = _merged_sensor(group_rows)
    result = _result_status(merged)
    rows.append(
      [
        sensor_id,
        ", ".join(brands),
        len(group_rows),
        result,
        _round(fmean(psis), 2) if psis else None,
        _round(fmean(temps), 1) if temps else None,
        _round(min(psis), 2) if psis else None,
        _round(max(psis), 2) if psis else None,
        first_ts.strftime("%Y-%m-%d %H:%M:%S"),
        last_ts.strftime("%Y-%m-%d %H:%M:%S"),
        _round(time_to_ok, 1) if time_to_ok is not None else None,
        _round(span, 1),
        merged.nok_reason(),
      ]
    )
  return rows


def _write_averages_sheet(wb: Workbook, readings: List[TelemetryReading]) -> None:
  ws = wb.create_sheet("Averages")
  _style_header(ws, AVERAGE_HEADERS)
  for excel_row, row in enumerate(_average_rows(readings), start=2):
    status = str(row[3])
    fill = OK_FILL if status == "OK" else LOW_FILL if status == "NOK" else None
    for col, val in enumerate(row, start=1):
      cell = ws.cell(row=excel_row, column=col, value=val)
      if fill:
        cell.fill = fill
  _set_widths(
    ws,
    {1: 16, 2: 28, 3: 12, 4: 12, 5: 18, 6: 18, 7: 16, 8: 16, 9: 22, 10: 22, 11: 14, 12: 12, 13: 36},
  )
  ws.freeze_panes = "A2"
  ws.auto_filter.ref = f"A1:M{max(ws.max_row, 1)}"


def _write_readings_sheet(wb: Workbook, readings: List[TelemetryReading]) -> None:
  ws = wb.create_sheet("Readings")
  _style_header(ws, READING_HEADERS)

  for group_index, (sensor_id, group_rows) in enumerate(_iter_id_groups(readings)):
    if group_index > 0:
      ws.append([])
    brands: List[str] = []
    for reading in group_rows:
      label = _brand_type(reading)
      if label not in brands:
        brands.append(label)
    count = len(group_rows)
    time_to_ok, span = _group_timing(group_rows)
    title = f"Sensor ID: {sensor_id}"
    if brands:
      title = f"{title}  —  {', '.join(brands)}"
    title = (
      f"{title}  ({count} reading{'s' if count != 1 else ''}"
      f" · time to OK {_format_seconds(time_to_ok)} · span {_format_seconds(span)})"
    )
    ws.append([title])
    title_row = ws.max_row
    title_cell = ws.cell(row=title_row, column=1)
    title_cell.fill = PRIMARY_FILL
    title_cell.font = PRIMARY_FONT
    for col in range(2, len(READING_HEADERS) + 1):
      ws.cell(row=title_row, column=col).fill = PRIMARY_FILL

    first_ts = min(r.timestamp for r in group_rows)
    for reading in group_rows:
      result = _result_status(reading)
      fill = OK_FILL if result == "OK" else LOW_FILL
      since_first = max(0.0, (reading.timestamp - first_ts).total_seconds())
      values = [
        reading.sensor_id,
        reading.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        _brand_type(reading),
        result,
        _round(reading.psi, 2),
        _round(reading.temperature_c, 1),
        reading.display_battery,
        _round(since_first, 1),
        reading.nok_reason(),
      ]
      ws.append(values)
      excel_row = ws.max_row
      for col in range(1, len(values) + 1):
        ws.cell(row=excel_row, column=col).fill = fill

  _set_widths(ws, {1: 18, 2: 22, 3: 28, 4: 10, 5: 16, 6: 16, 7: 14, 8: 18, 9: 36})
  ws.freeze_panes = "A2"


def export_session_excel(
  readings: List[TelemetryReading],
  filepath: str | Path,
  meta: Optional[Dict[str, Any]] = None,
) -> Path:
  """Write session readings and per-sensor averages to an Excel workbook."""
  path = Path(filepath)
  meta = meta or {}
  snapshot = list(readings)

  wb = Workbook()
  info = wb.active
  info.title = "Session Info"
  info["A1"] = REPORT_KIND
  info["A1"].font = Font(bold=True, size=14)
  info["A2"] = REPORT_SUBTITLE
  info["A2"].font = Font(italic=True, size=10, color="64748B")
  info["A4"] = "Report type"
  info["B4"] = "SDR Receiver (RTL-SDR telemetry) — not TPMS Board"
  info["A5"] = "Exported"
  info["B5"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  for i, (key, val) in enumerate(meta.items(), start=6):
    info[f"A{i}"] = key
    info[f"B{i}"] = str(val)
  info.column_dimensions["A"].width = 28
  info.column_dimensions["B"].width = 52

  _write_averages_sheet(wb, snapshot)
  _write_readings_sheet(wb, snapshot)

  path.parent.mkdir(parents=True, exist_ok=True)
  wb.save(path)
  return path


def export_session_pdf(
  readings: List[TelemetryReading],
  filepath: str | Path,
  meta: Optional[Dict[str, Any]] = None,
) -> Path:
  """Write an SDR Receiver PDF report (not a TPMS board report)."""
  from reportlab.lib import colors
  from reportlab.lib.enums import TA_CENTER, TA_LEFT
  from reportlab.lib.pagesizes import A4
  from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
  from reportlab.lib.units import mm
  from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

  path = Path(filepath)
  meta = meta or {}
  snapshot = list(readings)
  avg_rows = _average_rows(snapshot)
  ok_n = sum(1 for row in avg_rows if row[3] == "OK")
  nok_n = sum(1 for row in avg_rows if row[3] == "NOK")
  path.parent.mkdir(parents=True, exist_ok=True)

  navy = colors.HexColor("#1A365D")
  accent = colors.HexColor("#2563EB")
  line = colors.HexColor("#D0D7E0")
  light = colors.HexColor("#EEF1F5")
  base = getSampleStyleSheet()
  title = ParagraphStyle(
    "sdr_title", parent=base["Title"], fontName="Helvetica-Bold",
    fontSize=20, textColor=navy, alignment=TA_CENTER, spaceAfter=4,
  )
  sub = ParagraphStyle(
    "sdr_sub", parent=base["Normal"], fontSize=10, textColor=accent,
    alignment=TA_CENTER, spaceAfter=12,
  )
  body = ParagraphStyle(
    "sdr_body", parent=base["Normal"], fontSize=9, textColor=navy,
    leading=12, alignment=TA_LEFT,
  )

  def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(navy)
    canvas.rect(0, A4[1] - 15 * mm, A4[0], 15 * mm, fill=1, stroke=0)
    canvas.setFillColor(accent)
    canvas.rect(0, A4[1] - 17 * mm, A4[0], 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(14 * mm, A4[1] - 10 * mm, "SDR Receiver Report  ·  RTL-SDR telemetry (not TPMS board)")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 14 * mm, A4[1] - 10 * mm, datetime.now().strftime("%Y-%m-%d %H:%M"))
    canvas.setFillColor(navy)
    canvas.rect(0, 0, A4[0], 11 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(14 * mm, 4.5 * mm, "SDR Receiver Report  ·  rtl_433 decode session  ·  not a board validation export")
    canvas.drawRightString(A4[0] - 14 * mm, 4.5 * mm, f"Page {doc.page}")
    canvas.restoreState()

  story = [
    Paragraph("SDR Receiver Report", title),
    Paragraph("RTL-SDR / rtl_433 telemetry session — this is not a TPMS board report", sub),
    Paragraph(
      f"<b>Report type:</b> SDR Receiver &nbsp;&nbsp; "
      f"<b>Readings:</b> {len(snapshot)} &nbsp;&nbsp; "
      f"<b>OK sensors:</b> {ok_n} &nbsp;&nbsp; "
      f"<b>NOK sensors:</b> {nok_n} &nbsp;&nbsp; "
      f"<b>Sensors:</b> {len(avg_rows)}",
      body,
    ),
    Spacer(1, 4 * mm),
  ]
  for key, val in meta.items():
    story.append(Paragraph(f"<b>{key}:</b> {val}", body))
  story.append(Spacer(1, 5 * mm))
  story.append(Paragraph("Per-sensor averages", ParagraphStyle("h", parent=base["Heading2"], textColor=navy, fontSize=13)))

  table_data = [["Sensor ID", "Brand/Type", "Readings", "Result", "Avg PSI", "Avg °C", "Time to OK", "Span", "NOK reason"]]
  for row in avg_rows:
    table_data.append(
      [
        str(row[0]),
        str(row[1]),
        str(row[2]),
        str(row[3]),
        "" if row[4] is None else f"{row[4]:.2f}",
        "" if row[5] is None else f"{row[5]:.1f}",
        _format_seconds(row[10]),
        _format_seconds(row[11]),
        str(row[12] or ""),
      ]
    )
  if len(table_data) == 1:
    table_data.append(["—"] * 9)
  tbl = Table(
    table_data,
    colWidths=[22 * mm, 30 * mm, 16 * mm, 14 * mm, 18 * mm, 16 * mm, 18 * mm, 16 * mm, 32 * mm],
    repeatRows=1,
  )
  tbl.setStyle(
    TableStyle(
      [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, -1), light),
        ("GRID", (0, 0), (-1, -1), 0.25, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
      ]
    )
  )
  story.append(tbl)

  doc = SimpleDocTemplate(
    str(path),
    pagesize=A4,
    leftMargin=12 * mm,
    rightMargin=12 * mm,
    topMargin=22 * mm,
    bottomMargin=16 * mm,
    title="SDR Receiver Report — RTL-SDR Telemetry",
  )
  doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
  return path

