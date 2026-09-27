"""SQLite result store for resume and PASS/FAIL history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    excel_row INTEGER PRIMARY KEY,
    make TEXT,
    model TEXT,
    oe TEXT,
    supplier TEXT,
    code_a TEXT,
    code_b TEXT,
    code_c TEXT,
    board_performance TEXT,
    nok_reason TEXT,
    battery_percentage TEXT,
    battery_voltage TEXT,
    sdr_compare TEXT,
    sdr_reason TEXT,
    rtl433_decoder TEXT,
    iq_file TEXT,
    sensor_id TEXT,
    frequency TEXT,
    pressure TEXT,
    temperature TEXT,
    duration_s TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    _ensure_columns(conn)
    conn.commit()
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(runs)")}
    if "duration_s" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN duration_s TEXT")
    if "rtl433_decoder" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN rtl433_decoder TEXT")


def completed_rows(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute(
        "SELECT excel_row FROM runs WHERE board_performance IN ('OK','NOK','SKIP')"
    ).fetchall()
    return {int(r[0]) for r in rows}


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT board_performance, COUNT(*) FROM runs GROUP BY board_performance"
    ).fetchall()
    out = {"OK": 0, "NOK": 0, "SKIP": 0}
    for name, n in rows:
        if name in out:
            out[name] = int(n)
    out["done"] = out["OK"] + out["NOK"] + out["SKIP"]
    return out


def clear_all(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM runs")
    conn.commit()


def clear_from_row(conn: sqlite3.Connection, excel_row: int) -> int:
    """Drop saved results from excel_row onward so a chunk can be retested."""
    cur = conn.execute("DELETE FROM runs WHERE excel_row >= ?", (int(excel_row),))
    conn.commit()
    return int(cur.rowcount or 0)


def fetch_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute("SELECT * FROM runs ORDER BY excel_row")
    )


def upsert(conn: sqlite3.Connection, record: dict) -> None:
    columns = ",".join(record.keys())
    placeholders = ",".join(":" + key for key in record)
    updates = ",".join(f"{key}=excluded.{key}" for key in record if key != "excel_row")
    conn.execute(
        f"INSERT INTO runs ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(excel_row) DO UPDATE SET {updates}",
        record,
    )
    conn.commit()
