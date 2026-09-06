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
)
from tpms_bench.excel_io import parse_code, stamp_board_report_info
from tpms_bench.report import build_pdf
from tpms_bench.runner import OUT_XLSX, BenchRunner, ManualCode, ProgressEvent, reset_session_db
from tpms_bench.uart import default_port, find_serial_ports
from widgets import StatCard

CODE_A_BG = "#E0F2FE"
CODE_A_FG = "#0369A1"
CODE_B_BG = "#FEF3C7"
CODE_B_FG = "#B45309"
CODE_C_BG = "#CCFBF1"
CODE_C_FG = "#0F766E"
TELEMETRY_BG = "#ECFDF5"
TELEMETRY_FG = "#059669"
LED_IDLE = "#64748B"
LED_TTL_ON = "#34D399"
LED_JLINK_ON = "#FBBF24"


class TpmsView(ctk.CTkFrame):
    """Board validation UI. Switching away from this frame does not stop the bench."""

    def __init__(self, master, on_status_change: Optional[Callable[[bool, str], None]] = None, **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self.on_status_change = on_status_change or (lambda _running, _label: None)

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
        self.after(150, self._drain)
        self.after(80, self._animate_badge)
        self._notify_status()

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
            background=[("active", "#12263A")],
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
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=4, pady=(2, 4))
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
        self.rx_led = ctk.CTkLabel(footer, text="● Board", font=ctk.CTkFont(size=10, weight="bold"), text_color=LED_IDLE)
        self.rx_led.pack(side="right", padx=(8, 4))

        results = tk.Frame(self, bg=COLOR_BG, highlightbackground=COLOR_BORDER, highlightthickness=1)
        results.pack(side="bottom", fill="x", pady=(6, 2))

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
            "reason",
        )
        self.tree = ttk.Treeview(tree_host, columns=columns, show="headings", height=6, style="Combined.Treeview")
        headings = {
            "row": "#",
            "vehicle": "Vehicle",
            "codes": "CODE A / B / C",
            "result": "Board",
            "id": "Sensor ID",
            "temp": "°C",
            "volt": "Batt V",
            "reason": "Notes / NOK reason",
        }
        # Proportional weights for fitting without a horizontal scrollbar.
        self._tree_col_weights = {
            "row": 0.05,
            "vehicle": 0.18,
            "codes": 0.18,
            "result": 0.07,
            "id": 0.12,
            "temp": 0.06,
            "volt": 0.08,
            "reason": 0.26,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(
                col,
                width=80,
                minwidth=36,
                stretch=True,
                anchor="center" if col in ("row", "result", "id", "temp", "volt") else "w",
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

        top = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        top.pack(fill="x", pady=(0, 6))
        top_inner = ctk.CTkFrame(top, fg_color="transparent")
        top_inner.pack(fill="x", padx=10, pady=8)

        title_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(title_row, text="TPMS Board", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_TEXT).pack(side="left")
        self.state_badge = ctk.CTkLabel(
            title_row, text="● IDLE", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT_DIM
        )
        self.state_badge.pack(side="right")
        self.transport_var = ctk.StringVar(value="")
        ctk.CTkLabel(title_row, textvariable=self.transport_var, font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM).pack(
            side="right", padx=(0, 12)
        )

        actions_inner = ctk.CTkFrame(top_inner, fg_color="transparent")
        actions_inner.pack(fill="x", pady=(0, 6))
        self.start_btn = ctk.CTkButton(
            actions_inner, text="START TEST", width=130, height=34, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER, command=self.start_test,
        )
        self.start_btn.pack(side="left", padx=(0, 6))
        self.pause_btn = ctk.CTkButton(
            actions_inner, text="PAUSE", width=90, height=34, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLOR_BTN_PAUSE, hover_color=COLOR_BTN_PAUSE_HOVER, state="disabled", command=self.toggle_pause,
        )
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ctk.CTkButton(
            actions_inner, text="STOP", width=90, height=34, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLOR_BTN_STOP, hover_color=COLOR_BTN_STOP_HOVER, state="disabled", command=self.stop_test,
        )
        self.stop_btn.pack(side="left")

        # Exports sit furthest right; Port sits left of them (separated from START/PAUSE/STOP).
        ctk.CTkButton(
            actions_inner, text="Export Board PDF", width=140, height=30, font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_EXPORT, hover_color=COLOR_BTN_EXPORT_HOVER, command=self.export_pdf,
        ).pack(side="right")
        ctk.CTkButton(
            actions_inner, text="Export Board Excel", width=150, height=30, font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_EXPORT, hover_color=COLOR_BTN_EXPORT_HOVER, command=self.export_excel,
        ).pack(side="right", padx=(0, 6))

        port_group = ctk.CTkFrame(actions_inner, fg_color="transparent")
        port_group.pack(side="right", padx=(24, 20))
        ctk.CTkLabel(port_group, text="Port", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
            side="left", padx=(0, 6)
        )
        self.port_var = ctk.StringVar(value=default_port())
        self.port_combo = ctk.CTkComboBox(
            port_group, values=find_serial_ports() or [default_port()], width=130, height=30, **combo_colors()
        )
        self.port_combo.set(self.port_var.get())
        self.port_combo.pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            port_group, text="↻", width=32, height=30, fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._refresh_ports,
        ).pack(side="left")

        file_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        file_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(file_row, text="Excel", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(side="left")
        self.file_label = ctk.CTkLabel(file_row, text="No file selected", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_ORANGE)
        self.file_label.pack(side="left", padx=(6, 10))
        ctk.CTkButton(
            file_row, text="Choose Excel…", width=120, height=28, font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER, command=self.select_excel,
        ).pack(side="left")
        ctk.CTkButton(
            file_row, text="Reset", width=70, height=28, font=ctk.CTkFont(size=11),
            fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER, command=self.reset_session,
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
        current.pack(fill="x", pady=(0, 6))
        current_inner = ctk.CTkFrame(current, fg_color="transparent")
        current_inner.pack(fill="x", padx=10, pady=8)

        top_row = ctk.CTkFrame(current_inner, fg_color="transparent")
        top_row.pack(fill="x")
        self.vehicle_var = ctk.StringVar(value="Ready — choose an Excel database and/or enter custom codes")
        ctk.CTkLabel(
            top_row, textvariable=self.vehicle_var, font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_TEXT, anchor="w"
        ).pack(side="left")
        self.row_counter = ctk.CTkLabel(
            top_row, text="", font=ctk.CTkFont(size=11, weight="bold"), fg_color=COLOR_BLUE, text_color="white",
            corner_radius=6, width=90,
        )
        self.row_counter.pack(side="right")
        self.meta_var = ctk.StringVar(value="OE: —   ·   Supplier: —   ·   Freq: —")
        ctk.CTkLabel(current_inner, textvariable=self.meta_var, font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM, anchor="w").pack(
            anchor="w", pady=(2, 4)
        )

        codes = ctk.CTkFrame(current_inner, fg_color="transparent")
        codes.pack(fill="x")
        self.code_vars = {"A": ctk.StringVar(value="—"), "B": ctk.StringVar(value="—"), "C": ctk.StringVar(value="—")}
        for key, bg, fg, padx_right in (
            ("A", CODE_A_BG, CODE_A_FG, 6),
            ("B", CODE_B_BG, CODE_B_FG, 6),
            ("C", CODE_C_BG, CODE_C_FG, 0),
        ):
            box = ctk.CTkFrame(codes, fg_color=bg, corner_radius=6)
            box.pack(side="left", expand=True, fill="both", padx=(0, padx_right))
            inner = ctk.CTkFrame(box, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(
                inner, text=f"CODE {key}", font=ctk.CTkFont(size=9, weight="bold"), text_color=fg, anchor="w"
            ).pack(side="left", padx=(0, 10))
            ctk.CTkLabel(
                inner,
                textvariable=self.code_vars[key],
                font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
                text_color=fg,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

        tel = ctk.CTkFrame(current_inner, fg_color=TELEMETRY_BG, corner_radius=6)
        tel.pack(fill="x", pady=(8, 0))
        tel_inner = ctk.CTkFrame(tel, fg_color="transparent")
        tel_inner.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(
            tel_inner,
            text="LIVE TELEMETRY",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TELEMETRY_FG,
            anchor="w",
        ).pack(anchor="w")
        self.reading_var = ctk.StringVar(value="Waiting for first reading…")
        ctk.CTkLabel(
            tel_inner,
            textvariable=self.reading_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TELEMETRY_FG,
            anchor="w",
            justify="left",
        ).pack(fill="x", anchor="w", pady=(2, 0))

        stats_row = ctk.CTkFrame(self, fg_color="transparent")
        stats_row.pack(fill="x", pady=(0, 4))
        for i in range(5):
            stats_row.grid_columnconfigure(i, weight=1)
        self.stat_pending = StatCard(stats_row, "PENDING", "—", COLOR_ORANGE, COLOR_ORANGE_BG, compact=True)
        self.stat_pending.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.stat_done = StatCard(stats_row, "TESTED", "0", COLOR_BLUE, COLOR_BLUE_BG, compact=True)
        self.stat_done.grid(row=0, column=1, sticky="nsew", padx=4)
        self.stat_ok = StatCard(stats_row, "PASSED (OK)", "0", COLOR_GREEN, COLOR_GREEN_BG, compact=True)
        self.stat_ok.grid(row=0, column=2, sticky="nsew", padx=4)
        self.stat_nok = StatCard(stats_row, "FAILED (NOK)", "0", COLOR_RED, COLOR_RED_BG, compact=True)
        self.stat_nok.grid(row=0, column=3, sticky="nsew", padx=4)
        self.stat_rate = StatCard(stats_row, "PASS RATE", "0.0%", COLOR_HEADER_ACCENT, COLOR_CYAN_BG, compact=True)
        self.stat_rate.grid(row=0, column=4, sticky="nsew", padx=(4, 0))

        prog_row = ctk.CTkFrame(self, fg_color="transparent")
        prog_row.pack(fill="x")
        self.progress_label = ctk.CTkLabel(prog_row, text="Progress: 0.0% (0 of 0)", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
        self.progress_label.pack(side="left")
        self.elapsed_label = ctk.CTkLabel(prog_row, text="", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
        self.elapsed_label.pack(side="right")
        self.speed_label = ctk.CTkLabel(prog_row, text="", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED)
        self.speed_label.pack(side="right", padx=(0, 12))
        self.progress = ctk.CTkProgressBar(self, height=6, progress_color=COLOR_GREEN, fg_color=COLOR_BORDER)
        self.progress.pack(fill="x", pady=(2, 6))
        self.progress.set(0)

    def _refresh_ports(self) -> None:
        ports = find_serial_ports() or [default_port()]
        self.port_combo.configure(values=ports)
        if self.port_combo.get() not in ports:
            self.port_combo.set(ports[0])
            self.port_var.set(ports[0])

    def _reset_display(self) -> None:
        self._update_stat_labels(pending=0, done=0, ok=0, nok=0, total=0)
        self.vehicle_var.set("Ready — choose an Excel database and/or enter custom codes")
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
        """Board rows for comparative analysis — current session only (matches live table)."""
        return list(self._session_rows)

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
        self.source_xlsx = Path(path)
        self.file_label.configure(text=self.source_xlsx.name, text_color=COLOR_GREEN)
        self.status_var.set(f"Database loaded: {self.source_xlsx.name} — add custom codes if needed, then Start Test")

    def reset_session(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Session Active", "Stop the current test before resetting.", parent=self._toplevel())
            return
        if not messagebox.askyesno("Reset Session", "Clear all TPMS Board results and reset counters?", parent=self._toplevel()):
            return
        reset_session_db()
        self._clear_readings()
        self._reset_display()
        self._set_state_badge("IDLE")

    def start_test(self, *, skip_sdr: bool = False) -> bool:
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

        reset_session_db()
        self._clear_readings()
        self._reset_display()
        self.is_paused = False
        self.start_time = time.monotonic()
        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="PAUSE")
        self.stop_btn.configure(state="normal")
        self._set_state_badge("RUNNING")

        port = self.port_combo.get().strip() or default_port()
        self.runner = BenchRunner(
            port=port,
            source_xlsx=self.source_xlsx,
            resume=False,
            skip_sdr=skip_sdr,
            extra_codes=extra_codes,
            on_progress=self.queue.put,
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

    def _animate_badge(self) -> None:
        if self._state_label == "RUNNING":
            self._anim_step = (self._anim_step + 1) % 16
            self.state_badge.configure(text_color=COLOR_GREEN if self._anim_step < 8 else "#86EFAC")
        self.after(120, self._animate_badge)

    def _run_safe(self) -> None:
        try:
            assert self.runner is not None
            self.runner.run()
        except Exception as error:
            self.queue.put(ProgressEvent(kind="error", message=str(error)))

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
        if not OUT_XLSX.exists():
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
            stamp_board_report_info(OUT_XLSX)
            shutil.copy2(OUT_XLSX, dest)
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
        try:
            while True:
                self._apply(self.queue.get_nowait())
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _flash_row(self, item_id: str, tag: str, step: int = 0) -> None:
        if not self.tree.exists(item_id):
            return
        try:
            if step < 3:
                self.tree.item(item_id, tags=("flash",))
                self.after(70, lambda i=item_id, t=tag, s=step + 1: self._flash_row(i, t, s))
            else:
                self.tree.item(item_id, tags=(tag,))
        except tk.TclError:
            pass

    def _end_session(self, label: str, message: str) -> None:
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="PAUSE")
        self.stop_btn.configure(state="disabled")
        self.is_paused = False
        self._set_state_badge(label)
        try:
            if OUT_XLSX.exists():
                stamp_board_report_info(OUT_XLSX)
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
            elif event.path == "jlink":
                self._blink_led(self.rx_led, LED_JLINK_ON)
            return

        if event.kind == "started":
            self._total_rows = event.total
            self._set_state_badge("RUNNING")
            if event.transport:
                self.transport_var.set(event.transport)
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

        elif event.kind == "row_done":
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            if event.sensor_id and event.sensor_id != "na":
                self.reading_var.set(
                    f"ID  {event.sensor_id}  ·  {event.temperature} °C  ·  {event.voltage} V"
                )
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
                    event.voltage or "na",
                    event.reason or event.message or "",
                ),
                tags=(event.performance or "SKIP",),
            )
            self._flash_row(item, event.performance or "SKIP")
            self.tree.see(item)
            self._record_session_row(event)
            self._note_sdr_compare(event.sdr_compare)
            self._refresh_table_count()

        elif event.kind == "stopping":
            self._set_state_badge("STOPPED")
            self.status_var.set(event.message or "Stopping…")

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
