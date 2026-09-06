"""Hamaton TPMS Validation Bench PRO SUITE — one-click UI."""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tpms_bench.paths import app_root, sdk_src

ROOT = app_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SDK = sdk_src()
if SDK.exists() and str(SDK) not in sys.path:
    sys.path.insert(0, str(SDK))

from tpms_bench.report import build_pdf
from tpms_bench.runner import OUT_XLSX, BenchRunner, ProgressEvent, reset_session_db
from tpms_bench.uart import default_port, find_serial_ports

# Match the Hamaton PRO SUITE reference layout
BG = "#F4F7FB"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8FAFC"
BORDER = "#E2E8F0"

NAVY = "#0B1C2C"
NAVY_MID = "#12263A"
DARK_NAVY = "#071320"
ACCENT = "#22B8E6"
ACCENT_LIGHT = "#7DD3FC"

PRO_BLUE = "#38BDF8"
TEXT = "#1E293B"
TEXT_MUTED = "#64748B"
TEXT_ON_DARK = "#F8FAFC"
TEXT_SUBTLE = "#94A3B8"

GREEN = "#0F9F6E"
GREEN_BG = "#D1FAE5"
GREEN_DARK = "#047857"
START_TEAL = "#0D9B7A"

RED = "#DC2626"
RED_BG = "#FEE2E2"
RED_DARK = "#B91C1C"

AMBER = "#EA580C"
ORANGE_BTN = "#F97316"
BLUE = "#2563EB"
BLUE_BG = "#DBEAFE"
BLUE_LIGHT = "#BFDBFE"
BLUE_PILL = "#3B82F6"

PURPLE = "#7C3AED"
PURPLE_BG = "#EDE9FE"

STAT_PENDING_BG = "#FFFFFF"
STAT_DONE_BG = "#FFFFFF"
STAT_OK_BG = "#FFFFFF"
STAT_NOK_BG = "#FFFFFF"
STAT_RATE_BG = "#FFFFFF"

CODE_A_BG = "#E0F2FE"
CODE_A_FG = "#0369A1"
CODE_B_BG = "#FEF3C7"
CODE_B_FG = "#B45309"
CODE_C_BG = "#EDE9FE"
CODE_C_FG = "#6D28D9"

TELEMETRY_BG = "#ECFDF5"
TELEMETRY_FG = "#059669"

LED_IDLE = "#64748B"
LED_TTL_ON = "#34D399"
LED_JLINK_ON = "#FBBF24"

FOOTER_BG = "#EEF2F6"
FOOTER_FG = "#475569"

# Legacy aliases used in widgets
CREAM = BG
CARD_BG = SURFACE
GRAY = TEXT_MUTED
LIGHT_GRAY = BORDER
ORANGE = ACCENT

FONT_UI = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_MONO = ("Consolas", 12, "bold")

_BTN_VARIANTS: dict[str, dict[str, str]] = {
    "primary": {"bg": START_TEAL, "hover": "#0B7F64", "fg": "#FFFFFF", "active": "#096F57"},
    "secondary": {"bg": BLUE, "hover": "#1D4ED8", "fg": "#FFFFFF", "active": "#1E40AF"},
    "warning": {"bg": ORANGE_BTN, "hover": "#EA580C", "fg": "#FFFFFF", "active": "#C2410C"},
    "danger": {"bg": RED, "hover": "#B91C1C", "fg": "#FFFFFF", "active": "#991B1B"},
    "navy": {"bg": "#334155", "hover": "#1E293B", "fg": "#FFFFFF", "active": "#0F172A"},
    "purple": {"bg": PURPLE, "hover": "#6D28D9", "fg": "#FFFFFF", "active": "#5B21B6"},
    "ghost": {"bg": "#E2E8F0", "hover": "#CBD5E1", "fg": TEXT, "active": "#94A3B8"},
    "soft": {"bg": BLUE_BG, "hover": BLUE_LIGHT, "fg": BLUE, "active": BLUE_LIGHT},
    "icon": {"bg": SURFACE_ALT, "hover": BORDER, "fg": TEXT_MUTED, "active": BORDER},
    "accent": {"bg": ACCENT, "hover": "#0EA5E9", "fg": "#FFFFFF", "active": "#0284C7"},
    "disabled": {"bg": "#E2E8F0", "hover": "#E2E8F0", "fg": "#94A3B8", "active": "#E2E8F0"},
}


