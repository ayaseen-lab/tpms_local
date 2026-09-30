"""TPMS Board view — Hamaton bench UI as a CustomTkinter frame."""

from __future__ import annotations

import os
import platform
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

import customtkinter as ctk

from dialogs import ask_open_path, ask_save_path
from themes import (
    COLOR_BG,
    COLOR_BG_CARD,
    COLOR_BG_PANEL,
    COLOR_BLUE,
    COLOR_BLUE_BG,
    COLOR_BORDER,
    COLOR_BTN_EXPORT,
    COLOR_BTN_EXPORT_HOVER,
    COLOR_BTN_PAUSE,
    COLOR_BTN_PAUSE_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_BTN_PRIMARY_HOVER,
    COLOR_BTN_PRIMARY_TEXT,
    COLOR_BTN_SECONDARY,
    COLOR_BTN_SECONDARY_HOVER,
    COLOR_BTN_STOP,
    COLOR_BTN_STOP_HOVER,
    COLOR_CYAN_BG,
    COLOR_GREEN,
    COLOR_GREEN_BG,
    COLOR_HEADER_ACCENT,
    COLOR_HEADER_BG,
    COLOR_ORANGE,
    COLOR_ORANGE_BG,
    COLOR_RED,
    COLOR_RED_BG,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_TEXT_MUTED,
    combo_colors,
    entry_colors,
    ui_font,
)
from tpms_bench.excel_io import parse_code, stamp_board_report_info, vehicle_row_count
from tpms_bench.paths import app_root
from tpms_bench.report import build_pdf
from tpms_bench.runner import OUT_XLSX, SPEC_XLSX, BenchRunner, ManualCode, ProgressEvent, get_out_xlsx, reset_session_db
from tpms_bench.uart import default_port, find_serial_ports, port_device
from charts import BoardTrendCharts, ResultCharts
from widgets import StatCard

CODE_A_BG = "#E7F4F7"
CODE_A_FG = "#1B5F70"
CODE_B_BG = "#F8EFE6"
CODE_B_FG = "#8A4A1C"
CODE_C_BG = "#E8F7F4"
CODE_C_FG = "#14685E"
TELEMETRY_BG = "#E7F6EF"
TELEMETRY_FG = "#1A8F6E"
LED_IDLE = "#64748B"
LED_TTL_ON = "#34D399"
LED_JLINK_ON = "#FBBF24"

# In-repo Hamaton catalog — always loaded from data/ (tracked in git).
DEFAULT_HAMATON_XLSX = SPEC_XLSX if SPEC_XLSX.is_file() else (app_root() / "data" / "Hamaton_database_20260126_1305.xlsx")


def _fmt_batt(voltage: str | None, percentage: str | None = None) -> str:
    """Pretty battery for live labels — never show '0%' or bare 'na V'."""
    v = str(voltage or "").strip()
    p = str(percentage or "").strip()
    if v and v.lower() not in {"na", "n/a", "—", "-", "0", "0.0", "0.000"}:
        if v.upper() in {"OK", "LOW"}:
            return f"Batt {v}"
        if v.endswith("%"):
            return f"Batt {v}"
        try:
            return f"{float(v):.2f} V"
        except ValueError:
            return f"Batt {v}"
    if p and p.lower() not in {"na", "n/a", "—", "-", "0"}:
        try:
            n = int(float(p))
            if 1 <= n <= 100:
                return f"Batt {n}%"
        except ValueError:
            if p.endswith("%"):
                return f"Batt {p}"
    return "Batt —"


class _ControlState:
    """Stand-in for hidden RUN CHUNK / RUN FULL so Pause/Stop still track session state."""

    def __init__(self) -> None:
        self._state = "normal"

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self._state = kwargs["state"]

    def cget(self, key: str):
        if key == "state":
            return self._state
        return ""


