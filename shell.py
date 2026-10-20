"""Unified TPMS Suite — SDR Receiver and TPMS Board in one window."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

_ROOT = Path(__file__).resolve().parent
_SDR = _ROOT / "sdr_ui"
_SDK = _ROOT / "hamaton-sdk-python-fix-uart-transport-timing" / "src"
for _path in (_ROOT, _SDR, _SDK):
    _text = str(_path)
    if _path.exists() and _text not in sys.path:
        sys.path.insert(0, _text)

import customtkinter as ctk

from app import SdrView
from comparative_report import build_comparison, export_comparative_excel, export_comparative_pdf
from comparison_view import ComparisonView
from dialogs import ask_save_path
from iq_urh_tool import IqUrhView
from progress_view import ProgressView
from range_view import RangeView
from themes import (
    COLOR_BG,
    COLOR_BG_CARD,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_BTN_EXPORT,
    COLOR_BTN_EXPORT_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_BTN_PRIMARY_HOVER,
    COLOR_BTN_PRIMARY_TEXT,
    COLOR_CYAN_BG,
    COLOR_GREEN,
    COLOR_HEADER_ACCENT,
    COLOR_ORANGE,
    COLOR_ORANGE_BG,
    COLOR_PILL_MUTED_BG,
    COLOR_PILL_MUTED_FG,
    COLOR_PILL_OK_BG,
    COLOR_PILL_OK_FG,
    COLOR_RED,
    COLOR_SIDEBAR_ACTIVE,
    COLOR_SIDEBAR_BG,
    COLOR_SIDEBAR_HOVER,
    COLOR_SIDEBAR_MUTED,
    COLOR_SIDEBAR_TEXT,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_TEXT_MUTED,
    COMPANY_NAME,
    FYRQOM_LOGOTYPE,
    PRODUCT_NAME,
    combo_colors,
    ui_font,
)
from tpms_view import TpmsView

APP_TITLE = PRODUCT_NAME
APP_SUBTITLE = "USB-TTL diagnostics"
PAGE_TITLES = {
    "board": ("Board testing", "USB-TTL diagnostics"),
    "sdr": ("SDR Receiver", "rtl_433 live decode"),
    "progress": ("Progress", "Live Board + SDR timeline"),
    "compare": ("Comparison", "Board vs SDR results"),
    "range": ("Range Radar", "RF proximity view"),
    "iq": ("IQ / URH", "Capture and analyze"),
}


class CombinedApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        self.title(APP_TITLE)
        self.geometry("1440x920")
        self.minsize(1200, 780)
        self.configure(fg_color=COLOR_BG)
        self._active = "board"
        self.chunk_var = ctk.StringVar(value="100")
        self._pulse = 0
        self._build_chrome()
        self._build_views()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._pulse_status)
        self.after(120, self._maximize_window)
        self.after(600, self._refresh_sdr_optional_badge)
        if os.environ.get("FYRQOM_AUTOSTART") == "1":
            # Board-only full catalog — SDR never required.
            full = os.environ.get("FYRQOM_RUN_FULL", "1") == "1"
            with_sdr = os.environ.get("FYRQOM_WITH_SDR", "0") == "1"
            self.after(1800, lambda: self._start_board_run(run_full=full, with_sdr=with_sdr))
        else:
            self.after(350, self._prompt_session_choice)

    def _build_chrome(self) -> None:
        shell = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        # —— Dark left sidebar ——
        sidebar = ctk.CTkFrame(shell, fg_color=COLOR_SIDEBAR_BG, corner_radius=0, width=210)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 18))
        if FYRQOM_LOGOTYPE.is_file():
            from PIL import Image

            img = Image.open(FYRQOM_LOGOTYPE)
            self._logo_image = ctk.CTkImage(light_image=img, dark_image=img, size=(132, 38))
            ctk.CTkLabel(brand, image=self._logo_image, text="").pack(anchor="w")
        else:
            ctk.CTkLabel(
                brand, text=COMPANY_NAME.lower(), font=ui_font(22, "bold"), text_color="#FFFFFF"
            ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text="TPMS Suite 5.0", font=ui_font(12, "bold"), text_color=COLOR_SIDEBAR_ACTIVE
        ).pack(anchor="w", pady=(6, 0))

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkLabel(
            nav,
            text="WORKFLOWS",
            font=ui_font(10, "bold"),
            text_color=COLOR_SIDEBAR_MUTED,
            anchor="w",
        ).pack(fill="x", padx=8, pady=(0, 8))

        def _nav_btn(text: str, view: str) -> ctk.CTkButton:
            btn = ctk.CTkButton(
                nav,
                text=f"  {text}",
                anchor="w",
                height=42,
                font=ui_font(13, "bold"),
                corner_radius=10,
                fg_color="transparent",
                hover_color=COLOR_SIDEBAR_HOVER,
                text_color=COLOR_SIDEBAR_TEXT,
                command=lambda v=view: self.show_view(v),
            )
            btn.pack(fill="x", pady=2)
            return btn

        self.board_tab = _nav_btn("Board", "board")
        self.sdr_tab = _nav_btn("SDR Receiver", "sdr")
        self.progress_tab = _nav_btn("Progress", "progress")
        self.compare_tab = _nav_btn("Comparison", "compare")
        self.range_tab = _nav_btn("Range Radar", "range")
        self.iq_tab = _nav_btn("IQ / URH", "iq")

        # Spacer so Settings stays at the bottom
        ctk.CTkFrame(sidebar, fg_color="transparent").grid(row=2, column=0, sticky="nsew")

        foot = ctk.CTkFrame(sidebar, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 18))
        ctk.CTkFrame(foot, fg_color="#1A222C", height=1).pack(fill="x", pady=(0, 12))
        ctk.CTkButton(
            foot,
            text="  Settings",
            anchor="w",
            height=38,
            font=ui_font(13),
            corner_radius=10,
            fg_color="transparent",
            hover_color=COLOR_SIDEBAR_HOVER,
            text_color=COLOR_SIDEBAR_MUTED,
            command=lambda: self.show_view("board"),
        ).pack(fill="x")

        # —— Main column ——
        main = ctk.CTkFrame(shell, fg_color=COLOR_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        page_bar = ctk.CTkFrame(main, fg_color="transparent")
        page_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        titles = ctk.CTkFrame(page_bar, fg_color="transparent")
        titles.pack(side="left")
        self.page_title = ctk.CTkLabel(
            titles, text="Board testing", font=ui_font(20, "bold"), text_color=COLOR_TEXT
        )
        self.page_title.pack(anchor="w")
        self.page_subtitle = ctk.CTkLabel(
            titles, text=APP_SUBTITLE, font=ui_font(12), text_color=COLOR_TEXT_MUTED
        )
        self.page_subtitle.pack(anchor="w")

        badges = ctk.CTkFrame(page_bar, fg_color="transparent")
        badges.pack(side="right")
        self.board_status = ctk.CTkLabel(
            badges,
            text="●  Board connected  ·  USB-TTL TX/RX",
            font=ui_font(11, "bold"),
            text_color=COLOR_PILL_OK_FG,
            fg_color=COLOR_PILL_OK_BG,
            corner_radius=14,
            height=28,
            padx=12,
        )
        self.board_status.pack(side="left", padx=(0, 6))
        self.sdr_status = ctk.CTkLabel(
            badges,
            text="●  SDR idle",
            font=ui_font(11, "bold"),
            text_color=COLOR_PILL_MUTED_FG,
            fg_color=COLOR_PILL_MUTED_BG,
            corner_radius=14,
            height=28,
            padx=12,
        )
        self.sdr_status.pack(side="left")

        # Compact full-width toolbar — STOP on top, Start TPMS+SDR prominent
        COLOR_START = "#2563EB"
        COLOR_START_HOVER = "#1D4ED8"
        COLOR_TEAL = COLOR_SIDEBAR_ACTIVE
        COLOR_TEAL_HOVER = COLOR_BTN_PRIMARY_HOVER

        bar = ctk.CTkFrame(
            main, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER
        )
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        wrap = ctk.CTkFrame(bar, fg_color="transparent")
        wrap.pack(fill="x", padx=10, pady=8)

        def _lab(parent, text: str, color: str) -> None:
            ctk.CTkLabel(parent, text=text, font=ui_font(10, "bold"), text_color=color).pack(
                side="left", padx=(0, 6)
            )

        def _div(parent) -> None:
            ctk.CTkFrame(parent, fg_color=COLOR_BORDER, width=1, height=28).pack(side="left", padx=8)

        def _btn(
            parent,
            text: str,
            *,
            command,
            width: int = 100,
            height: int = 30,
            fg=COLOR_START,
            hover=COLOR_START_HOVER,
            text_color="#FFFFFF",
            border=None,
        ) -> ctk.CTkButton:
            kw = dict(
                text=text,
                width=width,
                height=height,
                font=ui_font(11, "bold"),
                fg_color=fg,
                hover_color=hover,
                text_color=text_color,
                corner_radius=8,
                command=command,
            )
            if border:
                kw["border_width"] = 1
                kw["border_color"] = border
            btn = ctk.CTkButton(parent, **kw)
            btn.pack(side="left", padx=(0, 4))
            return btn

        # Row 1 — all START first, then all STOP
        r1 = ctk.CTkFrame(wrap, fg_color="transparent")
        r1.pack(fill="x")
        _lab(r1, "START", COLOR_TEAL)
        self.shell_start_both_btn = ctk.CTkButton(
            r1,
            text="▶  Start TPMS + SDR",
            width=168,
            height=36,
            font=ui_font(13, "bold"),
            fg_color=COLOR_TEAL,
            hover_color=COLOR_TEAL_HOVER,
            text_color="#FFFFFF",
            corner_radius=10,
            command=lambda: self._start_board_run(run_full=False, with_sdr=True),
        )
        self.shell_start_both_btn.pack(side="left", padx=(0, 6))
        self.shell_start_btn = _btn(
            r1, "Start TPMS", width=104, height=34,
            fg=COLOR_START, hover=COLOR_START_HOVER,
            command=lambda: self._start_board_run(run_full=True, with_sdr=False),
        )
        self.shell_start_chunk_btn = _btn(
            r1, "Start chunk", width=100, height=34,
            command=lambda: self._start_board_run(run_full=False, with_sdr=False),
        )
        ctk.CTkLabel(r1, text="Size", font=ui_font(10, "bold"), text_color=COLOR_TEXT_MUTED).pack(
            side="left", padx=(2, 4)
        )
        self.chunk_combo = ctk.CTkComboBox(
            r1,
            values=["10", "25", "50", "100", "200", "500"],
            width=70,
            height=30,
            variable=self.chunk_var,
            **combo_colors(),
        )
        self.chunk_combo.set("100")
        self.chunk_combo.pack(side="left", padx=(0, 6))
        self.shell_start_sdr_only_btn = _btn(
            r1, "Start SDR", width=92, height=34,
            fg="#0F172A", hover="#000000",
            command=self._shell_start_sdr,
        )
        _div(r1)
        _lab(r1, "STOP", COLOR_RED)
        self.shell_stop_all_btn = _btn(
            r1, "STOP ALL", width=104, height=34,
            fg=COLOR_RED, hover="#B93A3A", command=self._shell_stop_all,
        )
        self.shell_stop_btn = _btn(
            r1, "Stop TPMS", width=96, height=34,
            fg="#FFFFFF", hover="#FCECEC", text_color=COLOR_RED, border=COLOR_RED,
            command=self._shell_stop,
        )
        self.shell_stop_sdr_btn = _btn(
            r1, "Stop SDR", width=90, height=34,
            fg="#FFFFFF", hover="#FCECEC", text_color=COLOR_RED, border=COLOR_RED,
            command=self._shell_stop_sdr,
        )

        # Row 2 — PAUSE + COMPARE + EXPORT
        r2 = ctk.CTkFrame(wrap, fg_color="transparent")
        r2.pack(fill="x", pady=(6, 0))
        _lab(r2, "PAUSE", COLOR_ORANGE)
        self.shell_pause_btn = _btn(
            r2, "Pause TPMS", width=100, height=30,
            fg=COLOR_ORANGE, hover="#B45309", command=self._shell_pause_tpms,
        )
        self.shell_pause_sdr_btn = _btn(
            r2, "Pause SDR", width=92, height=30,
            fg="#FFFFFF", hover=COLOR_ORANGE_BG, text_color=COLOR_ORANGE, border=COLOR_ORANGE,
            command=self._shell_pause_sdr,
        )
        self.shell_pause_all_btn = _btn(
            r2, "Pause ALL", width=92, height=30,
            fg=COLOR_ORANGE_BG, hover="#FDE68A", text_color=COLOR_ORANGE, border=COLOR_ORANGE,
            command=self._shell_pause_all,
        )
        _div(r2)
        _lab(r2, "COMPARE", COLOR_TEXT_MUTED)
        _btn(
            r2, "Compare Excel", width=112, height=30,
            fg=COLOR_BG, hover=COLOR_BORDER, text_color=COLOR_TEXT, border=COLOR_BORDER,
            command=lambda: self._export_comparative("xlsx"),
        )
        _btn(
            r2, "Compare PDF", width=104, height=30,
            fg=COLOR_BG, hover=COLOR_BORDER, text_color=COLOR_TEXT, border=COLOR_BORDER,
            command=lambda: self._export_comparative("pdf"),
        )

        exp = ctk.CTkFrame(r2, fg_color=COLOR_BG_PANEL, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        exp.pack(side="right")
        exp_in = ctk.CTkFrame(exp, fg_color="transparent")
        exp_in.pack(padx=8, pady=4)
        ctk.CTkButton(
            exp_in, text="Export", width=88, height=30, font=ui_font(12, "bold"),
            fg_color=COLOR_START, hover_color=COLOR_START_HOVER, text_color="#FFFFFF", corner_radius=8,
            command=lambda: self.board_view.export_excel() if hasattr(self, "board_view") else None,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            exp_in, text="PDF", width=52, height=28, font=ui_font(11, "bold"),
            fg_color="#FFFFFF", hover_color="#FEE2E2", text_color=COLOR_RED,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8,
            command=lambda: self.board_view.export_pdf() if hasattr(self, "board_view") else None,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            exp_in, text="Excel", width=58, height=28, font=ui_font(11, "bold"),
            fg_color="#FFFFFF", hover_color="#DCFCE7", text_color="#15803D",
            border_width=1, border_color=COLOR_BORDER, corner_radius=8,
            command=lambda: self.board_view.export_excel() if hasattr(self, "board_view") else None,
        ).pack(side="left")

        self._accent = ctk.CTkFrame(main, fg_color=COLOR_HEADER_ACCENT, height=0, corner_radius=0)
        self.content = ctk.CTkFrame(main, fg_color=COLOR_BG)
        self.content.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def _build_views(self) -> None:
        self.progress_view = ProgressView(self.content)
        self.sdr_view = SdrView(
            self.content,
            on_status_change=self._on_sdr_status,
            on_process_update=self._on_sdr_process,
        )
        self.board_view = TpmsView(
            self.content,
            on_status_change=self._on_board_status,
            on_chunk_complete=self._on_chunk_complete,
            on_process_update=self._on_board_process,
            chunk_var=self.chunk_var,
        )
        self.compare_view = ComparisonView(
            self.content,
            get_sdr=self.sdr_view.get_sensor_snapshot,
            get_board=self.board_view.get_tested_rows,
            export_excel=lambda: self._export_comparative("xlsx"),
            export_pdf=lambda: self._export_comparative("pdf"),
        )
        self.iq_view = IqUrhView(self.content)
        self.range_view = RangeView(
            self.content,
            get_sdr=self.sdr_view.get_sensor_snapshot,
        )
        self.sdr_view.grid(row=0, column=0, sticky="nsew")
        self.board_view.grid(row=0, column=0, sticky="nsew")
        self.progress_view.grid(row=0, column=0, sticky="nsew")
        self.compare_view.grid(row=0, column=0, sticky="nsew")
        self.range_view.grid(row=0, column=0, sticky="nsew")
        self.iq_view.grid(row=0, column=0, sticky="nsew")
        self.board_view.live_sdr_get = self.sdr_view.get_sensor_snapshot
        self.board_view.live_sdr_prepare = self._prepare_sdr_ready
        self.board_view.on_board_rf = self.sdr_view.ingest_board_reading
        self.board_view.on_board_trigger = self.sdr_view.watch_board_burst
        self.board_view.on_sdr_finalize = self.sdr_view.finalize_board_match
        self.board_view.on_prepare_sdr = self._prepare_sdr_for_board
        self.board_view.on_sdr_release = self._release_sdr_after_board
        self.sdr_view.on_range_update = self.range_view.update_sdr
        self.show_view("board")

    def _prepare_sdr_for_board(self, freq_mhz: float | None = None) -> bool:
        """Ensure SDR is listening (and tuned) for Board / custom-code compare."""
        try:
            return bool(self.sdr_view.ensure_listening(freq_mhz=freq_mhz))
        except Exception:
            return False

    def _prepare_sdr_ready(self, freq_mhz: float | None = None) -> bool:
        """Sync prepare for BenchRunner — True only when rtl_433 is alive on band."""
        try:
            tuned = bool(self.sdr_view.ensure_listening(freq_mhz=freq_mhz))
        except Exception:
            return False
        try:
            alive = bool(self.sdr_view.is_listen_alive())
        except Exception:
            alive = False
        # ensure_listening True means already on-band; also require subprocess up.
        return bool(tuned and alive)

    def _release_sdr_after_board(self, reason: str = "", message: str = "") -> None:
        """Board session/chunk settled — stop SDR listening until the next Start/row."""
        try:
            self.sdr_view.release_after_board_session(reason=reason, message=message)
        except Exception:
            pass

    def _on_board_process(self, **kwargs) -> None:
        try:
            self.progress_view.board_event(**kwargs)
        except Exception:
            pass

    def _on_sdr_process(self, **kwargs) -> None:
        try:
            self.progress_view.sdr_event(**kwargs)
        except Exception:
            pass

    def _prompt_session_choice(self) -> None:
        """Ask whether to continue the previous Board/SDR session or start clean."""
        board_n = 0
        sdr_n = 0
        try:
            board_n = int(self.board_view.previous_session_count())
        except Exception:
            board_n = 0
        try:
            sdr_n = int(self.sdr_view.previous_sensor_count())
        except Exception:
            sdr_n = 0
        if board_n <= 0 and sdr_n <= 0:
            return

        parts = []
        if board_n:
            parts.append(f"{board_n} Board result row(s)")
        if sdr_n:
            parts.append(f"{sdr_n} SDR sensor(s)")
        summary = " and ".join(parts)

        # Yes = continue · No = clear / new session
        continue_session = messagebox.askyesno(
            "Previous session found",
            f"A previous session is saved:\n\n  {summary}\n\n"
            "Yes  — Continue previous session (keep results)\n"
            "No   — Start a new session (clear Board + SDR values)",
            parent=self,
        )
        if continue_session:
            try:
                restored_b = self.board_view.restore_previous_session()
            except Exception:
                restored_b = 0
            try:
                restored_s = self.sdr_view.restore_previous_session()
            except Exception:
                restored_s = False
            note = []
            if restored_b:
                note.append(f"Board {restored_b}")
            if restored_s:
                note.append(f"SDR {len(self.sdr_view.get_sensor_snapshot())}")
            if note:
                self.title(f"{APP_TITLE}  ·  restored {' + '.join(note)}")
            return

        try:
            self.board_view.clear_session_silent()
        except Exception:
            pass
        try:
            self.sdr_view.clear_session_silent()
        except Exception:
            pass
        try:
            self.compare_view.refresh()
        except Exception:
            pass
        self.title(f"{APP_TITLE}  ·  new session")

    def show_view(self, name: str) -> None:
        self._active = name
        title, subtitle = PAGE_TITLES.get(name, ("TPMS Suite", APP_SUBTITLE))
        try:
            self.page_title.configure(text=title)
            self.page_subtitle.configure(text=subtitle)
        except Exception:
            pass
        self.board_view.grid_remove()
        self.sdr_view.grid_remove()
        self.progress_view.grid_remove()
        self.compare_view.grid_remove()
        self.range_view.grid_remove()
        self.iq_view.grid_remove()
        self._paint_tab(self.board_tab, False)
        self._paint_tab(self.sdr_tab, False)
        self._paint_tab(self.progress_tab, False)
        self._paint_tab(self.compare_tab, False)
        self._paint_tab(self.range_tab, False)
        self._paint_tab(self.iq_tab, False)
        if name == "sdr":
            self.sdr_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.sdr_tab, True)
        elif name == "progress":
            self.progress_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.progress_tab, True)
        elif name == "compare":
            self.compare_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.compare_tab, True)
            self.compare_view.refresh()
        elif name == "range":
            self.range_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.range_tab, True)
        elif name == "iq":
            self.iq_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.iq_tab, True)
        else:
            self.board_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.board_tab, True)
            self.after(50, self.board_view.focus_code_fields)

    def _paint_tab(self, button: ctk.CTkButton, active: bool) -> None:
        if active:
            button.configure(
                fg_color=COLOR_SIDEBAR_ACTIVE,
                hover_color=COLOR_BTN_PRIMARY_HOVER,
                text_color="#FFFFFF",
            )
        else:
            button.configure(
                fg_color="transparent",
                hover_color=COLOR_SIDEBAR_HOVER,
                text_color=COLOR_SIDEBAR_TEXT,
            )

    def _on_sdr_status(self, running: bool, label: str) -> None:
        upper = (label or "").upper()
        if upper in {"RUNNING", "LISTENING"}:
            self.sdr_status.configure(
                text=f"●  SDR listening  ·  {label}",
                text_color=COLOR_PILL_OK_FG,
                fg_color=COLOR_PILL_OK_BG,
            )
        elif upper in {"PAUSED", "ERROR"}:
            color = COLOR_ORANGE if upper == "PAUSED" else COLOR_RED
            self.sdr_status.configure(
                text=f"●  SDR  ·  {label}",
                text_color=color,
                fg_color=COLOR_PILL_MUTED_BG,
            )
        else:
            self.sdr_status.configure(
                text="●  SDR idle",
                text_color=COLOR_PILL_MUTED_FG,
                fg_color=COLOR_PILL_MUTED_BG,
            )

    def _on_board_status(self, running: bool, label: str) -> None:
        upper = (label or "").upper()
        if upper == "RUNNING":
            self.board_status.configure(
                text="●  Board running  ·  USB-TTL TX/RX",
                text_color=COLOR_PILL_OK_FG,
                fg_color=COLOR_PILL_OK_BG,
            )
        elif upper == "PAUSED":
            self.board_status.configure(
                text="●  Board paused  ·  USB-TTL",
                text_color=COLOR_ORANGE,
                fg_color=COLOR_ORANGE_BG,
            )
        elif upper == "ERROR":
            self.board_status.configure(
                text="●  Board error",
                text_color=COLOR_RED,
                fg_color=COLOR_PILL_MUTED_BG,
            )
        elif upper == "COMPLETED":
            self.board_status.configure(
                text="●  Board complete  ·  USB-TTL",
                text_color=COLOR_PILL_OK_FG,
                fg_color=COLOR_PILL_OK_BG,
            )
        else:
            self.board_status.configure(
                text="●  Board connected  ·  USB-TTL TX/RX",
                text_color=COLOR_PILL_OK_FG,
                fg_color=COLOR_PILL_OK_BG,
            )

    def _on_chunk_complete(self, message: str) -> None:
        self.show_view("compare")
        size = self.chunk_var.get()
        messagebox.showinfo(
            "Chunk complete",
            (message or f"{size}-row chunk finished.")
            + f"\n\nReview Comparison, then press RESUME on the Board tab for the next {size} rows.",
            parent=self,
        )

    def _maximize_window(self) -> None:
        """Use the full screen so Board content is not cramped under the toolbar."""
        try:
            if sys.platform == "darwin":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except Exception:
            try:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                self.geometry(f"{max(1280, sw - 40)}x{max(800, sh - 80)}+20+40")
            except Exception:
                pass

    def _pulse_status(self) -> None:
        self._pulse = (self._pulse + 1) % 24
        bright = self._pulse < 12
        try:
            text_b = self.board_status.cget("text") or ""
            if "running" in text_b.lower():
                self.board_status.configure(
                    text_color=COLOR_PILL_OK_FG if bright else COLOR_GREEN
                )
            text_s = self.sdr_status.cget("text") or ""
            if "listening" in text_s.lower() or "RUNNING" in text_s:
                self.sdr_status.configure(
                    text_color=COLOR_PILL_OK_FG if bright else COLOR_GREEN
                )
        except Exception:
            pass
        self.after(120, self._pulse_status)

    def _sdr_dongle_present(self) -> bool:
        try:
            from tpms_bench.hardware import check_hardware_trio

            return bool(check_hardware_trio().sdr.ok)
        except Exception:
            return False

    def _refresh_sdr_optional_badge(self) -> None:
        """Refresh SDR header badge from dongle / listen state."""
        try:
            text = str(self.sdr_status.cget("text") or "")
            if "LISTEN" in text.upper() or "RUNNING" in text.upper() or "PAUSED" in text.upper():
                return
            if self._sdr_dongle_present():
                self.sdr_status.configure(
                    text="●  SDR ready",
                    text_color=COLOR_PILL_OK_FG,
                    fg_color=COLOR_PILL_OK_BG,
                )
            else:
                self.sdr_status.configure(
                    text="●  SDR idle",
                    text_color=COLOR_PILL_MUTED_FG,
                    fg_color=COLOR_PILL_MUTED_BG,
                )
        except Exception:
            pass
        self.after(8000, self._refresh_sdr_optional_badge)

    def _shell_pause_tpms(self) -> None:
        if hasattr(self, "board_view"):
            self.board_view.toggle_pause()

    def _shell_pause_sdr(self) -> None:
        if hasattr(self, "sdr_view"):
            try:
                self.sdr_view._pause_listen()
            except Exception:
                pass

    def _shell_pause_all(self) -> None:
        self._shell_pause_tpms()
        self._shell_pause_sdr()

    def _shell_start_sdr(self) -> None:
        """Start SDR listening only (no Board run)."""
        if not hasattr(self, "sdr_view"):
            return
        if not self._sdr_dongle_present():
            messagebox.showinfo(
                "Start SDR",
                "No RTL-SDR dongle detected.\n\nPlug in an SDR and try again.",
                parent=self,
            )
            return
        self.show_view("sdr")
        try:
            self.sdr_view.restart_listen()
        except Exception:
            try:
                self.sdr_view.start_listen()
            except Exception:
                pass

    def _shell_stop(self) -> None:
        if hasattr(self, "board_view"):
            self.board_view.stop_test()

    def _shell_stop_sdr(self) -> None:
        if not hasattr(self, "sdr_view"):
            return
        try:
            self.sdr_view.release_after_board_session(
                reason="stop_sdr", message="Stop SDR — listening stopped"
            )
        except Exception:
            try:
                self.sdr_view._stop_listen()
            except Exception:
                pass

    def _shell_stop_all(self) -> None:
        """Stop Board and SDR listening."""
        self._shell_stop()
        self._shell_stop_sdr()

    def _start_board_run(self, run_full: bool = False, *, with_sdr: bool = False) -> None:
        """Start Board over USB-TTL. SDR compare is opt-in only."""
        if self.board_view.is_running():
            messagebox.showinfo("Start test", "Board test is already running.", parent=self)
            return
        self.show_view("board")
        if with_sdr:
            if not self._sdr_dongle_present():
                messagebox.showinfo(
                    "SDR not detected",
                    "No RTL-SDR dongle detected.\n\n"
                    "Starting Board-only on USB-TTL. Plug in an SDR and use Start TPMS + SDR for compare.",
                    parent=self,
                )
                self.board_view.start_test(skip_sdr=True, run_full=run_full)
                return
            self.show_view("sdr")
            self.sdr_view.restart_listen()
            self.after(3500, lambda: self._start_board_after_sdr(run_full))
            return
        # Default: Board-only — no SDR start, no wait.
        self.board_view.start_test(skip_sdr=True, run_full=run_full)

    def _start_both(self, run_full: bool = False) -> None:
        """Backward-compatible alias — Board-only unless FYRQOM_WITH_SDR=1."""
        with_sdr = os.environ.get("FYRQOM_WITH_SDR", "0") == "1"
        self._start_board_run(run_full=run_full, with_sdr=with_sdr)

    def _start_board_after_sdr(self, run_full: bool) -> None:
        if not self.sdr_view.is_running():
            self.sdr_view.restart_listen()
            self.after(2000, lambda: self.board_view.start_test(skip_sdr=False, run_full=run_full))
            return
        self.board_view.start_test(skip_sdr=False, run_full=run_full)

    def _build_comparison(self):
        sdr = self.sdr_view.get_sensor_snapshot()
        board = self.board_view.get_tested_rows()
        if not sdr and not board:
            messagebox.showinfo(
                "Comparative Analysis",
                "No results in the current session yet.\n\n"
                "Run the TPMS Board test and/or capture sensors on the SDR Receiver tab "
                "(Clear SDR session if you only want today's Board rows), then export again.",
                parent=self,
            )
            return None
        return build_comparison(sdr, board)

    def _export_comparative(self, kind: str) -> None:
        comparison = self._build_comparison()
        if comparison is None:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if kind == "pdf":
            title = "Save Comparative Analysis (PDF)"
            default = f"Comparative_Analysis_Report_{stamp}.pdf"
            filters = [("PDF — Comparative Analysis", "*.pdf"), ("All files", "*.*")]
            ext = ".pdf"
        else:
            title = "Save Comparative Analysis (Excel)"
            default = f"Comparative_Analysis_Report_{stamp}.xlsx"
            filters = [("Excel — Comparative Analysis", "*.xlsx"), ("All files", "*.*")]
            ext = ".xlsx"
        dest = ask_save_path(title, default, filters, ext, parent=self)
        if not dest:
            return
        try:
            if kind == "pdf":
                saved = export_comparative_pdf(dest, comparison)
            else:
                saved = export_comparative_excel(dest, comparison)
            messagebox.showinfo(
                "Comparative Analysis",
                (
                    f"Comparative Analysis ({kind.upper()}) saved — current session only.\n\n"
                    f"Board rows: {len(self.board_view.get_tested_rows())}  ·  "
                    f"SDR sensors: {len(self.sdr_view.get_sensor_snapshot())}\n"
                    f"Agree {comparison.agree} · Disagree {comparison.disagree} · "
                    f"Board only {comparison.board_only} · SDR only {comparison.sdr_only}\n"
                    f"Agreement rate: {comparison.agreement_rate:.1f}%\n\n{saved}"
                ),
                parent=self,
            )
            self._open_file(Path(saved))
        except Exception as error:
            messagebox.showerror("Comparative Analysis", str(error), parent=self)

    @staticmethod
    def _open_file(path: Path) -> None:
        try:
            if platform.system() == "Windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception:
            pass

    def _on_close(self) -> None:
        self.sdr_view.shutdown()
        self.board_view.shutdown()
        self.iq_view.shutdown()
        self.destroy()


def _acquire_single_instance() -> bool:
    """Allow only one TPMS Suite window — two instances fight over the RTL-SDR (usb_open)."""
    if platform.system() != "Windows":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # Keep a process-global handle so the mutex stays held for the app lifetime.
    global _INSTANCE_MUTEX  # noqa: PLW0603
    _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Local\\Xynovix_TPMS_Suite_SingleInstance")
    already = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    if already:
        messagebox.showerror(
            APP_TITLE,
            "TPMS Suite is already running.\n\n"
            "Close the other window first — two instances share one RTL-SDR and cause usb_open errors.",
        )
        return False
    return True


def run_app() -> None:
    if not _acquire_single_instance():
        return
    CombinedApp().mainloop()


_INSTANCE_MUTEX = None