class ModernButton(tk.Button):
    """Flat button with hover feedback and consistent sizing."""

    def __init__(
        self,
        master,
        text: str = "",
        command=None,
        variant: str = "secondary",
        *,
        large: bool = False,
        **kwargs,
    ) -> None:
        self._palette = dict(_BTN_VARIANTS.get(variant, _BTN_VARIANTS["secondary"]))
        padx = 20 if large else 14
        pady = 10 if large else 7
        font = ("Segoe UI", 11, "bold") if large else FONT_UI_BOLD
        outlined = variant in ("ghost", "icon")
        defaults: dict = {
            "text": text,
            "command": command,
            "bg": self._palette["bg"],
            "fg": self._palette["fg"],
            "activebackground": self._palette["active"],
            "activeforeground": self._palette["fg"],
            "font": font,
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 1 if outlined else 0,
            "highlightbackground": BORDER if outlined else self._palette["bg"],
            "highlightcolor": ACCENT,
            "padx": padx,
            "pady": pady,
            "cursor": "hand2",
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._paint()

    def _paint(self) -> None:
        disabled = str(self.cget("state")) == "disabled"
        pal = _BTN_VARIANTS["disabled"] if disabled else self._palette
        super().configure(
            bg=pal["bg"],
            fg=pal["fg"],
            activebackground=pal["active"],
            activeforeground=pal["fg"],
            disabledforeground=pal["fg"],
        )

    def _on_enter(self, _event) -> None:
        if str(self.cget("state")) != "disabled":
            super().configure(bg=self._palette["hover"])

    def _on_leave(self, _event) -> None:
        if str(self.cget("state")) != "disabled":
            super().configure(bg=self._palette["bg"])

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        result = super().configure(cnf, **kwargs) if cnf is not None else super().configure(**kwargs)
        if "state" in kwargs or (isinstance(cnf, dict) and "state" in cnf):
            self._paint()
        return result

    config = configure

    def set_variant(self, variant: str) -> None:
        self._palette = dict(_BTN_VARIANTS[variant])
        self._paint()


class BenchApp(tk.Tk):
    def __init__(self, autostart: bool = False) -> None:
        super().__init__()
        self.title("Hamaton TPMS Validation Bench")
        self.geometry("1320x880")
        self.minsize(1140, 780)
        self.configure(bg=BG)

        self.queue: queue.Queue[ProgressEvent] = queue.Queue()
        self.runner: BenchRunner | None = None
        self.worker: threading.Thread | None = None
        self.is_paused = False
        self.start_time: float | None = None
        self.source_xlsx: Path | None = None
        self._total_rows = 0
        self._anim_step = 0

        self._setup_styles()
        self._build_ui()
        self._reset_display()
        self.after(150, self._drain)
        self.after(80, self._animate_badge)
        if autostart:
            self.after(500, self.start_test)

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=SURFACE,
            foreground=TEXT,
            fieldbackground=SURFACE,
            rowheight=30,
            font=("Segoe UI", 10),
            bordercolor=BORDER,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#F1F5F9",
            foreground="#64748B",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=6,
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#E2E8F0")],
            foreground=[("active", "#475569")],
        )
        style.map("Treeview", background=[("selected", "#BFDBFE")], foreground=[("selected", TEXT)])
        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor="#E2E8F0",
            background=GREEN,
            lightcolor=GREEN,
            darkcolor=GREEN,
            thickness=7,
            bordercolor="#E2E8F0",
        )
        style.configure(
            "TCombobox",
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=TEXT,
            padding=5,
            arrowcolor=NAVY,
        )
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])
        style.configure("Vertical.TScrollbar", background="#C5CED8", troughcolor=BG, arrowcolor=NAVY_MID, bordercolor=BORDER)

    def _card(self, parent: tk.Misc, **pack_kw) -> tk.Frame:
        frame = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill="x", pady=(0, 10), **pack_kw)
        inner = tk.Frame(frame, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        return inner

    def _section_title(self, parent: tk.Misc, text: str) -> None:
        tk.Label(parent, text=text, bg=SURFACE, fg=TEXT_MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 8))

    def _stat_tile(
        self,
        parent: tk.Misc,
        icon: str,
        title: str,
        textvar: tk.StringVar,
        value_fg: str,
        label_fg: str,
    ) -> None:
        wrap = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(side="left", expand=True, fill="both", padx=(0, 8))
        card = tk.Frame(wrap, bg=SURFACE, padx=14, pady=10)
        card.pack(fill="both", expand=True)
        top = tk.Frame(card, bg=SURFACE)
        top.pack(anchor="w")
        tk.Label(top, text=icon, bg=SURFACE, fg=label_fg, font=("Segoe UI", 10)).pack(side="left")
        tk.Label(top, text=f"  {title}", bg=SURFACE, fg=label_fg, font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(card, textvariable=textvar, bg=SURFACE, fg=value_fg, font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(4, 0))

    def _build_ui(self) -> None:
        # ── Header ──────────────────────────────────────────────
        header = tk.Frame(self, bg=NAVY)
        header.pack(fill="x")
        header_inner = tk.Frame(header, bg=NAVY)
        header_inner.pack(fill="x", padx=18, pady=12)

        title_frame = tk.Frame(header_inner, bg=NAVY)
        title_frame.pack(side="left")
        title_row = tk.Frame(title_frame, bg=NAVY)
        title_row.pack(anchor="w")
        tk.Label(title_row, text="HAMATON TPMS", bg=NAVY, fg="white", font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(title_row, text="  VALIDATION BENCH", bg=NAVY, fg="white", font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(
            title_row, text="  PRO SUITE  ", bg="#0E7490", fg="white",
            font=("Segoe UI", 8, "bold"), padx=6, pady=2,
        ).pack(side="left", padx=(10, 0))
        tk.Label(
            title_frame,
            text="Automated Sensor Programming & LF Activation Benchmark · Real-Time Results Sync",
            bg=NAVY, fg="#7DD3FC", font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        self.state_badge = tk.Label(
            header_inner, text="●  IDLE", bg="#334155", fg="white",
            font=("Segoe UI", 9, "bold"), padx=14, pady=6,
        )
        self.state_badge.pack(side="right")

        self.transport_var = tk.StringVar(value="")
        tk.Label(header_inner, textvariable=self.transport_var, bg=NAVY, fg="#7DD3FC", font=("Segoe UI", 8)).pack(
            side="right", padx=(0, 12)
        )

        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

        self.status_var = tk.StringVar(value="Ready · Select an Excel database and click Start Test")
        footer = tk.Frame(self, bg=FOOTER_BG)
        footer.pack(fill="x", side="bottom")
        tk.Label(
            footer, textvariable=self.status_var, bg=FOOTER_BG, fg=FOOTER_FG,
            anchor="w", padx=16, pady=6, font=("Segoe UI", 9),
        ).pack(side="left", fill="x", expand=True)
        self.ttl_led = tk.Label(footer, text="● TTL", bg=FOOTER_BG, fg=LED_IDLE, font=("Segoe UI", 8, "bold"))
        self.ttl_led.pack(side="right", padx=(0, 8))
        self.rx_led = tk.Label(footer, text="● Board", bg=FOOTER_BG, fg=LED_IDLE, font=("Segoe UI", 8, "bold"))
        self.rx_led.pack(side="right", padx=(0, 12))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=10)

        # ── Current vehicle ─────────────────────────────────────
        current_outer = tk.Frame(body, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        current_outer.pack(fill="x", pady=(0, 8))
        current = tk.Frame(current_outer, bg=SURFACE)
        current.pack(fill="x", padx=14, pady=10)

        top_row = tk.Frame(current, bg=SURFACE)
        top_row.pack(fill="x")
        self.vehicle_var = tk.StringVar(value="Ready to test — choose an Excel file and click Start")
        tk.Label(top_row, textvariable=self.vehicle_var, bg=SURFACE, fg=NAVY, font=("Segoe UI", 16, "bold")).pack(
            side="left", anchor="w"
        )
        self.row_counter_var = tk.StringVar(value="")
        tk.Label(
            top_row, textvariable=self.row_counter_var, bg=BLUE_PILL, fg="white",
            font=("Segoe UI", 9, "bold"), padx=12, pady=4,
        ).pack(side="right")

        self.meta_var = tk.StringVar(value="OE: —   ·   Supplier: —   ·   Freq: —")
        tk.Label(current, textvariable=self.meta_var, bg=SURFACE, fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(
            anchor="w", pady=(2, 8)
        )

        codes = tk.Frame(current, bg=SURFACE)
        codes.pack(fill="x")
        self.code_vars = {"A": tk.StringVar(value="—"), "B": tk.StringVar(value="—"), "C": tk.StringVar(value="—")}
        for key, bg, fg in (("A", CODE_A_BG, CODE_A_FG), ("B", CODE_B_BG, CODE_B_FG), ("C", CODE_C_BG, CODE_C_FG)):
            box = tk.Frame(codes, bg=bg, padx=12, pady=8)
            box.pack(side="left", expand=True, fill="x", padx=(0, 8 if key != "C" else 0))
            inner = tk.Frame(box, bg=bg)
            inner.pack()
            tk.Label(inner, text=f"CODE {key}", bg=bg, fg=fg, font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 10))
            tk.Label(inner, textvariable=self.code_vars[key], bg=bg, fg=fg, font=("Consolas", 12, "bold")).pack(side="left")

        tel_frame = tk.Frame(current, bg=TELEMETRY_BG, padx=10, pady=6)
        tel_frame.pack(fill="x", pady=(8, 0))
        self.reading_var = tk.StringVar(value="Live Telemetry:  Waiting for first reading…")
        tk.Label(
            tel_frame, textvariable=self.reading_var, bg=TELEMETRY_BG, fg=TELEMETRY_FG,
            font=("Segoe UI", 10, "bold"), anchor="w",
        ).pack(fill="x")

        # ── Stats ───────────────────────────────────────────────
        stats_frame = tk.Frame(body, bg=BG)
        stats_frame.pack(fill="x", pady=(0, 6))
        self.pending_var = tk.StringVar(value="—")
        self.done_var = tk.StringVar(value="0")
        self.ok_var = tk.StringVar(value="0")
        self.nok_var = tk.StringVar(value="0")
        self.rate_var = tk.StringVar(value="0.0%")
        self._stat_tile(stats_frame, "⏳", "PENDING", self.pending_var, AMBER, AMBER)
        self._stat_tile(stats_frame, "📊", "TESTED", self.done_var, BLUE, BLUE)
        self._stat_tile(stats_frame, "✓", "PASSED (OK)", self.ok_var, GREEN, GREEN)
        self._stat_tile(stats_frame, "✕", "FAILED (NOK)", self.nok_var, RED, RED)
        self._stat_tile(stats_frame, "📈", "PASS RATE", self.rate_var, PURPLE, PURPLE)

        # ── Progress ────────────────────────────────────────────
        prog_row = tk.Frame(body, bg=BG)
        prog_row.pack(fill="x", pady=(0, 2))
        self.progress_label = tk.Label(prog_row, text="Progress: 0.0% (0 of 0)", bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9))
        self.progress_label.pack(side="left")
        self.speed_var = tk.StringVar(value="")
        self.elapsed_var = tk.StringVar(value="")
        tk.Label(prog_row, textvariable=self.elapsed_var, bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(side="right")
        tk.Label(prog_row, textvariable=self.speed_var, bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(side="right", padx=(0, 12))
        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100, style="Green.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 8))

        # ── Toolbar (two rows, as in reference) ─────────────────
        controls = tk.Frame(body, bg=BG)
        controls.pack(fill="x", pady=(0, 8))
        row1 = tk.Frame(controls, bg=BG)
        row1.pack(fill="x", pady=(0, 6))
        tk.Label(row1, text="Database File:", bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.file_label = tk.Label(row1, text="No file selected", bg=BG, fg=AMBER, font=("Segoe UI", 9, "bold"))
        self.file_label.pack(side="left", padx=(6, 12))
        ModernButton(row1, text="Choose Excel File…", command=self.select_excel, variant="secondary").pack(side="right", padx=(6, 0))
        ModernButton(row1, text="↻  Reset Session", command=self.reset_session, variant="ghost").pack(side="right")

        row2 = tk.Frame(controls, bg=BG)
        row2.pack(fill="x")
        tk.Label(row2, text="Port:", bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.port_var = tk.StringVar(value=default_port())
        self.port_combo = ttk.Combobox(row2, textvariable=self.port_var, width=22, font=FONT_UI)
        self.port_combo["values"] = find_serial_ports()
        self.port_combo.pack(side="left", padx=(6, 4))
        ModernButton(row2, text="↻", command=self._refresh_ports, variant="icon", padx=8, pady=4).pack(side="left", padx=(0, 12))

        self.start_btn = ModernButton(row2, text="▶  START TEST", command=self.start_test, variant="primary")
        self.start_btn.pack(side="left", padx=(0, 6))
        self.pause_btn = ModernButton(row2, text="❚❚  PAUSE", command=self.toggle_pause, variant="warning", state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ModernButton(row2, text="⏹  STOP", command=self.stop_test, variant="danger", state="disabled")
        self.stop_btn.pack(side="left")

        ModernButton(row2, text="Export PDF Report", command=self.make_pdf, variant="purple").pack(side="right")
        ModernButton(row2, text="View Excel Results", command=self.open_excel, variant="navy").pack(side="right", padx=(0, 6))

        # ── Results table ───────────────────────────────────────
        table_card = tk.Frame(body, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        table_card.pack(fill="both", expand=True)
        self.table_count_var = tk.StringVar(value="0 rows")
        columns = ("row", "vehicle", "supplier", "codes", "result", "id", "temp", "volt", "reason")
        self.tree = ttk.Treeview(table_card, columns=columns, show="headings", height=14)
        headings = {
            "row": "Row #", "vehicle": "Vehicle (Make / Model / Year)", "supplier": "OE Supplier",
            "codes": "CODE A / B / C", "result": "Result", "id": "Sensor ID",
            "temp": "Temp °C", "volt": "Battery V", "reason": "Note / NOK Diagnostics",
        }
        widths = {"row": 55, "vehicle": 210, "supplier": 100, "codes": 240, "result": 70, "id": 100, "temp": 70, "volt": 80, "reason": 200}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center" if col in ("row", "result", "id", "temp", "volt") else "w")

        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.tag_configure("OK", background="#D1FAE5", foreground="#047857")
        self.tree.tag_configure("NOK", background="#FEE2E2", foreground="#B91C1C")
        self.tree.tag_configure("SKIP", background="#F1F5F9", foreground=TEXT_MUTED)
        self.tree.tag_configure("flash", background="#BFDBFE")

    def _refresh_ports(self) -> None:
        ports = find_serial_ports()
        self.port_combo["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def _reset_display(self) -> None:
        self._update_stat_labels(pending=0, done=0, ok=0, nok=0, total=0)
        self.vehicle_var.set("Ready to test — choose an Excel file and click Start")
        self.meta_var.set("OE: —   ·   Supplier: —   ·   Freq: —")
        self.row_counter_var.set("")
        self.reading_var.set("Live Telemetry:  Waiting for first reading…")
        for key in self.code_vars:
            self.code_vars[key].set("—")
        self.progress.configure(value=0)
        self.progress_label.configure(text="Progress: 0.0% (0 of 0)")
        self.speed_var.set("")
        self.elapsed_var.set("")
        self._refresh_table_count()

    def _refresh_table_count(self) -> None:
        n = len(self.tree.get_children())
        self.table_count_var.set(f"{n} row{'s' if n != 1 else ''}")

    def _clear_readings(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._refresh_table_count()

    def select_excel(self) -> None:
        path = filedialog.askopenfilename(title="Select Hamaton Excel Database", filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
        if not path:
            return
        self.source_xlsx = Path(path)
        self.file_label.configure(text=self.source_xlsx.name, fg=AMBER)
        self.status_var.set(f"Database loaded: {self.source_xlsx.name} — click Start Test")

    def reset_session(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Session Active", "Stop the current test before resetting.")
            return
        if not messagebox.askyesno("Reset Session", "Clear all results and reset counters?"):
            return
        reset_session_db()
        self._clear_readings()
        self._reset_display()
        self._set_state_badge("IDLE", "#334155")

    def start_test(self) -> None:
        if self.worker and self.worker.is_alive():
            if self.is_paused and self.runner:
                self.toggle_pause()
            return

        if not self.source_xlsx or not self.source_xlsx.exists():
            messagebox.showinfo("Select Excel File", "Please choose an Excel database file first.")
            self.select_excel()
            if not self.source_xlsx:
                return

        reset_session_db()
        self._clear_readings()
        self._reset_display()
        self.is_paused = False
        self.start_time = time.monotonic()

        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="❚❚  PAUSE")
        self.pause_btn.set_variant("warning")
        self.stop_btn.configure(state="normal")
        self._set_state_badge("RUNNING", GREEN)

        port = self.port_var.get().strip() or default_port()
        self.status_var.set(f"Starting · USB-TTL on {port}…")

        self.runner = BenchRunner(
            port=port,
            source_xlsx=self.source_xlsx,
            resume=False,
            skip_sdr=False,
            on_progress=self.queue.put,
        )
        self.worker = threading.Thread(target=self._run_safe, daemon=True)
        self.worker.start()

    def toggle_pause(self) -> None:
        if not self.runner or not self.worker or not self.worker.is_alive():
            return
        if not self.is_paused:
            self.runner.pause()
            self.is_paused = True
            self.pause_btn.configure(text="▶  RESUME")
            self.pause_btn.set_variant("secondary")
            self._set_state_badge("PAUSED", AMBER)
        else:
            self.runner.resume_run()
            self.is_paused = False
            self.pause_btn.configure(text="❚❚  PAUSE")
            self.pause_btn.set_variant("warning")
            self._set_state_badge("RUNNING", GREEN)

    def stop_test(self) -> None:
        if self.runner:
            self.runner.request_stop()
        self.stop_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled")

    def _set_state_badge(self, text: str, color: str) -> None:
        sym = {"RUNNING": "●", "PAUSED": "❚❚", "STOPPED": "■", "COMPLETED": "✔", "IDLE": "●", "ERROR": "✕"}.get(text, "●")
        self.state_badge.configure(text=f"{sym}  {text}", bg=color, fg="white")

    def _animate_badge(self) -> None:
        if "RUNNING" in self.state_badge.cget("text"):
            self._anim_step = (self._anim_step + 1) % 16
            self.state_badge.configure(fg="white" if self._anim_step < 8 else "#C6F6D5")
        self.after(120, self._animate_badge)

    def _run_safe(self) -> None:
        try:
            assert self.runner is not None
            self.runner.run()
        except Exception as error:
            self.queue.put(ProgressEvent(kind="error", message=str(error)))

    def _open_file(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo("File Not Found", str(path))
            return
        if platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def open_excel(self) -> None:
        if OUT_XLSX.exists():
            self._open_file(OUT_XLSX)
        else:
            messagebox.showinfo("Excel Results", "No results file yet.")

    def make_pdf(self) -> None:
        try:
            self._open_file(build_pdf())
        except Exception as error:
            messagebox.showerror("PDF Error", str(error))

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

    def _end_session(self, label: str, color: str, message: str) -> None:
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="❚❚  PAUSE")
        self.pause_btn.set_variant("warning")
        self.stop_btn.configure(state="disabled")
        self.is_paused = False
        self._set_state_badge(label, color)
        try:
            build_pdf()
        except Exception:
            pass
        self.status_var.set(message)

    def _blink_led(self, widget: tk.Label, active_color: str, idle_color: str = LED_IDLE) -> None:
        widget.configure(fg=active_color)
        self.after(350, lambda: widget.configure(fg=idle_color))

    def _apply(self, event: ProgressEvent) -> None:
        if event.kind == "comm":
            if event.path == "ttl":
                self._blink_led(self.ttl_led, LED_TTL_ON)
            elif event.path == "jlink":
                self._blink_led(self.rx_led, LED_JLINK_ON)
            return

        if event.kind == "started":
            self._total_rows = event.total
            self._set_state_badge("RUNNING", GREEN)
            if event.transport:
                self.transport_var.set(event.transport)
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            self.status_var.set(event.message)

        elif event.kind == "row_start":
            self.vehicle_var.set(f"{event.make} {event.model} ({event.year})" if event.year else f"{event.make} {event.model}")
            self.meta_var.set(f"OE: {event.oe or '—'}  ·  Supplier: {event.supplier or '—'}  ·  Freq: {event.freq or '—'}")
            self.row_counter_var.set(f"Row {event.excel_row} / {event.total}")
            self.code_vars["A"].set(event.code_a or "—")
            self.code_vars["B"].set(event.code_b or "—")
            self.code_vars["C"].set(event.code_c or "—")
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            self.status_var.set(f"Testing row {event.excel_row}: {event.make} {event.model} · {event.pending} pending")

        elif event.kind == "row_done":
            self._update_stat_labels(event.pending, event.done, event.ok, event.nok, event.total)
            if event.sensor_id and event.sensor_id != "na":
                self.reading_var.set(
                    f"Live Telemetry:  ID  {event.sensor_id}  ·  {event.temperature} °C  ·  {event.voltage} V"
                )
            item = self.tree.insert("", 0, values=(
                event.excel_row, f"{event.make} {event.model}", event.supplier or "—",
                f"{event.code_a}  {event.code_b}  {event.code_c}", event.performance,
                event.sensor_id or "na", event.temperature or "na", event.voltage or "na",
                event.reason or event.message or "",
            ), tags=(event.performance or "SKIP",))
            self._flash_row(item, event.performance or "SKIP")
            self._refresh_table_count()
            self.tree.see(item)

        elif event.kind == "finished":
            self._end_session("COMPLETED", BLUE, event.message)

        elif event.kind == "stopped":
            self._end_session("STOPPED", GRAY, event.message)

        elif event.kind == "error":
            self.start_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled")
            self.stop_btn.configure(state="disabled")
            self._set_state_badge("ERROR", RED)
            messagebox.showerror("Bench Error", event.message)

    def _update_stat_labels(self, pending: int, done: int, ok: int, nok: int, total: int) -> None:
        self.pending_var.set(str(pending))
        self.done_var.set(str(done))
        self.ok_var.set(str(ok))
        self.nok_var.set(str(nok))
        self.rate_var.set(f"{(ok / done * 100.0) if done else 0.0:.1f}%")
        if total > 0:
            pct = done / total * 100.0
            self.progress.configure(maximum=total, value=done)
            self.progress_label.configure(text=f"Progress: {pct:.1f}% ({done} of {total})")
            if self.start_time and done > 0:
                elapsed_s = time.monotonic() - self.start_time
                mins, secs = divmod(int(elapsed_s), 60)
                rate = done / (elapsed_s / 60.0) if elapsed_s > 0 else 0
                self.speed_var.set(f"{rate:.1f} tests/min")
                self.elapsed_var.set(f"Elapsed: {mins}:{secs:02d}")


def main(autostart: bool = False) -> None:
    if "--autostart" in sys.argv:
        autostart = True
    BenchApp(autostart=autostart).mainloop()


if __name__ == "__main__":
    main()