class TpmsView(ctk.CTkFrame):
    """Board validation UI. Switching away from this frame does not stop the bench."""

    def __init__(
        self,
        master,
        on_status_change: Optional[Callable[[bool, str], None]] = None,
        on_chunk_complete: Optional[Callable[[str], None]] = None,
        chunk_var: Optional[tk.StringVar] = None,
        **kwargs,
    ):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self.on_status_change = on_status_change or (lambda _running, _label: None)
        self.on_chunk_complete = on_chunk_complete or (lambda _msg: None)
        self.on_board_rf: Callable | None = None
        self.on_board_trigger: Callable | None = None
        self.on_sdr_finalize: Callable | None = None
        self.chunk_var = chunk_var or tk.StringVar(value="100")

        self.queue: queue.Queue[ProgressEvent] = queue.Queue()
        self.runner: BenchRunner | None = None
        self.worker: threading.Thread | None = None
        self.is_paused = False
        self.start_time: float | None = None
        self.source_xlsx: Path | None = None
        self._total_rows = 0
        self._anim_step = 0
        self._state_label = "IDLE"
        self.custom_codes: list[ManualCode] = []
        self._sdr_agree = 0
        self._sdr_disagree = 0
        # Current Board session only — used by Comparative export (not stale SQLite history).
        self._session_rows: list[dict] = []

        self._setup_styles()
        self._build_ui()
        self._reset_display()
        # Session restore is deferred — CombinedApp asks Continue vs New Session at startup.
        self._autoload_default_excel()
        self.after(150, self._drain)
        self.after(80, self._animate_badge)
        self.after(900, self._poll_live_sdr)
        self._notify_status()
        self.live_sdr_get = None

    def _toplevel(self):
        return self.winfo_toplevel()

    def _setup_styles(self) -> None:
        style = ttk.Style(self._toplevel())
        style.theme_use("clam")
        style.configure(
            "Combined.Treeview",
            background=COLOR_BG,
            foreground=COLOR_TEXT,
            fieldbackground=COLOR_BG,
            rowheight=24,
            font=("Segoe UI", 10),
            bordercolor=COLOR_BORDER,
            borderwidth=0,
        )
        style.configure(
            "Combined.Treeview.Heading",
            background=COLOR_HEADER_BG,
            foreground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=6,
        )
        style.map(
            "Combined.Treeview.Heading",
            background=[("active", "#2C3538")],
            foreground=[("active", "#ffffff")],
        )
        style.map(
            "Combined.Treeview",
            background=[("selected", "#D6E8F5")],
            foreground=[("selected", COLOR_TEXT)],
            fieldbackground=[("", COLOR_BG)],
        )
        style.configure(
            "Combined.Vertical.TScrollbar",
            background="#C5CED8",
            troughcolor=COLOR_BG,
            arrowcolor=COLOR_HEADER_BG,
            bordercolor=COLOR_BORDER,
        )
        style.configure(
            "Combined.Horizontal.TScrollbar",
            background="#C5CED8",
            troughcolor=COLOR_BG,
            arrowcolor=COLOR_HEADER_BG,
            bordercolor=COLOR_BORDER,
        )

    def _build_ui(self) -> None:
        # Grid so the header never shrinks when the window is maximized.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=4, pady=(2, 4))
        self.status_var = ctk.StringVar(value="Ready · Select an Excel database and/or enter custom CODE A / B / C")
        ctk.CTkLabel(
            footer,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=10),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.ttl_led = ctk.CTkLabel(footer, text="● TTL", font=ctk.CTkFont(size=10, weight="bold"), text_color=LED_IDLE)
        self.ttl_led.pack(side="right", padx=(0, 4))
        self.rx_led = ctk.CTkLabel(footer, text="● Board RX", font=ctk.CTkFont(size=10, weight="bold"), text_color=LED_IDLE)
        self.rx_led.pack(side="right", padx=(8, 4))

        results = tk.Frame(self, bg=COLOR_BG, highlightbackground=COLOR_BORDER, highlightthickness=1)
        results.grid(row=4, column=0, sticky="ew", pady=(6, 2))

        table_header = tk.Frame(results, bg=COLOR_BG_PANEL)
        table_header.pack(fill="x")
        tk.Label(
            table_header,
            text="Live OK / NOK results",
            bg=COLOR_BG_PANEL,
            fg=COLOR_TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=8, pady=4)
        self.table_count_label = tk.Label(
            table_header, text="0 rows", bg=COLOR_BG_PANEL, fg=COLOR_TEXT_DIM, font=("Segoe UI", 9)
        )
        self.table_count_label.pack(side="right", padx=8)

        tree_host = tk.Frame(results, bg=COLOR_BG)
        tree_host.pack(fill="x", padx=4, pady=(0, 4))
        columns = (
            "row",
            "vehicle",
            "codes",
            "result",
            "id",
            "temp",
            "volt",
            "pressure",
            "rssi",
            "reason",
        )
        self.tree = ttk.Treeview(tree_host, columns=columns, show="headings", height=4, style="Combined.Treeview")
        headings = {
            "row": "#",
            "vehicle": "Vehicle",
            "codes": "CODE A / B / C",
            "result": "Board",
            "id": "Sensor ID",
            "temp": "°C",
            "volt": "Batt V",
            "pressure": "Pressure",
            "rssi": "RSSI",
            "reason": "Notes / NOK reason",
        }
        # Proportional weights for fitting without a horizontal scrollbar.
        self._tree_col_weights = {
            "row": 0.04,
            "vehicle": 0.14,
            "codes": 0.14,
            "result": 0.06,
            "id": 0.10,
            "temp": 0.05,
            "volt": 0.07,
            "pressure": 0.12,
            "rssi": 0.10,
            "reason": 0.18,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(
                col,
                width=80,
                minwidth=36,
                stretch=True,
                anchor="center" if col in ("row", "result", "id", "temp", "volt", "pressure", "rssi") else "w",
            )
        scroll_y = ttk.Scrollbar(
            tree_host, orient="vertical", command=self.tree.yview, style="Combined.Vertical.TScrollbar"
        )
        self.tree.configure(yscrollcommand=scroll_y.set)
        tree_host.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="ew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("OK", background=COLOR_GREEN_BG, foreground="#047857")
        self.tree.tag_configure("NOK", background=COLOR_RED_BG, foreground="#B91C1C")
        self.tree.tag_configure("SKIP", background=COLOR_BG_PANEL, foreground=COLOR_TEXT_MUTED)
        self.tree.tag_configure("flash", background=COLOR_CYAN_BG)
        self.tree.bind("<Configure>", self._fit_tree_columns, add="+")
        self.after(50, self._fit_tree_columns)

        # Stats must be reserved on the bottom stack BEFORE top panels pack,
        # otherwise PENDING / TESTED collapse to zero height.
        stats_anchor = ctk.CTkFrame(self, fg_color="transparent")
        stats_anchor.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        stats_row = ctk.CTkFrame(stats_anchor, fg_color="transparent")
        stats_row.pack(fill="x", pady=(0, 2))
        for i in range(5):
            stats_row.grid_columnconfigure(i, weight=1, minsize=96)
        self.stat_pending = StatCard(stats_row, "PENDING", "—", COLOR_ORANGE, COLOR_ORANGE_BG, compact=True)
        self.stat_pending.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stat_done = StatCard(stats_row, "TESTED", "0", COLOR_BLUE, COLOR_BLUE_BG, compact=True)
        self.stat_done.grid(row=0, column=1, sticky="ew", padx=4)
        self.stat_ok = StatCard(stats_row, "PASSED (OK)", "0", COLOR_GREEN, COLOR_GREEN_BG, compact=True)
        self.stat_ok.grid(row=0, column=2, sticky="ew", padx=4)
        self.stat_nok = StatCard(stats_row, "FAILED (NOK)", "0", COLOR_RED, COLOR_RED_BG, compact=True)
        self.stat_nok.grid(row=0, column=3, sticky="ew", padx=4)
        self.stat_rate = StatCard(stats_row, "PASS RATE", "0.0%", COLOR_HEADER_ACCENT, COLOR_CYAN_BG, compact=True)
        self.stat_rate.grid(row=0, column=4, sticky="ew", padx=(4, 0))

        prog_row = ctk.CTkFrame(stats_anchor, fg_color="transparent")
        prog_row.pack(fill="x")
        self.progress_label = ctk.CTkLabel(prog_row, text="Progress: 0.0% (0 of 0)", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
        self.progress_label.pack(side="left")
        self.elapsed_label = ctk.CTkLabel(prog_row, text="", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
        self.elapsed_label.pack(side="right")
        self.speed_label = ctk.CTkLabel(prog_row, text="", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
        self.speed_label.pack(side="right", padx=(0, 12))
        self.progress = ctk.CTkProgressBar(stats_anchor, height=6, progress_color=COLOR_GREEN, fg_color=COLOR_BORDER)
        self.progress.pack(fill="x", pady=(2, 4))
        self.progress.set(0)

        charts_anchor = ctk.CTkFrame(self, fg_color="transparent")
        charts_anchor.grid(row=2, column=0, sticky="nsew", pady=(0, 4))
        charts_anchor.grid_columnconfigure(0, weight=1)
        charts_anchor.grid_rowconfigure(0, weight=1)
        self.trend_charts = BoardTrendCharts(
            charts_anchor, height=78, title="Board trend graphs  ·  pass rate / cumulative / battery"
        )
        self.trend_charts.grid(row=0, column=0, sticky="nsew", pady=(0, 2))
        self.charts = ResultCharts(charts_anchor, height=70, title="Board results")
        self.charts.grid(row=1, column=0, sticky="ew")

        top = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_inner = ctk.CTkFrame(top, fg_color="transparent")
        top_inner.pack(fill="x", padx=12, pady=10)

        title_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(title_row, text="Fyrqom Board", font=ui_font(15, "bold"), text_color=COLOR_TEXT).pack(side="left")
        self.state_badge = ctk.CTkLabel(
            title_row, text="● IDLE", font=ui_font(12, "bold"), text_color=COLOR_TEXT_DIM
        )
        self.state_badge.pack(side="right")
        self.transport_var = ctk.StringVar(value="")
        ctk.CTkLabel(title_row, textvariable=self.transport_var, font=ui_font(11), text_color=COLOR_TEXT_DIM).pack(
            side="right", padx=(0, 12)
        )

        # Grid toolbar: buttons keep intrinsic size at any window width.
        # Run chunk / Run full / Chunk live only in the top nav — do not repeat them here.
        toolbar = ctk.CTkFrame(top_inner, fg_color=COLOR_BG_PANEL, corner_radius=8)
        toolbar.pack(fill="x", pady=(0, 8))
        toolbar.grid_columnconfigure(3, weight=1)

        # Board-only START lives here; Run chunk / Run full (Board+SDR) stay in the top nav.
        self.full_btn = _ControlState()
        self.start_btn = ctk.CTkButton(
            toolbar,
            text="START",
            width=96,
            height=32,
            font=ui_font(12, "bold"),
            fg_color=COLOR_BTN_PRIMARY,
            hover_color=COLOR_BTN_PRIMARY_HOVER,
            text_color=COLOR_BTN_PRIMARY_TEXT,
            corner_radius=8,
            command=lambda: self.start_test(skip_sdr=True, run_full=False),
        )
        self.start_btn.grid(row=0, column=0, padx=(8, 6), pady=8, sticky="w")
        self.pause_btn = ctk.CTkButton(
            toolbar,
            text="PAUSE",
            width=96,
            height=32,
            font=ui_font(12, "bold"),
            fg_color=COLOR_BTN_PAUSE,
            hover_color=COLOR_BTN_PAUSE_HOVER,
            text_color="#FFFFFF",
            corner_radius=8,
            state="disabled",
            command=self.toggle_pause,
        )
        self.pause_btn.grid(row=0, column=1, padx=(0, 6), pady=8, sticky="w")
        self.stop_btn = ctk.CTkButton(
            toolbar,
            text="STOP",
            width=88,
            height=32,
            font=ui_font(12, "bold"),
            fg_color=COLOR_BTN_STOP,
            hover_color=COLOR_BTN_STOP_HOVER,
            text_color="#FFFFFF",
            corner_radius=8,
            state="disabled",
            command=self.stop_test,
        )
        self.stop_btn.grid(row=0, column=2, padx=(0, 8), pady=8, sticky="w")

        ctk.CTkLabel(toolbar, text="Port", font=ui_font(11, "bold"), text_color=COLOR_TEXT_DIM).grid(
            row=0, column=7, padx=(8, 4), pady=8, sticky="e"
        )
        self.port_var = ctk.StringVar(value=default_port())
        self.port_combo = ctk.CTkComboBox(
            toolbar,
            values=find_serial_ports() or [default_port()],
            width=220,
            height=30,
            font=ui_font(11),
            **combo_colors(),
        )
        self.port_combo.set(self.port_var.get())
        self.port_combo.grid(row=0, column=8, padx=(0, 4), pady=8, sticky="e")
        ctk.CTkButton(
            toolbar,
            text="↻",
            width=34,
            height=30,
            font=ui_font(12, "bold"),
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            corner_radius=8,
            command=self._refresh_ports,
        ).grid(row=0, column=9, padx=(0, 10), pady=8, sticky="e")
        ctk.CTkButton(
            toolbar,
            text="Export Excel",
            width=112,
            height=30,
            font=ui_font(11, "bold"),
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            corner_radius=8,
            command=self.export_excel,
        ).grid(row=0, column=10, padx=(0, 6), pady=8, sticky="e")
        ctk.CTkButton(
            toolbar,
            text="Export PDF",
            width=104,
            height=30,
            font=ui_font(11, "bold"),
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            corner_radius=8,
            command=self.export_pdf,
        ).grid(row=0, column=11, padx=(0, 8), pady=8, sticky="e")

        file_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        file_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(file_row, text="Excel", font=ui_font(10, "bold"), text_color=COLOR_TEXT_DIM).pack(side="left")
        self.file_label = ctk.CTkLabel(file_row, text="No file selected", font=ui_font(11, "bold"), text_color=COLOR_ORANGE)
        self.file_label.pack(side="left", padx=(6, 10))
        ctk.CTkButton(
            file_row, text="Choose Excel…", width=120, height=28, font=ui_font(11, "bold"),
            fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER, corner_radius=8, command=self.select_excel,
        ).pack(side="left")
        ctk.CTkButton(
            file_row, text="Reset", width=70, height=28, font=ui_font(11),
            fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER, corner_radius=8, command=self.reset_session,
        ).pack(side="left", padx=(6, 0))

        code_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        code_row.pack(fill="x")
        self.manual_entries: dict[str, ctk.CTkEntry] = {}
        for key in ("A", "B", "C"):
            ctk.CTkLabel(code_row, text=f"CODE {key}", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
                side="left", padx=(0, 4)
            )
            entry = ctk.CTkEntry(code_row, width=120, height=28, placeholder_text=f"{key} hex", **entry_colors())
            entry.pack(side="left", padx=(0, 8))
            entry.bind("<Return>", lambda _e: self.add_custom_code())
            self.manual_entries[key] = entry
        self.manual_label_entry = ctk.CTkEntry(code_row, width=120, height=28, placeholder_text="label", **entry_colors())
        self.manual_label_entry.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            code_row, text="Add Code", width=90, height=28, font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_GREEN, hover_color="#15803d", command=self.add_custom_code,
        ).pack(side="left")
        self.codes_list = ctk.CTkFrame(top_inner, fg_color="transparent")
        self.codes_list.pack(fill="x", pady=(4, 0))
        self.codes_hint = ctk.CTkLabel(
            self.codes_list, text="No custom codes added yet.", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED, anchor="w"
        )
        self.codes_hint.pack(anchor="w")

        current = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        current.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        current_inner = ctk.CTkFrame(current, fg_color="transparent")
        current_inner.pack(fill="x", padx=8, pady=4)

        top_row = ctk.CTkFrame(current_inner, fg_color="transparent")
        top_row.pack(fill="x")
        self.vehicle_var = ctk.StringVar(value="Ready — choose an Excel database and/or enter custom codes")
        ctk.CTkLabel(
            top_row, textvariable=self.vehicle_var, font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT, anchor="w"
        ).pack(side="left")
        self.row_counter = ctk.CTkLabel(
            top_row, text="", font=ctk.CTkFont(size=10, weight="bold"), fg_color=COLOR_BLUE, text_color="white",
            corner_radius=5, width=84, height=20,
        )
        self.row_counter.pack(side="right")
        self.meta_var = ctk.StringVar(value="OE: —   ·   Supplier: —   ·   Freq: —")
        ctk.CTkLabel(current_inner, textvariable=self.meta_var, font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM, anchor="w").pack(
            anchor="w", pady=(0, 2)
        )

        codes = ctk.CTkFrame(current_inner, fg_color="transparent")
        codes.pack(fill="x")
        self.code_vars = {"A": ctk.StringVar(value="—"), "B": ctk.StringVar(value="—"), "C": ctk.StringVar(value="—")}
        for key, bg, fg, padx_right in (
            ("A", CODE_A_BG, CODE_A_FG, 4),
            ("B", CODE_B_BG, CODE_B_FG, 4),
            ("C", CODE_C_BG, CODE_C_FG, 0),
        ):
            box = ctk.CTkFrame(codes, fg_color=bg, corner_radius=5)
            box.pack(side="left", expand=True, fill="both", padx=(0, padx_right))
            inner = ctk.CTkFrame(box, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(
                inner, text=f"CODE {key}", font=ctk.CTkFont(size=8, weight="bold"), text_color=fg, anchor="w"
            ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                inner,
                textvariable=self.code_vars[key],
                font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                text_color=fg,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

        tel = ctk.CTkFrame(current_inner, fg_color=TELEMETRY_BG, corner_radius=5)
        tel.pack(fill="x", pady=(4, 0))
        tel_inner = ctk.CTkFrame(tel, fg_color="transparent")
        tel_inner.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(
            tel_inner,
            text="LIVE TELEMETRY",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=TELEMETRY_FG,
            anchor="w",
        ).pack(anchor="w")
        self.reading_var = ctk.StringVar(value="Waiting for first reading…")
        ctk.CTkLabel(
            tel_inner,
            textvariable=self.reading_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TELEMETRY_FG,
            anchor="w",
            justify="left",
        ).pack(fill="x", anchor="w", pady=(1, 0))

    def _refresh_ports(self) -> None:
        ports = find_serial_ports() or [default_port()]
        self.port_combo.configure(values=ports)
        if self.port_combo.get() not in ports:
            self.port_combo.set(ports[0])
            self.port_var.set(ports[0])

    def _refresh_ready_banner(self) -> None:
        if self.source_xlsx and self.source_xlsx.is_file():
            n = vehicle_row_count(self.source_xlsx)
            port = port_device(self.port_combo.get()) or port_device(default_port()) or "COM?"
            if n > 0:
                self.vehicle_var.set(
                    f"{self.source_xlsx.name} — {n:,} vehicles loaded · use Run chunk / Run full (top bar)"
                )
                self.status_var.set(f"Ready on {port} — {n:,} catalog rows · waiting for Run")
            else:
                self.vehicle_var.set(f"{self.source_xlsx.name} loaded — no catalog rows found")
                self.status_var.set(f"Ready on {port} — check Excel or add custom codes")
        else:
            self.vehicle_var.set("Ready — choose an Excel database and/or enter custom codes")
            self.status_var.set("Choose an Excel database and/or enter custom CODE A / B / C")

    def _reset_display(self) -> None:
        self._update_stat_labels(pending=0, done=0, ok=0, nok=0, total=0)
        self.meta_var.set("OE: —   ·   Supplier: —   ·   Freq: —")
        self.row_counter.configure(text="")
        self.reading_var.set("Waiting for first reading…")
        for key in self.code_vars:
            self.code_vars[key].set("—")
        self.progress.set(0)
        self.progress_label.configure(text="Progress: 0.0% (0 of 0)")
        self.speed_label.configure(text="")
        self.elapsed_label.configure(text="")
        self._refresh_table_count()
        self._refresh_ready_banner()

    def _fit_tree_columns(self, _event=None) -> None:
        """Stretch live columns to the tree width so no horizontal scrollbar is needed."""
        if not hasattr(self, "tree"):
            return
        try:
            width = int(self.tree.winfo_width())
        except tk.TclError:
            return
        if width < 80:
            return
        # Leave a little room for the vertical scrollbar border.
        usable = max(200, width - 4)
        weights = getattr(self, "_tree_col_weights", None) or {}
        total_w = sum(weights.values()) or 1.0
        for col, weight in weights.items():
            col_w = max(36, int(usable * (weight / total_w)))
            self.tree.column(col, width=col_w)

    def _refresh_table_count(self) -> None:
        n = len(self.tree.get_children())
        if hasattr(self, "table_count_label"):
            self.table_count_label.configure(text=f"{n} row{'s' if n != 1 else ''}")

    def _note_sdr_compare(self, sdr_compare: str) -> None:
        cmp = (sdr_compare or "").strip().upper()
        if cmp in {"", "PENDING", "NA", "N/A"}:
            return
        if cmp == "SUCCESS":
            self._sdr_agree += 1
        elif cmp == "FAIL":
            self._sdr_disagree += 1

    def _clear_readings(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._sdr_agree = 0
        self._sdr_disagree = 0
        self._session_rows.clear()
        self._refresh_table_count()
        if hasattr(self, "charts"):
            self.charts.reset()
        if hasattr(self, "trend_charts"):
            self.trend_charts.reset()

    def _record_session_row(self, event: ProgressEvent) -> None:
        perf = str(event.performance or "").strip().upper()
        if perf not in ("OK", "NOK"):
            return
        sid = str(event.sensor_id or "").strip()
        if sid.lower() in {"na", "n/a", "none", "-", "—"}:
            sid = ""
        self._session_rows.append(
            {
                "sensor_id": sid,
                "board_performance": perf,
                "nok_reason": str(event.reason or ""),
                "sdr_compare": str(event.sdr_compare or ""),
                "sdr_reason": str(event.sdr_reason or ""),
                "excel_row": int(event.excel_row or 0),
                "make": str(event.make or ""),
                "model": str(event.model or ""),
                "duration_s": event.duration_s,
            }
        )

    def get_tested_rows(self) -> list[dict]:
        """Board rows for comparative analysis — current session, else SQLite resume."""
        if self._session_rows:
            return list(self._session_rows)
        return self._hydrate_session_rows_from_db()

    def _hydrate_session_rows_from_db(self) -> list[dict]:
        """Reload Board OK/NOK rows from bench.sqlite so Compare survives a restart."""
        try:
            from tpms_bench.results_db import connect, fetch_all
            from tpms_bench.runner import DB_PATH
        except Exception:
            return []
        if not DB_PATH.exists():
            return []
        try:
            db = connect(DB_PATH)
            rows = fetch_all(db)
            db.close()
        except Exception:
            return []
        hydrated: list[dict] = []
        for row in rows:
            perf = str(row["board_performance"] or "").strip().upper()
            if perf not in ("OK", "NOK"):
                continue
            sid = str(row["sensor_id"] or "").strip()
            if sid.lower() in {"na", "n/a", "none", "-", "—"}:
                sid = ""
            hydrated.append(
                {
                    "sensor_id": sid,
                    "board_performance": perf,
                    "nok_reason": str(row["nok_reason"] or ""),
                    "sdr_compare": str(row["sdr_compare"] or ""),
                    "sdr_reason": str(row["sdr_reason"] or ""),
                    "excel_row": int(row["excel_row"] or 0),
                    "make": str(row["make"] or ""),
                    "model": str(row["model"] or ""),
                    "duration_s": row["duration_s"],
                    "_db_row": row,
                }
            )
        if hydrated and not self._session_rows:
            # Store without the private _db_row helper for Compare consumers.
            self._session_rows = [
                {k: v for k, v in item.items() if k != "_db_row"} for item in hydrated
            ]
        return list(self._session_rows) if self._session_rows else []

    def _restore_session_from_db(self) -> int:
        """Repopulate the live Board table from SQLite after an app restart."""
        try:
            from tpms_bench.results_db import connect, counts, fetch_all
            from tpms_bench.runner import DB_PATH
        except Exception:
            return 0
        if not DB_PATH.exists():
            return 0
        try:
            db = connect(DB_PATH)
            rows = fetch_all(db)
            stats = counts(db)
            db.close()
        except Exception:
            return 0
        if not rows:
            return 0

        self._session_rows.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        shown = 0
        for row in rows:
            perf = str(row["board_performance"] or "").strip().upper()
            if perf not in ("OK", "NOK", "SKIP"):
                continue
            sid = str(row["sensor_id"] or "").strip()
            if sid.lower() in {"na", "n/a", "none", "-", "—"}:
                sid_disp = "na"
                sid = ""
            else:
                sid_disp = sid
            make = str(row["make"] or "")
            model = str(row["model"] or "")
            code_a = str(row["code_a"] or "")
            code_b = str(row["code_b"] or "")
            code_c = str(row["code_c"] or "")
            temp = str(row["temperature"] or "na")
            volt = _fmt_batt(
                str(row["battery_voltage"] or ""),
                str(row["battery_percentage"] or ""),
            ).removeprefix("Batt ").strip() or "na"
            press = str(row["pressure"] if "pressure" in row.keys() else "na") or "na"
            rssi = str(row["rssi"] if "rssi" in row.keys() else "na") or "na"
            reason = str(row["nok_reason"] or "")
            excel_row = int(row["excel_row"] or 0)
            self.tree.insert(
                "",
                0,
                values=(
                    excel_row,
                    f"{make} {model}".strip(),
                    f"{code_a}  {code_b}  {code_c}".strip(),
                    perf,
                    sid_disp,
                    temp,
                    volt,
                    press,
                    rssi,
                    reason,
                ),
                tags=(perf,),
            )
            shown += 1
            if perf in ("OK", "NOK"):
                self._session_rows.append(
                    {
                        "sensor_id": sid,
                        "board_performance": perf,
                        "nok_reason": reason,
                        "sdr_compare": str(row["sdr_compare"] or ""),
                        "sdr_reason": str(row["sdr_reason"] or ""),
                        "excel_row": excel_row,
                        "make": make,
                        "model": model,
                        "duration_s": row["duration_s"],
                    }
                )
            self._note_sdr_compare(str(row["sdr_compare"] or ""))

        done = int(stats.get("done") or shown)
        ok = int(stats.get("OK") or 0)
        nok = int(stats.get("NOK") or 0)
        self._update_stat_labels(pending=0, done=done, ok=ok, nok=nok, total=done)
        self._refresh_table_count()
        if hasattr(self, "charts"):
            history = [str(r.get("board_performance") or "") for r in self._session_rows]
            self.charts.set_counts(ok, nok, history)
        if hasattr(self, "trend_charts"):
            history = [str(r.get("board_performance") or "") for r in self._session_rows]
            volts: list[float] = []
            temps: list[float] = []
            for row in rows:
                try:
                    v = str(row["battery_voltage"] or "").strip()
                    if v and v.lower() not in {"na", "n/a", "—", "-", "ok", "low"}:
                        volts.append(float(v))
                except (TypeError, ValueError):
                    pass
                try:
                    t = str(row["temperature"] or "").strip()
                    if t and t.lower() not in {"na", "n/a", "—", "-"}:
                        temps.append(float(t))
                except (TypeError, ValueError):
                    pass
            self.trend_charts.set_from_history(results=history, voltages=volts, temps=temps)
        return shown

    def focus_code_fields(self) -> None:
        try:
            self.manual_entries["A"].focus_set()
        except Exception:
            pass

    def _entry_text(self, entry: ctk.CTkEntry) -> str:
        value = (entry.get() or "").strip()
        try:
            placeholder = str(entry.cget("placeholder_text") or "")
        except Exception:
            placeholder = ""
        if placeholder and value == placeholder:
            return ""
        return value

    def _read_manual_fields(self, *, require_complete: bool) -> ManualCode | None:
        values = {key: self._entry_text(self.manual_entries[key]) for key in ("A", "B", "C")}
        filled = [v for v in values.values() if v]
        if not filled:
            return None
        if len(filled) != 3:
            if require_complete:
                messagebox.showinfo(
                    "Custom opcodes",
                    "Enter CODE A, CODE B and CODE C together before adding.",
                    parent=self._toplevel(),
                )
                raise ValueError("incomplete custom codes")
            return None
        for key, raw in values.items():
            if parse_code(raw) is None:
                messagebox.showinfo("Custom opcodes", f"CODE {key} is not a valid hex opcode: {raw}", parent=self._toplevel())
                raise ValueError("invalid custom code")
        label = self._entry_text(self.manual_label_entry) or f"Manual code {len(self.custom_codes) + 1}"
        return ManualCode(code_a=values["A"].upper(), code_b=values["B"].upper(), code_c=values["C"].upper(), label=label)

    def add_custom_code(self) -> None:
        try:
            extra = self._read_manual_fields(require_complete=True)
        except ValueError:
            return
        if extra is None:
            messagebox.showinfo("Custom opcodes", "Type CODE A, CODE B and CODE C, then click Add Code.", parent=self._toplevel())
            return
        self.custom_codes.append(extra)
        for entry in self.manual_entries.values():
            entry.delete(0, "end")
        self.manual_label_entry.delete(0, "end")
        self._refresh_codes_list()
        self.status_var.set(f"Added custom code {extra.label}: {extra.code_a} / {extra.code_b} / {extra.code_c}")
        self.focus_code_fields()

    def _remove_custom_code(self, index: int) -> None:
        if 0 <= index < len(self.custom_codes):
            removed = self.custom_codes.pop(index)
            self._refresh_codes_list()
            self.status_var.set(f"Removed custom code {removed.label}")

    def _refresh_codes_list(self) -> None:
        for child in self.codes_list.winfo_children():
            child.destroy()
        if not self.custom_codes:
            self.codes_hint = ctk.CTkLabel(
                self.codes_list,
                text="No custom codes added yet.",
                font=ctk.CTkFont(size=10),
                text_color=COLOR_TEXT_MUTED,
                anchor="w",
            )
            self.codes_hint.pack(anchor="w")
            return
        for index, code in enumerate(self.custom_codes):
            row = ctk.CTkFrame(self.codes_list, fg_color=COLOR_CYAN_BG, corner_radius=6)
            row.pack(side="left", padx=(0, 6), pady=2)
            ctk.CTkLabel(
                row,
                text=f"{code.label}: {code.code_a}/{code.code_b}/{code.code_c}",
                font=ctk.CTkFont(family="Consolas", size=11),
                text_color=COLOR_TEXT,
            ).pack(side="left", padx=(8, 4), pady=3)
            ctk.CTkButton(
                row,
                text="×",
                width=28,
                height=22,
                font=ctk.CTkFont(size=12),
                fg_color=COLOR_BTN_SECONDARY,
                hover_color=COLOR_BTN_SECONDARY_HOVER,
                command=lambda i=index: self._remove_custom_code(i),
            ).pack(side="right", padx=(0, 4), pady=2)

    def select_excel(self) -> None:
        path = ask_open_path(
            "Select TPMS Board Excel database (opcodes)",
            [("Excel files", "*.xlsx"), ("All files", "*.*")],
            parent=self._toplevel(),
        )
        if not path:
            return
        self._load_excel(Path(path))

    def _load_excel(self, path: Path) -> None:
        self.source_xlsx = path
        self.file_label.configure(text=self.source_xlsx.name, text_color=COLOR_GREEN)
        self._refresh_ready_banner()

    def _autoload_default_excel(self) -> None:
        """Preselect Hamaton catalog (or FYRQOM_SOURCE_XLSX override) so a run can start."""
        if self.source_xlsx:
            return
        override = os.environ.get("FYRQOM_SOURCE_XLSX", "").strip()
        if override:
            path = Path(override).expanduser()
            if not path.is_absolute():
                path = app_root() / path
            if path.is_file():
                self._load_excel(path)
                return
        if DEFAULT_HAMATON_XLSX.is_file():
            self._load_excel(DEFAULT_HAMATON_XLSX)

    def previous_session_count(self) -> int:
        """How many Board OK/NOK rows are stored from the last session."""
        try:
            from tpms_bench.results_db import connect, fetch_all
            from tpms_bench.runner import DB_PATH
        except Exception:
            return 0
        if not DB_PATH.exists():
            return 0
        try:
            db = connect(DB_PATH)
            rows = fetch_all(db)
            db.close()
        except Exception:
            return 0
        return sum(1 for row in rows if str(row["board_performance"] or "").strip().upper() in {"OK", "NOK"})

    def restore_previous_session(self) -> int:
        """Hydrate the Board table from SQLite. Returns restored row count."""
        restored = self._restore_session_from_db()
        if restored:
            self.status_var.set(f"Restored {restored} Board result row(s) from last session")
            self._set_state_badge("IDLE")
        return restored

    def clear_session_silent(self) -> None:
        """Clear Board results without a confirmation dialog (startup New Session)."""
        try:
            reset_session_db()
        except Exception:
            pass
        if self.source_xlsx and self.source_xlsx.is_file():
            try:
                from tpms_bench.excel_io import copy_workbook
                from tpms_bench.runner import OUT_XLSX

                copy_workbook(self.source_xlsx, OUT_XLSX, force=True)
            except Exception:
                pass
        self._clear_readings()
        self._reset_display()
        self._set_state_badge("IDLE")
        self.status_var.set("New session — previous Board results cleared")

    def reset_session(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Session Active", "Stop the current test before resetting.", parent=self._toplevel())
            return
        if not messagebox.askyesno("Reset Session", "Clear all TPMS Board results and reset counters?", parent=self._toplevel()):
            return
        reset_session_db()
        if self.source_xlsx and self.source_xlsx.is_file():
            try:
                from tpms_bench.excel_io import copy_workbook
                from tpms_bench.runner import OUT_XLSX

                copy_workbook(self.source_xlsx, OUT_XLSX, force=True)
            except Exception:
                pass
        self._clear_readings()
        self._reset_display()
        self._set_state_badge("IDLE")

    def selected_chunk_size(self) -> int:
        try:
            return max(1, int(self.chunk_var.get()))
        except (TypeError, ValueError):
            return 100

    def start_test(self, *, skip_sdr: bool = True, chunk_size: int | None = None, run_full: bool = False) -> bool:
        """Start the Board bench. Returns False if start was blocked (e.g. no Excel/codes)."""
        if self.worker and self.worker.is_alive():
            if self.is_paused and self.runner:
                self.toggle_pause()
            return True

        extra_codes = list(self.custom_codes)
        try:
            typed = self._read_manual_fields(require_complete=bool(self._entry_text(self.manual_entries["A"]) or self._entry_text(self.manual_entries["B"]) or self._entry_text(self.manual_entries["C"])))
        except ValueError:
            return False
        if typed:
            extra_codes.append(typed)

        if (not self.source_xlsx or not self.source_xlsx.exists()) and not extra_codes:
            messagebox.showinfo(
                "Select Excel or add codes",
                "Choose an Excel database and/or add custom CODE A / B / C before starting.",
                parent=self._toplevel(),
            )
            return False

        # Keep existing Board results — only "Reset Session" clears. Resume unfinished rows.
        if not self._session_rows:
            self._hydrate_session_rows_from_db()
        self.is_paused = False
        self.start_time = time.monotonic()
        self.start_btn.configure(state="disabled")
        if hasattr(self, "full_btn"):
            self.full_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="PAUSE")
        self.stop_btn.configure(state="normal")
        self._set_state_badge("RUNNING")

        size = 0 if run_full else (chunk_size if chunk_size is not None else self.selected_chunk_size())
        port = port_device(self.port_combo.get()) or port_device(default_port())
        self.runner = BenchRunner(
            port=port,
            source_xlsx=self.source_xlsx,
            resume=True,
            skip_sdr=skip_sdr,
            sdr_timeout=float(__import__("os").environ.get("FYRQOM_SDR_TIMEOUT", "8")),
            extra_codes=extra_codes,
            on_progress=self.queue.put,
            chunk_size=size,
            retest_from=None,
            require_agree=False,
            agree_retries=1,
            live_sdr_get=self.live_sdr_get,
        )
        if skip_sdr:
            self.status_var.set(
                f"Starting TPMS Board test · USB-TTL on {port} · "
                "SDR Receiver handles RF (Board live IQ capture off so the dongle is free)…"
            )
        else:
            self.status_var.set(
                f"Starting TPMS Board test · USB-TTL on {port} · live SDR compare = "
                "ID + OK/NOK in trigger window (PSI/°C may differ; stop SDR Receiver if dongle busy)…"
            )
        self.worker = threading.Thread(target=self._run_safe, daemon=True, name="tpms-board")
        self.worker.start()
        return True

    def toggle_pause(self) -> None:
        if not self.runner or not self.worker or not self.worker.is_alive():
            return
        if not self.is_paused:
            self.runner.pause()
            self.is_paused = True
            self.pause_btn.configure(text="RESUME")
            self._set_state_badge("PAUSED")
        else:
            self.runner.resume_run()
            self.is_paused = False
            self.pause_btn.configure(text="PAUSE")
            self._set_state_badge("RUNNING")

    def stop_test(self) -> None:
        if self.runner:
            self.runner.request_stop()
        self.stop_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled", text="PAUSE")
        self.is_paused = False
        self._set_state_badge("STOPPED")
        self.status_var.set("Stopping — aborting COM wait…")
        # If the worker is stuck opening/using a bad COM port, force UI recovery soon.
        self.after(800, self._ensure_stopped_ui)

    def _ensure_stopped_ui(self) -> None:
        """Recover controls if stop was requested but the worker never finished cleanly."""
        if self.worker and self.worker.is_alive():
            self.after(400, self._ensure_stopped_ui)
            return
        if self.start_btn.cget("state") == "disabled":
            self.start_btn.configure(state="normal")
            if hasattr(self, "full_btn"):
                self.full_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled", text="PAUSE")
            self.stop_btn.configure(state="disabled")
            self.is_paused = False
            if self._state_label in ("RUNNING", "PAUSED"):
                self._set_state_badge("STOPPED")
            self.status_var.set("Stopped")

    def _set_state_badge(self, text: str) -> None:
        self._state_label = text
        colors = {
            "RUNNING": COLOR_GREEN,
            "PAUSED": COLOR_ORANGE,
            "STOPPED": COLOR_TEXT_DIM,
            "COMPLETED": COLOR_BLUE,
            "IDLE": COLOR_TEXT_DIM,
            "ERROR": COLOR_RED,
        }
        sym = {"RUNNING": "●", "PAUSED": "❚❚", "STOPPED": "■", "COMPLETED": "✔", "IDLE": "●", "ERROR": "✕"}.get(text, "●")
        self.state_badge.configure(text=f"{sym}  {text}", text_color=colors.get(text, COLOR_TEXT_DIM))
        self._notify_status()

    def _notify_status(self) -> None:
        running = self._state_label in ("RUNNING", "PAUSED")
        try:
            self.on_status_change(running, self._state_label)
        except Exception:
            pass

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _push_tpms_range(self, event: ProgressEvent) -> None:
        # Soft-fill voltage/temp into trend hist without counting a result (row_done does that).
        if hasattr(self, "trend_charts"):
            volt = None
            temp = None
            try:
                v_raw = str(getattr(event, "voltage", "") or "").strip()
                if v_raw and v_raw.lower() not in {"na", "n/a", "—", "-"}:
                    volt = float(v_raw)
            except (TypeError, ValueError):
                volt = None
            try:
                t_raw = str(getattr(event, "temperature", "") or "").strip()
                if t_raw and t_raw.lower() not in {"na", "n/a", "—", "-"}:
                    temp = float(t_raw)
            except (TypeError, ValueError):
                temp = None
            if volt is None and temp is None:
                return
            try:
                self.trend_charts.push(voltage=volt, temp=temp)
            except Exception:
                pass

    def _poll_live_sdr(self) -> None:
        """Show SDR packets on the telemetry bar so a silent Board still looks alive."""
        try:
            snap = self.live_sdr_get() if self.live_sdr_get else None
        except Exception:
            snap = None
        if snap:
            latest = None
            for reading in snap.values():
                ts = getattr(reading, "timestamp", None)
                if latest is None or (ts and getattr(latest, "timestamp", None) and ts > latest.timestamp):
                    latest = reading
            if latest is None:
                latest = next(iter(snap.values()), None)
            if latest is not None:
                sid = getattr(latest, "sensor_id", None) or "—"
                temp = getattr(latest, "display_temp", None) or "—"
                psi = getattr(latest, "display_pressure", None) or "—"
                rssi = getattr(latest, "display_rssi", None) or "—"
                self.reading_var.set(
                    f"SDR  {sid}  ·  {temp}  ·  {psi}  ·  RSSI {rssi}  ·  {len(snap)} ID(s) live"
                )
        try:
            delay = 400 if self.winfo_ismapped() else 1200
        except tk.TclError:
            delay = 1200
        self.after(delay, self._poll_live_sdr)

    def _animate_badge(self) -> None:
        if self._state_label == "RUNNING":
            self._anim_step = (self._anim_step + 1) % 20
            pulse = abs(10 - (self._anim_step % 20))
            green = "#1A8A6C" if pulse > 4 else "#3EC9A5"
            self.state_badge.configure(text_color=green)
            if hasattr(self, "progress"):
                try:
                    self.progress.configure(progress_color=green)
                except Exception:
                    pass
        self.after(90, self._animate_badge)

    def _run_safe(self) -> None:
        try:
            assert self.runner is not None
            self.runner.run()
        except Exception as error:
            message = str(error)
            low = message.lower()
            if "permission denied" in low or "[errno 13]" in low:
                message = (
                    "Cannot write the Board results Excel — it is open in another program "
                    "(usually Microsoft Excel).\n\n"
                    "Close that file, then press START again.\n\n"
                    f"({error})"
                )
            self.queue.put(ProgressEvent(kind="error", message=message))

    def _open_file(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo("File Not Found", str(path), parent=self._toplevel())
            return
        if platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def export_excel(self) -> None:
        out = get_out_xlsx() if get_out_xlsx().exists() else OUT_XLSX
        if not out.exists():
            messagebox.showinfo("TPMS Board Report (Excel)", "No TPMS Board results yet. Run a test first.", parent=self._toplevel())
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = ask_save_path(
            "Save TPMS Board Report (Excel) — Hamaton bench, not SDR receiver",
            f"TPMS_Board_Report_{stamp}.xlsx",
            [("Excel — TPMS Board Report", "*.xlsx"), ("All files", "*.*")],
            ".xlsx",
            parent=self._toplevel(),
        )
        if not dest:
            return
        try:
            stamp_board_report_info(out)
            shutil.copy2(out, dest)
            self.status_var.set(f"TPMS Board Report (Excel) saved: {Path(dest).name}")
            messagebox.showinfo(
                "TPMS Board Report (Excel)",
                f"TPMS Board Report (Excel) saved.\n\nThis file is Hamaton board validation, not an SDR receiver report.\n\n{dest}",
                parent=self._toplevel(),
            )
            self._open_file(Path(dest))
        except Exception as error:
            messagebox.showerror("TPMS Board Report (Excel)", str(error), parent=self._toplevel())

    def export_pdf(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = ask_save_path(
            "Save TPMS Board Report (PDF) — Hamaton bench, not SDR receiver",
            f"TPMS_Board_Report_{stamp}.pdf",
            [("PDF — TPMS Board Report", "*.pdf"), ("All files", "*.*")],
            ".pdf",
            parent=self._toplevel(),
        )
        if not dest:
            return
        try:
            saved = build_pdf(Path(dest))
            self.status_var.set(f"TPMS Board Report (PDF) saved: {saved.name}")
            messagebox.showinfo(
                "TPMS Board Report (PDF)",
                f"TPMS Board Report (PDF) saved.\n\nThis file is Hamaton board validation, not an SDR receiver report.\n\n{saved}",
                parent=self._toplevel(),
            )
            self._open_file(saved)
        except Exception as error:
            messagebox.showerror("TPMS Board Report (PDF)", str(error), parent=self._toplevel())

    def _drain(self) -> None:
        # Cap work per tick so SDR UI timers still run while the Board is busy.
        try:
            for _ in range(40):
                self._apply(self.queue.get_nowait())
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _flash_row(self, item_id: str, tag: str, step: int = 0) -> None:
        # Skip animation under load — flashing every row freezes the UI (and SDR).
        if step == 0 and len(self.queue.queue) > 5:
            try:
                if self.tree.exists(item_id):
                    self.tree.item(item_id, tags=(tag,))
            except tk.TclError:
                pass
            return
        if not self.tree.exists(item_id):
            return
        try:
            if step < 2:
                self.tree.item(item_id, tags=("flash",))
                self.after(50, lambda i=item_id, t=tag, s=step + 1: self._flash_row(i, t, s))
            else:
                self.tree.item(item_id, tags=(tag,))
        except tk.TclError:
            pass

    def _end_session(self, label: str, message: str) -> None:
        self.start_btn.configure(state="normal")
        if hasattr(self, "full_btn"):
            self.full_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="PAUSE")
        self.stop_btn.configure(state="disabled")
        self.is_paused = False
        self._set_state_badge(label)
        try:
            out = get_out_xlsx()
            if out.exists():
                stamp_board_report_info(out)
            build_pdf()
        except Exception:
            pass
        self.status_var.set(message)

    def _blink_led(self, widget: ctk.CTkLabel, active_color: str) -> None:
        widget.configure(text_color=active_color)
        self.after(350, lambda: widget.configure(text_color=LED_IDLE))

    def _apply(self, event: ProgressEvent) -> None:
        if event.kind == "comm":
            if event.path == "ttl":
                self._blink_led(self.ttl_led, LED_TTL_ON)
            elif event.path in ("uart", "jlink"):
                if event.path == "uart":
                    self.rx_led.configure(text="● USB RX")
                    self._blink_led(self.rx_led, LED_TTL_ON)
                else:
                    self.rx_led.configure(text="● J-Link")
                    self._blink_led(self.rx_led, LED_JLINK_ON)
            elif event.message:
                self.status_var.set(event.message)
            return

        if event.kind == "started":
            self._total_rows = event.total
            self._set_state_badge("RUNNING")
            if event.transport:
                self.transport_var.set(event.transport)
                t = event.transport.upper()
                if "USB-TTL TX/RX" in t or "USB-TTL RX" in t:
                    self.rx_led.configure(text="● USB RX")
                elif "J-LINK" in t:
                    self.rx_led.configure(text="● J-Link")
                else:
                    self.rx_led.configure(text="● Board RX")
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            self.status_var.set(event.message)

        elif event.kind == "row_start":
            self.vehicle_var.set(f"{event.make} {event.model} ({event.year})" if event.year else f"{event.make} {event.model}")
            self.meta_var.set(f"OE: {event.oe or '—'}  ·  Supplier: {event.supplier or '—'}  ·  Freq: {event.freq or '—'}")
            self.row_counter.configure(text=f"Row {event.excel_row} / {event.total}")
            self.code_vars["A"].set(event.code_a or "—")
            self.code_vars["B"].set(event.code_b or "—")
            self.code_vars["C"].set(event.code_c or "—")
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            self.status_var.set(f"Testing row {event.excel_row}: {event.make} {event.model} · {event.pending} pending")
            if self.on_board_trigger:
                try:
                    self.on_board_trigger(
                        sensor_id=str(event.sensor_id or ""),
                        excel_row=event.excel_row,
                        vehicle=f"{event.make} {event.model}".strip(),
                    )
                except Exception:
                    pass

        elif event.kind == "board_ok":
            # Board ABC finished — show reading now; SDR decode may still be in flight.
            if event.sensor_id and event.sensor_id != "na":
                batt = _fmt_batt(event.voltage, event.battery_percentage)
                self.reading_var.set(
                    f"ID  {event.sensor_id}  ·  {event.temperature} °C  ·  {batt}"
                )
            self._push_tpms_range(event)
            perf = (event.performance or "").upper()
            self.status_var.set(
                event.message
                or (
                    f"Row {event.excel_row} Board {perf or '—'} — "
                    "waiting rtl_433 before next ABC…"
                )
            )
            self._note_sdr_compare("PENDING")
            if self.on_board_rf and event.sensor_id and str(event.sensor_id).lower() not in {"na", "n/a"}:
                try:
                    self.on_board_rf(
                        event.sensor_id,
                        excel_row=event.excel_row,
                        vehicle=f"{event.make} {event.model}".strip(),
                        temperature=event.temperature,
                        voltage=event.voltage,
                        pressure=event.pressure,
                        board_result=event.performance or "OK",
                    )
                except Exception:
                    pass
            if self.on_board_trigger:
                try:
                    self.on_board_trigger(
                        sensor_id=str(event.sensor_id or ""),
                        excel_row=event.excel_row,
                        vehicle=f"{event.make} {event.model}".strip(),
                    )
                except Exception:
                    pass

        elif event.kind == "row_done":
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            if event.sensor_id and event.sensor_id != "na":
                self.reading_var.set(
                    f"ID  {event.sensor_id}  ·  {event.temperature} °C  ·  "
                    f"{event.pressure or 'P na'}  ·  RSSI {event.rssi or 'na'}  ·  "
                    f"{_fmt_batt(event.voltage, event.battery_percentage)}"
                )
            self._push_tpms_range(event)
            item = self.tree.insert(
                "",
                0,
                values=(
                    event.excel_row,
                    f"{event.make} {event.model}".strip(),
                    f"{event.code_a}  {event.code_b}  {event.code_c}".strip(),
                    event.performance,
                    event.sensor_id or "na",
                    event.temperature or "na",
                    _fmt_batt(event.voltage, event.battery_percentage).removeprefix("Batt ").strip() or "na",
                    event.pressure or "na",
                    event.rssi or "na",
                    event.reason or event.message or "",
                ),
                tags=(event.performance or "SKIP",),
            )
            self._flash_row(item, event.performance or "SKIP")
            self.tree.see(item)
            self._record_session_row(event)
            self._note_sdr_compare(event.sdr_compare)
            self._refresh_table_count()
            if hasattr(self, "charts"):
                self.charts.add_result(event.performance or "")
            if hasattr(self, "trend_charts"):
                volt = None
                temp = None
                try:
                    v_raw = str(getattr(event, "voltage", "") or "").strip()
                    if v_raw and v_raw.lower() not in {"na", "n/a", "—", "-"}:
                        volt = float(v_raw)
                except (TypeError, ValueError):
                    volt = None
                try:
                    t_raw = str(getattr(event, "temperature", "") or "").strip()
                    if t_raw and t_raw.lower() not in {"na", "n/a", "—", "-"}:
                        temp = float(t_raw)
                except (TypeError, ValueError):
                    temp = None
                try:
                    self.trend_charts.push(
                        result=event.performance or "",
                        voltage=volt,
                        temp=temp,
                    )
                except Exception:
                    pass
            # Stamp final rtl_433 library decoder (or SDR FAIL) onto the Board match row.
            finalize = getattr(self.sdr_view if hasattr(self, "sdr_view") else None, "finalize_board_match", None)
            # Combined shell wires on_board_rf; finalize via optional callback.
            finalize_cb = getattr(self, "on_sdr_finalize", None)
            if callable(finalize_cb):
                try:
                    finalize_cb(
                        excel_row=event.excel_row,
                        sensor_id=event.sensor_id,
                        decoder=event.rtl433_decoder,
                        sdr_compare=event.sdr_compare,
                        sdr_reason=event.sdr_reason,
                    )
                except Exception:
                    pass
            sdr = (event.sdr_compare or "").upper()
            self.status_var.set(
                f"Row {event.excel_row} Board {event.performance or '—'} · SDR {sdr or '—'} "
                f"— next ABC…"
            )

        elif event.kind == "stopping":
            self._set_state_badge("STOPPED")
            self.status_var.set(event.message or "Stopping…")

        elif event.kind == "chunk_complete":
            self.is_paused = True
            self.pause_btn.configure(text="RESUME")
            self._set_state_badge("PAUSED")
            self.status_var.set(event.message or "Chunk complete — review Comparison")
            self.after(80, lambda: self.on_chunk_complete(event.message or ""))

        elif event.kind == "finished":
            self._end_session("COMPLETED", event.message)

        elif event.kind == "stopped":
            self._end_session("STOPPED", event.message)

        elif event.kind == "error":
            # If operator already hit Stop, treat COM/open failures as a clean stop.
            if self._state_label == "STOPPED" or (self.runner and self.runner.stop_flag):
                self._end_session("STOPPED", event.message or "Stopped")
            else:
                self.start_btn.configure(state="normal")
                if hasattr(self, "full_btn"):
                    self.full_btn.configure(state="normal")
                self.pause_btn.configure(state="disabled", text="PAUSE")
                self.stop_btn.configure(state="disabled")
                self.is_paused = False
                self._set_state_badge("ERROR")
                messagebox.showerror("TPMS Board Error", event.message, parent=self._toplevel())
                self.status_var.set(event.message or "Error")

    def _update_stat_labels(self, pending: int, done: int, ok: int, nok: int, total: int) -> None:
        self.stat_pending.set_value(str(pending))
        self.stat_done.set_value(str(done))
        self.stat_ok.set_value(str(ok))
        self.stat_nok.set_value(str(nok))
        self.stat_rate.set_value(f"{(ok / done * 100.0) if done else 0.0:.1f}%")
        if total > 0:
            pct = done / total
            self.progress.set(min(1.0, pct))
            self.progress_label.configure(text=f"Progress: {pct * 100:.1f}% ({done} of {total})")
            if self.start_time and done > 0:
                elapsed_s = time.monotonic() - self.start_time
                mins, secs = divmod(int(elapsed_s), 60)
                rate = done / (elapsed_s / 60.0) if elapsed_s > 0 else 0
                self.speed_label.configure(text=f"{rate:.1f} tests/min")
                self.elapsed_label.configure(text=f"Elapsed: {mins}:{secs:02d}")
        else:
            self.progress.set(0)

    def shutdown(self) -> None:
        if self.runner:
            self.runner.request_stop()
