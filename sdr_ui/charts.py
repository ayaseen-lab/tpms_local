"""Result charts drawn with Tk canvas — no extra dependency."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from themes import (
    COLOR_BG_CARD,
    COLOR_BLUE,
    COLOR_BORDER,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_TEXT_MUTED,
    ui_font,
)


def _slice(c: tk.Canvas, cx: float, cy: float, r: float, start: float, extent: float, color: str) -> None:
    if abs(extent) < 0.8:
        return
    c.create_arc(
        cx - r, cy - r, cx + r, cy + r,
        start=start, extent=extent, style="pieslice",
        fill=color, outline=COLOR_BG_CARD, width=2,
    )


class ResultCharts(ctk.CTkFrame):
    """Pass/fail donut plus a rolling OK/NOK bar history."""

    def __init__(self, master, *, height: int = 168, title: str = "Results graphs", **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG_CARD)
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._ok = 0
        self._nok = 0
        self._history: list[str] = []
        self._anim = 1.0

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=ui_font(12, "bold"), text_color=COLOR_TEXT).pack(side="left")
        self.caption = ctk.CTkLabel(head, text="No results yet", font=ui_font(11), text_color=COLOR_TEXT_MUTED)
        self.caption.pack(side="right")

        host = tk.Frame(self, bg=COLOR_BG_CARD, height=height)
        host.pack(fill="x", padx=8, pady=8)
        host.pack_propagate(False)
        self.canvas = tk.Canvas(host, bg=COLOR_BG_CARD, highlightthickness=0, height=height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._paint())

    def set_counts(self, ok: int, nok: int, history: list[str] | None = None) -> None:
        self._ok = max(0, int(ok))
        self._nok = max(0, int(nok))
        if history is not None:
            self._history = [str(x).upper() for x in history][-40:]
        done = self._ok + self._nok
        rate = (self._ok / done * 100.0) if done else 0.0
        self.caption.configure(
            text=f"{done} tested   ·   {self._ok} OK   ·   {self._nok} NOK   ·   {rate:.1f}% pass"
            if done
            else "No results yet"
        )
        self._paint()

    def add_result(self, performance: str) -> None:
        tag = str(performance or "").strip().upper()
        if tag == "OK":
            self._ok += 1
        elif tag == "NOK":
            self._nok += 1
        else:
            return
        self._history.append(tag)
        self._history = self._history[-40:]
        self.set_counts(self._ok, self._nok, self._history)

    def reset(self) -> None:
        self._ok = 0
        self._nok = 0
        self._history.clear()
        self.set_counts(0, 0, [])

    def _paint(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(int(c.winfo_width() or 0), 240)
        h = max(int(c.winfo_height() or 0), 110)
        pad = 10
        box = min(h - 20, 130)
        cx, cy, r = pad + box / 2, h / 2 - 4, box / 2 - 8
        ok, nok = self._ok, self._nok
        total = ok + nok
        if total <= 0:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#D5DEDC", width=16)
            c.create_text(cx, cy, text="0", fill=COLOR_TEXT, font=("Helvetica Neue", 20, "bold"))
        else:
            ok_ext = 360.0 * ok / total
            _slice(c, cx, cy, r, 90, -ok_ext, COLOR_GREEN)
            _slice(c, cx, cy, r, 90 - ok_ext, -(360.0 - ok_ext), COLOR_RED)
            hole = r * 0.55
            c.create_oval(cx - hole, cy - hole, cx + hole, cy + hole, fill=COLOR_BG_CARD, outline="")
            c.create_text(cx, cy - 6, text=str(total), fill=COLOR_TEXT, font=("Helvetica Neue", 20, "bold"))
            c.create_text(cx, cy + 14, text="tested", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 9))

        left = pad + box + 18
        right = w - pad
        top, bottom = 22, h - 22
        c.create_text(left, 10, text="Last rows", fill=COLOR_TEXT_DIM, font=("Helvetica Neue", 10, "bold"), anchor="w")
        bars = self._history
        slots = max(12, min(36, len(bars) or 12))
        bw = max(5, int((right - left) / slots) - 2)
        for i in range(slots):
            x = left + i * (bw + 2)
            if i < len(bars):
                color = COLOR_GREEN if bars[i] == "OK" else COLOR_RED
                c.create_rectangle(x, top, x + bw, bottom, fill=color, outline="")
            else:
                c.create_rectangle(x, bottom - 6, x + bw, bottom, fill="#E4EBEA", outline="")
        c.create_text(left, h - 8, text=f"OK {ok}     NOK {nok}", fill=COLOR_TEXT, font=("Helvetica Neue", 10, "bold"), anchor="w")


class CompareCharts(ctk.CTkFrame):
    """Two real graphs: Board OK/NOK and Comparison mix (agree / disagree / only)."""

    def __init__(self, master, *, height: int = 220, **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG_CARD)
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._board_ok = 0
        self._board_nok = 0
        self._agree = 0
        self._disagree = 0
        self._board_only = 0
        self._sdr_only = 0

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text="Comparison graphs", font=ui_font(13, "bold"), text_color=COLOR_TEXT).pack(side="left")
        self.caption = ctk.CTkLabel(head, text="Waiting for Board and SDR results", font=ui_font(11), text_color=COLOR_TEXT_MUTED)
        self.caption.pack(side="right")

        host = tk.Frame(self, bg=COLOR_BG_CARD, height=height)
        host.pack(fill="both", expand=True, padx=8, pady=8)
        host.pack_propagate(False)
        self.canvas = tk.Canvas(host, bg=COLOR_BG_CARD, highlightthickness=0, height=height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._paint())

    def set_comparison(
        self,
        *,
        board_ok: int,
        board_nok: int,
        agree: int,
        disagree: int,
        board_only: int,
        sdr_only: int,
    ) -> None:
        self._board_ok = max(0, int(board_ok))
        self._board_nok = max(0, int(board_nok))
        self._agree = max(0, int(agree))
        self._disagree = max(0, int(disagree))
        self._board_only = max(0, int(board_only))
        self._sdr_only = max(0, int(sdr_only))
        total = self._board_ok + self._board_nok
        mix = self._agree + self._disagree + self._board_only + self._sdr_only
        if total or mix:
            self.caption.configure(
                text=(
                    f"Board {total} rows ({self._board_ok} OK / {self._board_nok} NOK)   ·   "
                    f"Agree {self._agree}  Disagree {self._disagree}  "
                    f"Board only {self._board_only}  SDR only {self._sdr_only}"
                )
            )
        else:
            self.caption.configure(text="Waiting for Board and SDR results")
        self._paint()

    def set_agreement(self, agree: int, disagree: int) -> None:
        self.set_comparison(
            board_ok=agree,
            board_nok=disagree,
            agree=agree,
            disagree=disagree,
            board_only=0,
            sdr_only=0,
        )

    def _paint(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(int(c.winfo_width() or 0), 400)
        h = max(int(c.winfo_height() or 0), 180)
        mid = w * 0.42
        self._paint_board(c, 12, mid - 10, h)
        self._paint_mix(c, mid + 10, w - 12, h)

    def _paint_board(self, c: tk.Canvas, left: float, right: float, h: int) -> None:
        c.create_text(left, 12, text="Board results", fill=COLOR_TEXT, font=("Helvetica Neue", 12, "bold"), anchor="w")
        ok, nok = self._board_ok, self._board_nok
        total = ok + nok
        cx = left + 70
        cy = h / 2 + 6
        r = min(58, (h - 50) / 2)
        if total <= 0:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#D5DEDC", width=14)
            c.create_text(cx, cy, text="0", fill=COLOR_TEXT, font=("Helvetica Neue", 18, "bold"))
        else:
            ok_ext = 360.0 * ok / total
            _slice(c, cx, cy, r, 90, -ok_ext, COLOR_GREEN)
            _slice(c, cx, cy, r, 90 - ok_ext, -(360.0 - ok_ext), COLOR_RED)
            hole = r * 0.52
            c.create_oval(cx - hole, cy - hole, cx + hole, cy + hole, fill=COLOR_BG_CARD, outline="")
            c.create_text(cx, cy - 6, text=str(total), fill=COLOR_TEXT, font=("Helvetica Neue", 18, "bold"))
            c.create_text(cx, cy + 12, text="rows", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 9))
        lx = cx + r + 16
        for i, (label, n, color) in enumerate(
            (("OK", ok, COLOR_GREEN), ("NOK", nok, COLOR_RED))
        ):
            y = 48 + i * 28
            c.create_rectangle(lx, y, lx + 12, y + 12, fill=color, outline="")
            c.create_text(lx + 18, y + 6, text=f"{label}   {n}", fill=COLOR_TEXT, font=("Helvetica Neue", 12, "bold"), anchor="w")
        if total:
            rate = 100.0 * ok / total
            c.create_text(lx, 48 + 64, text=f"Pass  {rate:.1f}%", fill=COLOR_TEXT_DIM, font=("Helvetica Neue", 11), anchor="w")

    def _paint_mix(self, c: tk.Canvas, left: float, right: float, h: int) -> None:
        c.create_text(left, 12, text="Board vs SDR", fill=COLOR_TEXT, font=("Helvetica Neue", 12, "bold"), anchor="w")
        items = (
            ("Agree", self._agree, COLOR_GREEN),
            ("Disagree", self._disagree, COLOR_RED),
            ("Board only", self._board_only, COLOR_ORANGE),
            ("SDR only", self._sdr_only, COLOR_BLUE),
        )
        top, bottom = 36, h - 28
        span = max(80, bottom - top)
        max_n = max((n for _l, n, _c in items), default=0)
        slot = max(36, (right - left) / 4)
        bar_w = min(46, slot * 0.55)
        for i, (label, n, color) in enumerate(items):
            x = left + i * slot + (slot - bar_w) / 2
            bh = 8 if max_n <= 0 else max(8, int(span * (n / max_n)))
            y0 = bottom - bh
            c.create_rectangle(x, y0, x + bar_w, bottom, fill=color, outline="")
            c.create_text(x + bar_w / 2, y0 - 12, text=str(n), fill=COLOR_TEXT, font=("Helvetica Neue", 12, "bold"))
            c.create_text(x + bar_w / 2, bottom + 12, text=label, fill=COLOR_TEXT_DIM, font=("Helvetica Neue", 9))
