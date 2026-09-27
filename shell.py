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
from themes import (
    COLOR_BG,
    COLOR_BG_CARD,
    COLOR_BORDER,
    COLOR_BTN_EXPORT,
    COLOR_BTN_EXPORT_HOVER,
    COLOR_BTN_FULL,
    COLOR_BTN_FULL_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_BTN_PRIMARY_HOVER,
    COLOR_BTN_PRIMARY_TEXT,
    COLOR_GREEN,
    COLOR_HEADER_ACCENT,
    COLOR_HEADER_BG,
    COLOR_HEADER_SUB,
    COLOR_HEADER_TEXT,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_TAB_ACTIVE,
    COLOR_TAB_ACTIVE_TEXT,
    COLOR_TAB_BAR,
    COLOR_TAB_IDLE,
    COLOR_TAB_IDLE_HOVER,
    COLOR_TAB_IDLE_TEXT,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COMPANY_NAME,
    FYRQOM_LOGOTYPE,
    PRODUCT_NAME,
    combo_colors,
    ui_font,
)
from tpms_view import TpmsView

APP_TITLE = PRODUCT_NAME
APP_SUBTITLE = "Board programs codes   ·   SDR listens live   ·   USB / J-Link RX"


class CombinedApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        self.title(APP_TITLE)
        self.geometry("1440x920")
        self.minsize(1100, 720)
        self.configure(fg_color=COLOR_BG)
        self._active = "board"
        self.chunk_var = ctk.StringVar(value="100")
        self._pulse = 0
        self._build_chrome()
        self._build_views()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._pulse_status)
        if os.environ.get("FYRQOM_AUTOSTART") == "1":
            # Full catalog by default when launching a clean automated run.
            full = os.environ.get("FYRQOM_RUN_FULL", "1") == "1"
            self.after(1800, lambda: self._start_both(run_full=full))

    def _build_chrome(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLOR_HEADER_BG, corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", padx=18, pady=8)
        if FYRQOM_LOGOTYPE.is_file():
            from PIL import Image

            img = Image.open(FYRQOM_LOGOTYPE)
            self._logo_image = ctk.CTkImage(light_image=img, dark_image=img, size=(148, 44))
            ctk.CTkLabel(left, image=self._logo_image, text="").pack(side="left", padx=(0, 16))
        else:
            ctk.CTkLabel(
                left,
                text=COMPANY_NAME,
                font=ui_font(22, "bold"),
                text_color=COLOR_HEADER_TEXT,
            ).pack(side="left", padx=(0, 16))
        titles = ctk.CTkFrame(left, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(
            titles, text="TPMS  Suite", font=ui_font(16, "bold"), text_color=COLOR_HEADER_TEXT
        ).pack(anchor="w")
        ctk.CTkLabel(titles, text=APP_SUBTITLE, font=ui_font(11), text_color=COLOR_HEADER_SUB).pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=18)
        self.sdr_status = ctk.CTkLabel(
            right, text="SDR  ·  STOPPED", font=ui_font(12, "bold"), text_color=COLOR_HEADER_SUB,
            fg_color="#1C2426", corner_radius=12, width=140, height=28,
        )
        self.sdr_status.pack(side="right", padx=(10, 0))
        self.board_status = ctk.CTkLabel(
            right, text="BOARD  ·  IDLE", font=ui_font(12, "bold"), text_color=COLOR_HEADER_SUB,
            fg_color="#1C2426", corner_radius=12, width=140, height=28,
        )
        self.board_status.pack(side="right")

        nav = ctk.CTkFrame(self, fg_color=COLOR_BG)
        nav.pack(fill="x", padx=12, pady=(10, 0))

        tabs = ctk.CTkFrame(nav, fg_color=COLOR_TAB_BAR, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        tabs.pack(side="left", padx=(0, 10))
        self.board_tab = ctk.CTkButton(
            tabs, text="Board", width=112, height=34, font=ui_font(13, "bold"),
            corner_radius=10, command=lambda: self.show_view("board"),
        )
        self.board_tab.pack(side="left", padx=4, pady=4)
        self.sdr_tab = ctk.CTkButton(
            tabs, text="SDR Receiver", width=130, height=34, font=ui_font(13, "bold"),
            corner_radius=10, command=lambda: self.show_view("sdr"),
        )
        self.sdr_tab.pack(side="left", padx=(0, 4), pady=4)
        self.compare_tab = ctk.CTkButton(
            tabs, text="Comparison", width=120, height=34, font=ui_font(13, "bold"),
            corner_radius=10, command=lambda: self.show_view("compare"),
        )
        self.compare_tab.pack(side="left", padx=(0, 4), pady=4)
        self.iq_tab = ctk.CTkButton(
            tabs, text="IQ / URH", width=100, height=34, font=ui_font(13, "bold"),
            corner_radius=10, command=lambda: self.show_view("iq"),
        )
        self.iq_tab.pack(side="left", padx=(0, 4), pady=4)

        run_box = ctk.CTkFrame(nav, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        run_box.pack(side="left")
        ctk.CTkLabel(run_box, text="Chunk", font=ui_font(11, "bold"), text_color=COLOR_TEXT_DIM).pack(
            side="left", padx=(10, 4)
        )
        self.chunk_combo = ctk.CTkComboBox(
            run_box,
            values=["10", "25", "50", "100", "200", "500"],
            width=72,
            height=30,
            variable=self.chunk_var,
            **combo_colors(),
        )
        self.chunk_combo.set("100")
        self.chunk_combo.pack(side="left", padx=(0, 6), pady=4)
        ctk.CTkButton(
            run_box, text="Run chunk", width=108, height=30, font=ui_font(12, "bold"),
            fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER,
            text_color=COLOR_BTN_PRIMARY_TEXT,
            command=lambda: self._start_both(run_full=False),
        ).pack(side="left", padx=(0, 4), pady=4)
        ctk.CTkButton(
            run_box, text="Run full", width=96, height=30, font=ui_font(12, "bold"),
            fg_color=COLOR_BTN_FULL, hover_color=COLOR_BTN_FULL_HOVER,
            command=lambda: self._start_both(run_full=True),
        ).pack(side="left", padx=(0, 8), pady=4)

        ctk.CTkButton(
            nav, text="Compare PDF", width=118, height=32, font=ui_font(11, "bold"),
            fg_color=COLOR_BTN_EXPORT, hover_color=COLOR_BTN_EXPORT_HOVER,
            command=lambda: self._export_comparative("pdf"),
        ).pack(side="right")
        ctk.CTkButton(
            nav, text="Compare Excel", width=128, height=32, font=ui_font(11, "bold"),
            fg_color=COLOR_BTN_EXPORT, hover_color=COLOR_BTN_EXPORT_HOVER,
            command=lambda: self._export_comparative("xlsx"),
        ).pack(side="right", padx=(0, 6))

        self._accent = ctk.CTkFrame(self, fg_color=COLOR_HEADER_ACCENT, height=3, corner_radius=0)
        self._accent.pack(fill="x", pady=(8, 0))

        self.content = ctk.CTkFrame(self, fg_color=COLOR_BG)
        self.content.pack(fill="both", expand=True, padx=12, pady=8)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def _build_views(self) -> None:
        self.sdr_view = SdrView(self.content, on_status_change=self._on_sdr_status)
        self.board_view = TpmsView(
            self.content,
            on_status_change=self._on_board_status,
            on_chunk_complete=self._on_chunk_complete,
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
        self.sdr_view.grid(row=0, column=0, sticky="nsew")
        self.board_view.grid(row=0, column=0, sticky="nsew")
        self.compare_view.grid(row=0, column=0, sticky="nsew")
        self.iq_view.grid(row=0, column=0, sticky="nsew")
        self.board_view.live_sdr_get = self.sdr_view.get_sensor_snapshot
        self.board_view.on_board_rf = self.sdr_view.ingest_board_reading
        self.board_view.on_sdr_finalize = self.sdr_view.finalize_board_match
        self.show_view("board")

    def show_view(self, name: str) -> None:
        self._active = name
        self.board_view.grid_remove()
        self.sdr_view.grid_remove()
        self.compare_view.grid_remove()
        self.iq_view.grid_remove()
        self._paint_tab(self.board_tab, False)
        self._paint_tab(self.sdr_tab, False)
        self._paint_tab(self.compare_tab, False)
        self._paint_tab(self.iq_tab, False)
        if name == "sdr":
            self.sdr_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.sdr_tab, True)
        elif name == "compare":
            self.compare_view.grid(row=0, column=0, sticky="nsew")
            self._paint_tab(self.compare_tab, True)
            self.compare_view.refresh()
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
                fg_color=COLOR_TAB_ACTIVE,
                hover_color=COLOR_BG_CARD,
                text_color=COLOR_TAB_ACTIVE_TEXT,
                border_width=2,
                border_color=COLOR_HEADER_ACCENT,
            )
        else:
            button.configure(
                fg_color=COLOR_TAB_IDLE,
                hover_color=COLOR_TAB_IDLE_HOVER,
                text_color=COLOR_TAB_IDLE_TEXT,
                border_width=0,
            )

    def _on_sdr_status(self, running: bool, label: str) -> None:
        colors = {"RUNNING": COLOR_GREEN, "PAUSED": COLOR_ORANGE, "ERROR": COLOR_RED}
        self.sdr_status.configure(text=f"SDR  ·  {label}", text_color=colors.get(label, COLOR_HEADER_SUB))

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
        self.board_status.configure(text=f"BOARD  ·  {label}", text_color=color)

    def _on_chunk_complete(self, message: str) -> None:
        self.show_view("compare")
        size = self.chunk_var.get()
        messagebox.showinfo(
            "Chunk complete",
            (message or f"{size}-row chunk finished.")
            + f"\n\nReview Comparison, then press RESUME on the Board tab for the next {size} rows.",
            parent=self,
        )

    def _pulse_status(self) -> None:
        self._pulse = (self._pulse + 1) % 24
        bright = self._pulse < 12
        try:
            if "RUNNING" in (self.board_status.cget("text") or ""):
                self.board_status.configure(text_color=COLOR_GREEN if bright else "#7EE0C3")
            if "RUNNING" in (self.sdr_status.cget("text") or ""):
                self.sdr_status.configure(text_color=COLOR_GREEN if bright else "#7EE0C3")
            if hasattr(self, "_accent"):
                self._accent.configure(fg_color=COLOR_HEADER_ACCENT if bright else "#3ECFBE")
        except Exception:
            pass
        self.after(90, self._pulse_status)

    def _start_both(self, run_full: bool = False) -> None:
        """Start live SDR (reclaim dongle), then the Board bench."""
        if self.board_view.is_running():
            messagebox.showinfo("Start test", "Board test is already running.", parent=self)
            return
        # Always restart SDR so a replugged dongle is reopened before ABC codes.
        self.show_view("sdr")
        self.sdr_view.restart_listen()
        self.after(4500, lambda: self._start_board_after_sdr(run_full))

    def _start_board_after_sdr(self, run_full: bool) -> None:
        if not self.sdr_view.is_running():
            # One more try if the first open raced the USB re-enumerate.
            self.sdr_view.restart_listen()
            self.after(2000, lambda: self.board_view.start_test(skip_sdr=True, run_full=run_full))
            return
        self.board_view.start_test(skip_sdr=True, run_full=run_full)

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
