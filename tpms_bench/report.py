"""Client PDF: successful CODE A/B/C communications only. No SDR."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .results_db import connect, counts, fetch_all
from .runner import DB_PATH, PDF_PATH

NAVY = colors.HexColor("#0A1F33")
ORANGE = colors.HexColor("#D9782A")
GREEN = colors.HexColor("#1A7A4C")
LIGHT = colors.HexColor("#EEF1F5")
OK_BG = colors.HexColor("#E6F6EC")
CARD = colors.HexColor("#FFF8F0")
LINE = colors.HexColor("#D0D7E0")


def _hex_id(value: object) -> str:
    text = str(value or "").strip().upper().replace(" ", "")
    if len(text) == 8 and all(c in "0123456789ABCDEF" for c in text):
        return text
    return ""


def communicated(row) -> bool:
    return bool(_hex_id(row["sensor_id"]))


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, textColor=NAVY, alignment=TA_CENTER, spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Normal"], fontSize=11, textColor=ORANGE,
            alignment=TA_CENTER, spaceAfter=16,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Heading2"], textColor=NAVY, fontSize=14,
            spaceBefore=12, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=9.5, textColor=NAVY,
            leading=13, alignment=TA_LEFT,
        ),
        "tiny": ParagraphStyle(
            "tiny", parent=base["Normal"], fontSize=8, textColor=NAVY, leading=10,
        ),
        "card": ParagraphStyle(
            "card", parent=base["Normal"], fontSize=9, textColor=NAVY,
            leading=12, alignment=TA_CENTER,
        ),
    }


def _header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 15 * mm, A4[0], 15 * mm, fill=1, stroke=0)
    canvas.setFillColor(ORANGE)
    canvas.rect(0, A4[1] - 17 * mm, A4[0], 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(14 * mm, A4[1] - 10 * mm, "TPMS Board Report  ·  Hamaton bench (not SDR)")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 14 * mm, A4[1] - 10 * mm, datetime.now().strftime("%Y-%m-%d %H:%M"))
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, A4[0], 11 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(14 * mm, 4.5 * mm, "TPMS Board Report  ·  USB-TTL TX / RX  ·  not an SDR receiver export")
    canvas.drawRightString(A4[0] - 14 * mm, 4.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(dest: Path | None = None) -> Path:
    dest = dest or PDF_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    db = connect(DB_PATH)
    stats = counts(db)
    rows = fetch_all(db)
    db.close()

    success = [r for r in rows if communicated(r)]
    unique_codes: dict[tuple[str, str, str], list] = defaultdict(list)
    for row in success:
        unique_codes[(row["code_a"], row["code_b"], row["code_c"])].append(row)

    first = next((r for r in rows if r["board_performance"] == "OK"), None) or (
        success[0] if success else None
    )
    styles = _styles()

    story: list = []
    story.append(Paragraph("TPMS Board Report", styles["title"]))
    story.append(
        Paragraph(
            "Hamaton board validation — CODE A / B / C communication (this is not an SDR receiver report)",
            styles["sub"],
        )
    )

    cards = [
        ["Live sensor ID", _hex_id(first["sensor_id"]) if first else "—"],
        ["Codes that replied", str(len(unique_codes))],
        ["Vehicles in this report", str(len(success))],
        ["Board OK", str(stats["OK"])],
    ]
    card_table = Table(cards, colWidths=[45 * mm] * 4)
    card_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD),
                ("BOX", (0, 0), (-1, -1), 0.6, ORANGE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#F6AD55")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, 1), 13),
                ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(card_table)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("1. First confirmed sensor reading", styles["h"]))
    if first:
        story.append(
            Paragraph(
                f"<b>{first['make']} {first['model']}</b> &nbsp; OE {first['oe']} &nbsp; "
                f"{first['supplier']}<br/>"
                f"<b>CODE A</b> {first['code_a']} &nbsp; <b>CODE B</b> {first['code_b']} "
                f"&nbsp; <b>CODE C</b> {first['code_c']}<br/>"
                f"<b>ID</b> {_hex_id(first['sensor_id'])} &nbsp; "
                f"<b>Frequency</b> {first['frequency']} MHz &nbsp; "
                f"<b>Temperature</b> {first['temperature']} °C &nbsp; "
                f"<b>Pressure</b> {first['pressure']} &nbsp; "
                f"<b>RSSI</b> {first['rssi'] if 'rssi' in first.keys() else 'na'} &nbsp; "
                f"<b>Battery</b> {first['battery_voltage']} V",
                styles["body"],
            )
        )
    else:
        story.append(Paragraph("No live reading stored yet.", styles["body"]))

    story.append(Paragraph("2. How this bench talks to the board", styles["h"]))
    story.append(
        Paragraph(
            "Each Excel row that is not INDIRECT sends CODE A, CODE B and CODE C. "
            "The board programs a <b>new unique Sensor ID (OEID)</b> for every row, "
            "LF-activates, then reads ID, frequency, pressure, temperature and battery. "
            "Board OK requires the RF readback to match that programmed ID — proof the "
            "sensor accepted the new protocol/ID. "
            "<b>USB-TTL RX is tried first.</b> If the adapter has no RX, the board "
            "reply is read from on-board memory. "
            "This report lists only rows where the board returned a sensor ID — "
            "those are the codes we could communicate with.",
            styles["body"],
        )
    )

    story.append(Paragraph("3. Unique CODE A / B / C that communicated", styles["h"]))
    code_header = ["CODE A", "CODE B", "CODE C", "Supplier", "Vehicles", "ID", "Temp", "Battery"]
    code_data = [code_header]
    for (a, b, c), group in sorted(unique_codes.items(), key=lambda item: item[1][0]["make"]):
        sample = group[0]
        suppliers = ", ".join(sorted({str(g["supplier"]) for g in group}))
        code_data.append(
            [
                a, b, c, suppliers, str(len(group)),
                _hex_id(sample["sensor_id"]),
                f"{sample['temperature']} °C",
                f"{sample['battery_voltage']} V",
            ]
        )
    if len(code_data) == 1:
        code_data.append(["—"] * 8)
    code_table = Table(code_data, colWidths=[24 * mm, 24 * mm, 24 * mm, 32 * mm, 18 * mm, 22 * mm, 18 * mm, 22 * mm])
    code_style = [
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (2, -1), "Courier-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, -1), OK_BG),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("ALIGN", (4, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    code_table.setStyle(TableStyle(code_style))
    story.append(code_table)

    story.append(PageBreak())
    story.append(Paragraph("4. Every vehicle that returned telemetry", styles["h"]))
    story.append(
        Paragraph(
            "These rows used the listed codes and the board answered with a sensor ID. "
            "Board OK means program + LF + full read. Other green-tint rows still "
            "exchanged UART and produced a reading.",
            styles["body"],
        )
    )

    veh_header = [
        "#", "Vehicle", "OE", "Supplier", "CODE A", "CODE B", "CODE C",
        "ID", "rtl_433 Decoder", "MHz", "°C", "P", "V", "Board", "Time",
    ]
    veh_data = [veh_header]
    for row in success:
        dur_raw = row["duration_s"] if "duration_s" in row.keys() else None
        try:
            dur_s = float(dur_raw) if dur_raw not in (None, "", "na") else None
        except (TypeError, ValueError, KeyError):
            dur_s = None
        if dur_s is None:
            dur_txt = "—"
        elif dur_s < 60:
            dur_txt = f"{dur_s:.0f}s"
        else:
            mins, secs = divmod(int(round(dur_s)), 60)
            dur_txt = f"{mins}m {secs:02d}s"
        decoder = "—"
        try:
            raw_dec = row["rtl433_decoder"] if "rtl433_decoder" in row.keys() else None
            if raw_dec not in (None, "", "na"):
                decoder = str(raw_dec)
        except (KeyError, IndexError, TypeError):
            decoder = "—"
        veh_data.append(
            [
                str(row["excel_row"]),
                Paragraph(f"{row['make']} {row['model']}", styles["tiny"]),
                Paragraph(str(row["oe"] or ""), styles["tiny"]),
                str(row["supplier"] or ""),
                str(row["code_a"]),
                str(row["code_b"]),
                str(row["code_c"]),
                _hex_id(row["sensor_id"]),
                Paragraph(decoder, styles["tiny"]),
                str(row["frequency"] if row["frequency"] not in (None, "na") else "—"),
                str(row["temperature"] if row["temperature"] not in (None, "na") else "—"),
                str(row["pressure"] if row["pressure"] not in (None, "na") else "—"),
                str(row["battery_voltage"] if row["battery_voltage"] not in (None, "na") else "—"),
                str(row["board_performance"]),
                dur_txt,
            ]
        )
    if len(veh_data) == 1:
        veh_data.append(["—"] * 15)

    # Portrait table may be tight — use slightly smaller columns
    veh_table = Table(
        veh_data,
        colWidths=[
            8 * mm, 22 * mm, 14 * mm, 12 * mm, 14 * mm, 14 * mm, 14 * mm,
            14 * mm, 28 * mm, 8 * mm, 8 * mm, 7 * mm, 9 * mm, 10 * mm, 10 * mm,
        ],
        repeatRows=1,
    )
    veh_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), 6),
        ("FONTNAME", (4, 1), (7, -1), "Courier"),
        ("GRID", (0, 0), (-1, -1), 0.2, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (7, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
    ]
    for i, row in enumerate(success, start=1):
        bg = OK_BG if row["board_performance"] == "OK" else colors.HexColor("#B2F5EA")
        veh_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        if row["board_performance"] == "OK":
            veh_cmds.append(("FONTNAME", (13, i), (13, i), "Helvetica-Bold"))
            veh_cmds.append(("TEXTCOLOR", (13, i), (13, i), GREEN))
    veh_table.setStyle(TableStyle(veh_cmds))
    story.append(KeepTogether([veh_table]))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("5. Run status", styles["h"]))
    pending = max(0, 1742 - stats["done"])
    status = [
        ["Board OK", str(stats["OK"]), "Program, LF activate and full telemetry"],
        ["Communicated", str(len(success)), "Any row that returned a sensor ID"],
        ["Unique code triples", str(len(unique_codes)), "Distinct CODE A/B/C that answered"],
        ["Rows finished", str(stats["done"]), f"{pending} vehicle rows still pending"],
    ]
    st = Table(status, colWidths=[40 * mm, 28 * mm, 114 * mm])
    st.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), NAVY),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
                ("FONTNAME", (0, 0), (1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (1, 0), (1, -1), CARD),
                ("GRID", (0, 0), (-1, -1), 0.3, LINE),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(st)

    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=22 * mm,
        bottomMargin=16 * mm,
        title="TPMS Board Report — Hamaton Validation Bench",
    )
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return dest
