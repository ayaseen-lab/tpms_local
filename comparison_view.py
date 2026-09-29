"""Fyrqom Comparison tab — Board vs SDR agreement for the current chunk."""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk

from charts import CompareCharts, TelemetryCharts
from comparative_report import build_comparison
from themes import (
    COLOR_BG,
    COLOR_BG_CARD,
    COLOR_BLUE,
    COLOR_BLUE_BG,
    COLOR_BORDER,
    COLOR_BTN_EXPORT,
    COLOR_BTN_EXPORT_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_BTN_PRIMARY_HOVER,
    COLOR_BTN_PRIMARY_TEXT,
    COLOR_CYAN_BG,
    COLOR_GREEN,
    COLOR_GREEN_BG,
    COLOR_RED,
    COLOR_RED_BG,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_TEXT_MUTED,
)
from widgets import StatCard


class ComparisonView(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        get_sdr: Callable[[], dict],
        get_board: Callable[[], list[dict]],
        export_excel: Callable[[], None],
        export_pdf: Callable[[], None],
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._get_sdr = get_sdr
        self._get_board = get_board
        self._export_excel = export_excel
        self._export_pdf = export_pdf
        self._build()
        self.after(1500, self._auto_refresh)

    def _build(self) -> None:
        head = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        head.pack(fill="x", pady=(0, 8))
        inner = ctk.CTkFrame(head, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(
            inner,
            text="Comparison",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            inner,
            text="Same CODE A / B / C  ·  Board and SDR must agree before the next row",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
        ).pack(side="left", padx=14)
        ctk.CTkButton(
            inner,
            text="Export PDF",
            width=120,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            command=self._export_pdf,
        ).pack(side="right")
        ctk.CTkButton(
            inner,
            text="Export Excel",
            width=120,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            command=self._export_excel,
        ).pack(side="right", padx=(0, 8))
        ctk.CTkButton(
            inner,
            text="Refresh",
            width=100,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BTN_PRIMARY,
            hover_color=COLOR_BTN_PRIMARY_HOVER,
            text_color=COLOR_BTN_PRIMARY_TEXT,
            command=self.refresh,
        ).pack(side="right", padx=(0, 8))

        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 8))
        self.agree_card = StatCard(stats, "AGREE", "0", COLOR_GREEN, COLOR_GREEN_BG)
        self.disagree_card = StatCard(stats, "DISAGREE", "0", COLOR_RED, COLOR_RED_BG)
        self.rate_card = StatCard(stats, "AGREEMENT", "—", COLOR_TEXT, COLOR_BG_CARD)
        self.board_card = StatCard(stats, "BOARD ROWS", "0", COLOR_TEXT_DIM, COLOR_BG_CARD)
        self.sdr_card = StatCard(stats, "SDR MATCHES", "0", COLOR_BLUE, COLOR_BLUE_BG)
        for card in (self.agree_card, self.disagree_card, self.rate_card, self.board_card, self.sdr_card):
            card.pack(side="left", expand=True, fill="x", padx=4)

        self.charts = CompareCharts(self, height=240)
        self.charts.pack(fill="x", pady=(0, 8))
        self.telemetry_charts = TelemetryCharts(
            self,
            height=110,
            title="Comparison live mix",
            series_titles=("Agree", "Disagree", "Board+SDR"),
        )
        self.telemetry_charts.pack(fill="x", pady=(0, 8))

        table = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        table.pack(fill="both", expand=True)
        host = tk.Frame(table, bg=COLOR_BG_CARD)
        host.pack(fill="both", expand=True, padx=8, pady=8)
        cols = ("row", "vehicle", "id", "board", "sdr", "verdict", "reason")
        self.tree = ttk.Treeview(host, columns=cols, show="headings", height=16, style="Combined.Treeview")
        heads = {
            "row": "#",
            "vehicle": "Vehicle",
            "id": "Sensor ID",
            "board": "Board",
            "sdr": "SDR",
            "verdict": "Comparison",
            "reason": "Notes",
        }
        widths = {"row": 60, "vehicle": 200, "id": 130, "board": 80, "sdr": 80, "verdict": 120, "reason": 360}
        for col in cols:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], minwidth=40, stretch=col == "reason")
        scroll = ttk.Scrollbar(host, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("AGREE", background=COLOR_GREEN_BG, foreground="#047857")
        self.tree.tag_configure("DISAGREE", background=COLOR_RED_BG, foreground="#B91C1C")
        self.tree.tag_configure("ONLY", background=COLOR_CYAN_BG, foreground=COLOR_TEXT)

        self.footer = ctk.CTkLabel(
            self,
            text="Choose a chunk size or Run full. Graphs update with each result.",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
        )
        self.footer.pack(anchor="w", pady=(8, 0))

    def refresh(self) -> None:
        sdr = self._get_sdr() or {}
        board = self._get_board() or []
        comparison = build_comparison(sdr, board)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in comparison.rows:
            verdict = (row.verdict or "").upper()
            tag = "AGREE" if "AGREE" in verdict and "DIS" not in verdict else (
                "DISAGREE" if "DIS" in verdict else "ONLY"
            )
            self.tree.insert(
                "",
                "end",
                values=(
                    row.excel_row or "—",
                    row.vehicle or "—",
                    row.sensor_id or "—",
                    row.board_result or "—",
                    row.sdr_result or "—",
                    row.verdict or "—",
                    (row.board_reason or row.sdr_reason or "")[:120],
                ),
                tags=(tag,),
            )
        self.agree_card.set_value(str(comparison.agree))
        self.disagree_card.set_value(str(comparison.disagree))
        self.rate_card.set_value(f"{comparison.agreement_rate:.1f}%" if comparison.matched else "—")
        self.board_card.set_value(str(comparison.board_rows))
        self.sdr_card.set_value(str(comparison.sdr_matches))
        self.footer.configure(
            text=(
                f"{len(comparison.rows)} lines  ·  "
                f"Agree {comparison.agree}  ·  Disagree {comparison.disagree}  ·  "
                f"Board rows {comparison.board_rows}  ·  SDR matches {comparison.sdr_matches}  ·  "
                f"{comparison.sdr_ids} unique SDR ID(s)"
            )
        )
        board_ok = sum(1 for row in board if str(row.get("board_performance") or "").upper() == "OK")
        board_nok = sum(1 for row in board if str(row.get("board_performance") or "").upper() == "NOK")
        self.charts.set_comparison(
            board_ok=board_ok,
            board_nok=board_nok,
            agree=comparison.agree,
            disagree=comparison.disagree,
            board_only=comparison.board_only,
            sdr_only=comparison.sdr_only,
        )
        if hasattr(self, "telemetry_charts"):
            self.telemetry_charts.push(
                a=float(comparison.agree),
                b=float(comparison.disagree),
                c=float(comparison.agree + comparison.disagree),
            )

    def _auto_refresh(self) -> None:
        try:
            if self.winfo_ismapped():
                self.refresh()
        except Exception:
            pass
        self.after(2000, self._auto_refresh)
