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
from dialogs import ask_save_path
from iq_urh_tool import IqUrhView
from themes import (
    COLOR_BG,
    COLOR_BTN_EXPORT,
    COLOR_BTN_EXPORT_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_BTN_PRIMARY_HOVER,
    COLOR_GREEN,
    COLOR_HEADER_ACCENT,
    COLOR_HEADER_BG,
    COLOR_HEADER_SUB,
    COLOR_HEADER_TEXT,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_TAB_IDLE,
    COLOR_TAB_IDLE_HOVER,
    COLOR_TEXT_DIM,
)
from tpms_view import TpmsView

APP_TITLE = "TPMS Suite"
APP_SUBTITLE = "TPMS Board  ·  SDR Receiver  ·  IQ / URH  ·  switch views without stopping a run"


class CombinedApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        self.title(APP_TITLE)
        self.geometry("1380x900")
        self.minsize(1100, 720)
        self.configure(fg_color=COLOR_BG)
        self._active = "board"
        self._build_chrome()
        self._build_views()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_chrome(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLOR_HEADER_BG, corner_radius=0, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", padx=16, pady=6)
        ctk.CTkLabel(
            left, text=APP_TITLE.upper(), font=ctk.CTkFont(size=16, weight="bold"), text_color=COLOR_HEADER_TEXT
        ).pack(anchor="w")
        ctk.CTkLabel(left, text=APP_SUBTITLE, font=ctk.CTkFont(size=11), text_color=COLOR_HEADER_SUB).pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=20)

        self.sdr_status = ctk.CTkLabel(
            right, text="SDR ● STOPPED", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_HEADER_SUB
        )
        self.sdr_status.pack(side="right", padx=(16, 0))
        self.board_status = ctk.CTkLabel(
            right, text="BOARD ● IDLE", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_HEADER_SUB
        )
        self.board_status.pack(side="right")

        nav = ctk.CTkFrame(self, fg_color=COLOR_BG)
        nav.pack(fill="x", padx=12, pady=(8, 0))
        self.board_tab = ctk.CTkButton(
            nav,
            text="TPMS Board",
            width=160,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.show_view("board"),
        )
        self.board_tab.pack(side="left", padx=(0, 8))
        self.sdr_tab = ctk.CTkButton(
            nav,
            text="SDR Receiver",
            width=160,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.show_view("sdr"),
        )
        self.sdr_tab.pack(side="left", padx=(0, 8))
        self.iq_tab = ctk.CTkButton(
            nav,
            text="IQ / URH",
            width=140,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.show_view("iq"),
        )
        self.iq_tab.pack(side="left")
        ctk.CTkLabel(
            nav,
            text="Tabs switch view only — runs keep going.",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM,
        ).pack(side="left", padx=12)

        # Always-visible: start both + comparative exports (not in a menu / not below the fold).
        ctk.CTkButton(
            nav,
            text="Compare PDF",
            width=120,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            command=lambda: self._export_comparative("pdf"),
        ).pack(side="right")
        ctk.CTkButton(
            nav,
            text="Compare Excel",
            width=130,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            command=lambda: self._export_comparative("xlsx"),
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            nav,
            text="Start Both",
            width=120,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_PRIMARY,
            hover_color=COLOR_BTN_PRIMARY_HOVER,
            command=self._start_both,
        ).pack(side="right", padx=(0, 10))

        accent = ctk.CTkFrame(self, fg_color=COLOR_HEADER_ACCENT, height=3, corner_radius=0)
        accent.pack(fill="x", pady=(8, 0))

        self.content = ctk.CTkFrame(self, fg_color=COLOR_BG)
        self.content.pack(fill="both", expand=True, padx=12, pady=8)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def _build_views(self) -> None:
        self.sdr_view = SdrView(self.content, on_status_change=self._on_sdr_status)
        self.board_view = TpmsView(self.content, on_status_change=self._on_board_status)
        self.iq_view = IqUrhView(self.content)
        # All stay created so processing continues; only the active view is mapped
        # so CODE A/B/C fields can take keyboard focus.
        self.sdr_view.grid(row=0, column=0, sticky="nsew")
        self.board_view.grid(row=0, column=0, sticky="nsew")
        self.iq_view.grid(row=0, column=0, sticky="nsew")
        self.show_view("board")

    def show_view(self, name: str) -> None:
        self._active = name
        self.board_view.grid_remove()
        self.sdr_view.grid_remove()
        self.iq_view.grid_remove()
        self._paint_tab(self.board_tab, False)
        self._paint_tab(self.sdr_tab, False)
        self._paint_tab(self.iq_tab, False)
        if name == "sdr":
            self.sdr_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.sdr_tab, True)
        elif name == "iq":
            self.iq_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.iq_tab, True)
        else:
            self.board_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.board_tab, True)
            self.after(50, self.board_view.focus_code_fields)

    def _paint_tab(self, button: ctk.CTkButton, active: bool) -> None:
        if active:
            button.configure(fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER, text_color="#ffffff")
        else:
            button.configure(fg_color=COLOR_TAB_IDLE, hover_color=COLOR_TAB_IDLE_HOVER, text_color="#ffffff")

    def _on_sdr_status(self, running: bool, label: str) -> None:
        colors = {"RUNNING": COLOR_GREEN, "PAUSED": COLOR_ORANGE, "ERROR": COLOR_RED}
        self.sdr_status.configure(text=f"SDR ● {label}", text_color=colors.get(label, COLOR_HEADER_SUB))

    def _on_board_status(self, running: bool, label: str) -> None:
        color = COLOR_HEADER_SUB
        if label == "RUNNING":
            color = COLOR_GREEN
        elif label == "PAUSED":
            color = COLOR_ORANGE
        elif label == "ERROR":
            color = COLOR_RED
        elif label == "COMPLETED":
            color = COLOR_HEADER_ACCENT
        self.board_status.configure(text=f"BOARD ● {label}", text_color=color)

    def _start_both(self) -> None:
        """Start SDR Receiver listening and TPMS Board test together.

        Board live IQ capture is skipped so both can share one RTL-SDR: the SDR tab
        collects RF for the comparative report while the Board runs the Hamaton bench.
        """
        if self.board_view.is_running() and self.sdr_view.is_running():
            messagebox.showinfo(
                "Start Both",
                "Both the TPMS Board test and SDR Receiver are already running.",
                parent=self,
            )
            return

        # Validate / start Board first (needs Excel or codes); skip Board IQ capture.
        if not self.board_view.is_running():
            started = self.board_view.start_test(skip_sdr=True)
            if not started:
                return

        if not self.sdr_view.is_running():
            self.sdr_view.start_listen()

        messagebox.showinfo(
            "Start Both",
            "Started TPMS Board and SDR Receiver together.\n\n"
            "• Board: Hamaton bench (live IQ capture off — dongle free for SDR tab)\n"
            "• SDR: listening for RF — use Compare Excel/PDF when both have IDs\n\n"
            "Keep the SDR Receiver tab band set to your sensor frequency.",
            parent=self,
        )

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


def run_app() -> None:
    CombinedApp().mainloop()
