"""Result charts drawn with Tk canvas — no extra dependency."""

from __future__ import annotations

import time
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


class _ThrottledPaint:
    """Coalesce canvas redraws so dense RSSI packets cannot freeze Tk."""

    _PAINT_MIN_MS = 80

    def _request_paint(self) -> None:
        try:
            if not self.winfo_ismapped():
                return
        except tk.TclError:
            return
        now = time.monotonic()
        last = getattr(self, "_last_paint_ts", 0.0)
        pending = getattr(self, "_paint_pending", False)
        wait_ms = self._PAINT_MIN_MS - (now - last) * 1000.0
        if wait_ms <= 0:
            self._last_paint_ts = now
            self._paint_pending = False
            self._paint()
            return
        if pending:
            return
        self._paint_pending = True
        try:
            self.after(max(16, int(wait_ms)), self._deferred_paint)
        except tk.TclError:
            self._paint_pending = False

    def _deferred_paint(self) -> None:
        self._paint_pending = False
        self._last_paint_ts = time.monotonic()
        try:
            if self.winfo_ismapped():
                self._paint()
        except tk.TclError:
            pass


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


class BoardTrendCharts(ctk.CTkFrame):
    """Board-only visuals: pass-rate trend, cumulative OK/NOK, battery histogram."""

    def __init__(self, master, *, height: int = 130, title: str = "Board trend graphs", **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG_CARD)
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._results: list[str] = []
        self._volts: list[float] = []
        self._temps: list[float] = []
        self._maxlen = 80

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=ui_font(12, "bold"), text_color=COLOR_TEXT).pack(side="left")
        self.caption = ctk.CTkLabel(head, text="Waiting for Board results…", font=ui_font(11), text_color=COLOR_TEXT_MUTED)
        self.caption.pack(side="right")

        host = tk.Frame(self, bg=COLOR_BG_CARD, height=height)
        host.pack(fill="x", padx=8, pady=8)
        host.pack_propagate(False)
        self.canvas = tk.Canvas(host, bg=COLOR_BG_CARD, highlightthickness=0, height=height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._paint())

    def push(
        self,
        *,
        result: str | None = None,
        voltage: float | None = None,
        temp: float | None = None,
    ) -> None:
        tag = str(result or "").strip().upper()
        if tag in {"OK", "NOK"}:
            self._results.append(tag)
            self._results = self._results[-self._maxlen :]
        if voltage is not None:
            try:
                self._volts.append(float(voltage))
                self._volts = self._volts[-self._maxlen :]
            except (TypeError, ValueError):
                pass
        if temp is not None:
            try:
                self._temps.append(float(temp))
                self._temps = self._temps[-self._maxlen :]
            except (TypeError, ValueError):
                pass
        self._update_caption()
        self._paint()

    def set_from_history(
        self,
        results: list[str] | None = None,
        voltages: list[float] | None = None,
        temps: list[float] | None = None,
    ) -> None:
        if results is not None:
            self._results = [str(x).upper() for x in results if str(x).upper() in {"OK", "NOK"}][-self._maxlen :]
        if voltages is not None:
            self._volts = [float(v) for v in voltages if v is not None][-self._maxlen :]
        if temps is not None:
            self._temps = [float(t) for t in temps if t is not None][-self._maxlen :]
        self._update_caption()
        self._paint()

    def reset(self) -> None:
        self._results.clear()
        self._volts.clear()
        self._temps.clear()
        self.caption.configure(text="Waiting for Board results…")
        self._paint()

    def _update_caption(self) -> None:
        ok = sum(1 for r in self._results if r == "OK")
        nok = sum(1 for r in self._results if r == "NOK")
        done = ok + nok
        rate = (100.0 * ok / done) if done else 0.0
        parts = [f"{done} rows", f"{rate:.1f}% pass"]
        if self._volts:
            parts.append(f"batt {self._volts[-1]:.2f} V")
        self.caption.configure(text="   ·   ".join(parts))

    def _paint(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(int(c.winfo_width() or 0), 360)
        h = max(int(c.winfo_height() or 0), 110)
        gap = 10
        panel_w = (w - gap * 4) / 3
        self._paint_pass_rate(c, gap, gap + panel_w, 8, h - 8)
        self._paint_cumulative(c, gap * 2 + panel_w, gap * 2 + panel_w * 2, 8, h - 8)
        self._paint_volt_hist(c, gap * 3 + panel_w * 2, gap * 3 + panel_w * 3, 8, h - 8)

    def _panel(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float, title: str) -> tuple[float, float, float, float]:
        c.create_rectangle(left, top, right, bottom, fill="#F7FBFA", outline="#E2EEEC")
        c.create_text(left + 8, top + 12, text=title, fill=COLOR_TEXT_DIM, font=("Helvetica Neue", 9, "bold"), anchor="w")
        return left + 10, right - 10, top + 26, bottom - 12

    def _paint_pass_rate(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float) -> None:
        pl, pr, pt, pb = self._panel(c, left, right, top, bottom, "Pass rate trend (%)")
        if len(self._results) < 2:
            c.create_text((left + right) / 2, (top + bottom) / 2 + 6, text="no data", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 10))
            return
        rates: list[float] = []
        ok = 0
        for i, tag in enumerate(self._results, start=1):
            if tag == "OK":
                ok += 1
            rates.append(100.0 * ok / i)
        # Area fill under curve.
        pts: list[float] = []
        for i, rate in enumerate(rates):
            x = pl + (pr - pl) * (i / max(1, len(rates) - 1))
            y = pb - (pb - pt) * (rate / 100.0)
            pts.extend([x, y])
        area = [pl, pb] + pts + [pr, pb]
        c.create_polygon(*area, fill="#D1FAE5", outline="")
        c.create_line(*pts, fill=COLOR_GREEN, width=2, smooth=True)
        c.create_text(pr, top + 12, text=f"{rates[-1]:.1f}%", fill=COLOR_TEXT, font=("Helvetica Neue", 10, "bold"), anchor="e")

    def _paint_cumulative(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float) -> None:
        pl, pr, pt, pb = self._panel(c, left, right, top, bottom, "Cumulative OK / NOK")
        if not self._results:
            c.create_text((left + right) / 2, (top + bottom) / 2 + 6, text="no data", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 10))
            return
        ok_c: list[float] = []
        nok_c: list[float] = []
        ok = nok = 0
        for tag in self._results:
            if tag == "OK":
                ok += 1
            else:
                nok += 1
            ok_c.append(float(ok))
            nok_c.append(float(nok))
        hi = max(ok_c[-1], nok_c[-1], 1.0)

        def _line(series: list[float], color: str) -> None:
            pts: list[float] = []
            for i, val in enumerate(series):
                x = pl + (pr - pl) * (i / max(1, len(series) - 1))
                y = pb - (pb - pt) * (val / hi)
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=2)

        _line(ok_c, COLOR_GREEN)
        _line(nok_c, COLOR_RED)
        c.create_text(pl, pb + 2, text=f"OK {int(ok_c[-1])}", fill=COLOR_GREEN, font=("Helvetica Neue", 8, "bold"), anchor="nw")
        c.create_text(pr, pb + 2, text=f"NOK {int(nok_c[-1])}", fill=COLOR_RED, font=("Helvetica Neue", 8, "bold"), anchor="ne")

    def _paint_volt_hist(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float) -> None:
        pl, pr, pt, pb = self._panel(c, left, right, top, bottom, "Battery voltage (hist)")
        series = self._volts if self._volts else self._temps
        label_empty = "no voltage yet" if not self._volts else "no data"
        if len(series) < 1:
            c.create_text((left + right) / 2, (top + bottom) / 2 + 6, text=label_empty, fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 10))
            return
        bins = 8
        lo, hi = min(series), max(series)
        if abs(hi - lo) < 1e-9:
            lo, hi = lo - 0.1, hi + 0.1
        counts = [0] * bins
        for v in series:
            idx = int((v - lo) / (hi - lo) * bins)
            idx = min(bins - 1, max(0, idx))
            counts[idx] += 1
        peak = max(counts) or 1
        bw = (pr - pl) / bins - 2
        for i, n in enumerate(counts):
            x0 = pl + i * ((pr - pl) / bins) + 1
            bh = max(2, (pb - pt) * (n / peak))
            c.create_rectangle(x0, pb - bh, x0 + bw, pb, fill=COLOR_ORANGE if self._volts else COLOR_BLUE, outline="")
        c.create_text(pl, top + 12, text=f"{lo:.2f}", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 8), anchor="w")
        c.create_text(pr, top + 12, text=f"{hi:.2f}", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 8), anchor="e")


class SdrRfCharts(_ThrottledPaint, ctk.CTkFrame):
    """SDR-only visuals: RSSI histogram, signal scatter, unique-ID growth."""

    def __init__(self, master, *, height: int = 130, title: str = "SDR RF graphs", **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG_CARD)
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._rssi: list[float] = []
        self._snr: list[float] = []
        self._unique_counts: list[int] = []
        self._seen: set[str] = set()
        self._ok = 0
        self._nok = 0
        self._maxlen = 64
        teal = "#0D9488"
        self._teal = teal

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=ui_font(12, "bold"), text_color=COLOR_TEXT).pack(side="left")
        self.caption = ctk.CTkLabel(head, text="Waiting for RF packets…", font=ui_font(11), text_color=COLOR_TEXT_MUTED)
        self.caption.pack(side="right")

        host = tk.Frame(self, bg=COLOR_BG_CARD, height=height)
        host.pack(fill="x", padx=8, pady=8)
        host.pack_propagate(False)
        self.canvas = tk.Canvas(host, bg=COLOR_BG_CARD, highlightthickness=0, height=height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._paint())

    def push(
        self,
        *,
        rssi: float | None = None,
        snr: float | None = None,
        sensor_id: str | None = None,
        result: str | None = None,
    ) -> None:
        if rssi is not None:
            try:
                self._rssi.append(float(rssi))
                self._rssi = self._rssi[-self._maxlen :]
            except (TypeError, ValueError):
                pass
        if snr is not None:
            try:
                self._snr.append(float(snr))
                self._snr = self._snr[-self._maxlen :]
            except (TypeError, ValueError):
                pass
        sid = str(sensor_id or "").strip().upper()
        if sid:
            self._seen.add(sid)
        self._unique_counts.append(len(self._seen))
        self._unique_counts = self._unique_counts[-self._maxlen :]
        tag = str(result or "").strip().upper()
        if tag == "OK":
            self._ok += 1
        elif tag == "NOK":
            self._nok += 1
        parts = []
        if self._rssi:
            parts.append(f"RSSI {self._rssi[-1]:.1f} dB")
        parts.append(f"{len(self._seen)} unique IDs")
        if self._ok or self._nok:
            parts.append(f"OK {self._ok} / NOK {self._nok}")
        self.caption.configure(text="   ·   ".join(parts) if parts else "Waiting for RF packets…")
        self._request_paint()

    def set_counts(self, ok: int, nok: int) -> None:
        self._ok = max(0, int(ok))
        self._nok = max(0, int(nok))
        self._paint()

    def reset(self) -> None:
        self._rssi.clear()
        self._snr.clear()
        self._unique_counts.clear()
        self._seen.clear()
        self._ok = 0
        self._nok = 0
        self.caption.configure(text="Waiting for RF packets…")
        self._paint()

    def _paint(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(int(c.winfo_width() or 0), 360)
        h = max(int(c.winfo_height() or 0), 110)
        gap = 10
        panel_w = (w - gap * 4) / 3
        self._paint_rssi_hist(c, gap, gap + panel_w, 8, h - 8)
        self._paint_scatter(c, gap * 2 + panel_w, gap * 2 + panel_w * 2, 8, h - 8)
        self._paint_unique(c, gap * 3 + panel_w * 2, gap * 3 + panel_w * 3, 8, h - 8)

    def _panel(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float, title: str) -> tuple[float, float, float, float]:
        c.create_rectangle(left, top, right, bottom, fill="#F4F8FC", outline="#D9E4EF")
        c.create_text(left + 8, top + 12, text=title, fill=COLOR_TEXT_DIM, font=("Helvetica Neue", 9, "bold"), anchor="w")
        return left + 10, right - 10, top + 26, bottom - 12

    def _paint_rssi_hist(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float) -> None:
        pl, pr, pt, pb = self._panel(c, left, right, top, bottom, "RSSI histogram")
        if len(self._rssi) < 1:
            c.create_text((left + right) / 2, (top + bottom) / 2 + 6, text="no RF yet", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 10))
            return
        bins = 10
        lo, hi = min(self._rssi), max(self._rssi)
        if abs(hi - lo) < 1e-9:
            lo, hi = lo - 1.0, hi + 1.0
        counts = [0] * bins
        for v in self._rssi:
            idx = min(bins - 1, max(0, int((v - lo) / (hi - lo) * bins)))
            counts[idx] += 1
        peak = max(counts) or 1
        bw = (pr - pl) / bins - 2
        for i, n in enumerate(counts):
            x0 = pl + i * ((pr - pl) / bins) + 1
            bh = max(2, (pb - pt) * (n / peak))
            c.create_rectangle(x0, pb - bh, x0 + bw, pb, fill=self._teal, outline="")
        c.create_text(pr, top + 12, text=f"{self._rssi[-1]:.1f}", fill=COLOR_TEXT, font=("Helvetica Neue", 10, "bold"), anchor="e")

    def _paint_scatter(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float) -> None:
        pl, pr, pt, pb = self._panel(c, left, right, top, bottom, "RSSI scatter")
        if len(self._rssi) < 1:
            c.create_text((left + right) / 2, (top + bottom) / 2 + 6, text="no RF yet", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 10))
            return
        lo, hi = min(self._rssi), max(self._rssi)
        if abs(hi - lo) < 1e-9:
            lo, hi = lo - 1.0, hi + 1.0
        n = len(self._rssi)
        # Median guide.
        ordered = sorted(self._rssi)
        med = ordered[len(ordered) // 2]
        med_y = pb - (pb - pt) * ((med - lo) / (hi - lo))
        c.create_line(pl, med_y, pr, med_y, fill="#CBD5E1", width=1, dash=(3, 2))
        for i, val in enumerate(self._rssi):
            x = pl + (pr - pl) * (i / max(1, n - 1))
            y = pb - (pb - pt) * ((val - lo) / (hi - lo))
            r = 2.5
            c.create_oval(x - r, y - r, x + r, y + r, fill=COLOR_BLUE, outline="")
        c.create_text(pr, top + 12, text=f"med {med:.1f}", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 8), anchor="e")

    def _paint_unique(self, c: tk.Canvas, left: float, right: float, top: float, bottom: float) -> None:
        pl, pr, pt, pb = self._panel(c, left, right, top, bottom, "Unique IDs growth")
        if len(self._unique_counts) < 1:
            c.create_text((left + right) / 2, (top + bottom) / 2 + 6, text="no IDs yet", fill=COLOR_TEXT_MUTED, font=("Helvetica Neue", 10))
            return
        hi = max(self._unique_counts) or 1
        pts: list[float] = []
        for i, val in enumerate(self._unique_counts):
            x = pl + (pr - pl) * (i / max(1, len(self._unique_counts) - 1))
            y = pb - (pb - pt) * (val / hi)
            pts.extend([x, y])
        area = [pl, pb] + pts + [pr, pb]
        c.create_polygon(*area, fill="#DBEAFE", outline="")
        if len(pts) >= 4:
            c.create_line(*pts, fill=COLOR_BLUE, width=2)
        c.create_text(pr, top + 12, text=str(self._unique_counts[-1]), fill=COLOR_TEXT, font=("Helvetica Neue", 10, "bold"), anchor="e")


class TelemetryCharts(_ThrottledPaint, ctk.CTkFrame):
    """Live line graphs: three configurable series (default pressure / RSSI / temp)."""

    def __init__(
        self,
        master,
        *,
        height: int = 140,
        title: str = "Live telemetry graphs",
        series_titles: tuple[str, str, str] = ("Pressure (PSI)", "RSSI (dB)", "Temp (°C)"),
        **kwargs,
    ):
        kwargs.setdefault("fg_color", COLOR_BG_CARD)
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._a: list[float] = []
        self._b: list[float] = []
        self._c: list[float] = []
        self._titles = series_titles
        self._ok = 0
        self._nok = 0
        self._maxlen = 48

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=ui_font(12, "bold"), text_color=COLOR_TEXT).pack(side="left")
        self.caption = ctk.CTkLabel(head, text="Waiting for samples…", font=ui_font(11), text_color=COLOR_TEXT_MUTED)
        self.caption.pack(side="right")

        host = tk.Frame(self, bg=COLOR_BG_CARD, height=height)
        host.pack(fill="x", padx=8, pady=8)
        host.pack_propagate(False)
        self.canvas = tk.Canvas(host, bg=COLOR_BG_CARD, highlightthickness=0, height=height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._paint())

    def push(
        self,
        *,
        psi: float | None = None,
        rssi: float | None = None,
        temp: float | None = None,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        result: str | None = None,
    ) -> None:
        # Prefer explicit a/b/c; fall back to psi/rssi/temp aliases.
        va = a if a is not None else psi
        vb = b if b is not None else rssi
        vc = c if c is not None else temp
        for bucket, val in ((self._a, va), (self._b, vb), (self._c, vc)):
            if val is None:
                continue
            try:
                bucket.append(float(val))
            except (TypeError, ValueError):
                pass
        tag = str(result or "").strip().upper()
        if tag == "OK":
            self._ok += 1
        elif tag == "NOK":
            self._nok += 1
        self._a = self._a[-self._maxlen :]
        self._b = self._b[-self._maxlen :]
        self._c = self._c[-self._maxlen :]
        parts = []
        if self._a:
            parts.append(f"{self._titles[0].split('(')[0].strip()} {self._a[-1]:.1f}")
        if self._b:
            parts.append(f"{self._titles[1].split('(')[0].strip()} {self._b[-1]:.1f}")
        if self._c:
            parts.append(f"{self._titles[2].split('(')[0].strip()} {self._c[-1]:.1f}")
        if self._ok or self._nok:
            parts.append(f"OK {self._ok} / NOK {self._nok}")
        self.caption.configure(text="   ·   ".join(parts) if parts else "Waiting for samples…")
        self._request_paint()

    def set_counts(self, ok: int, nok: int) -> None:
        self._ok = max(0, int(ok))
        self._nok = max(0, int(nok))
        self._request_paint()

    def reset(self) -> None:
        self._a.clear()
        self._b.clear()
        self._c.clear()
        self._ok = 0
        self._nok = 0
        self.caption.configure(text="Waiting for samples…")
        self._request_paint()

    def _paint(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(int(c.winfo_width() or 0), 360)
        h = max(int(c.winfo_height() or 0), 100)
        gap = 10
        panel_w = (w - gap * 4) / 3
        teal = "#0D9488"
        panels = (
            (self._titles[0], self._a, COLOR_BLUE, 0),
            (self._titles[1], self._b, teal, 1),
            (self._titles[2], self._c, COLOR_GREEN, 2),
        )
        for title, series, color, idx in panels:
            left = gap + idx * (panel_w + gap)
            right = left + panel_w
            self._spark(c, left, right, 8, h - 8, title, series, color)

    def _spark(
        self,
        c: tk.Canvas,
        left: float,
        right: float,
        top: float,
        bottom: float,
        title: str,
        series: list[float],
        color: str,
    ) -> None:
        c.create_rectangle(left, top, right, bottom, fill="#F7FBFA", outline="#E2EEEC")
        c.create_text(left + 8, top + 12, text=title, fill=COLOR_TEXT_DIM, font=("Helvetica Neue", 9, "bold"), anchor="w")
        plot_top, plot_bot = top + 24, bottom - 10
        plot_left, plot_right = left + 8, right - 8
        if len(series) < 2:
            c.create_text(
                (left + right) / 2,
                (plot_top + plot_bot) / 2,
                text="no data",
                fill=COLOR_TEXT_MUTED,
                font=("Helvetica Neue", 10),
            )
            return
        lo = min(series)
        hi = max(series)
        span = hi - lo
        # Pad Y so nearly-flat series (e.g. 12 cm stuck) still draw mid-panel, not a bottom hairline.
        if abs(span) < 1e-9:
            pad = max(0.05, abs(lo) * 0.05 + 0.05)
            lo, hi = lo - pad, hi + pad
        else:
            pad = span * 0.18
            lo, hi = lo - pad, hi + pad
        n = len(series)
        # Grid mid-line.
        mid_y = (plot_top + plot_bot) / 2
        c.create_line(plot_left, mid_y, plot_right, mid_y, fill="#E2EEEC", width=1)
        pts: list[float] = []
        for i, val in enumerate(series):
            x = plot_left + (plot_right - plot_left) * (i / max(1, n - 1))
            y = plot_bot - (plot_bot - plot_top) * ((val - lo) / (hi - lo))
            pts.extend([x, y])
        c.create_line(*pts, fill=color, width=2, smooth=True)
        c.create_oval(pts[-2] - 3, pts[-1] - 3, pts[-2] + 3, pts[-1] + 3, fill=color, outline="")
        c.create_text(
            right - 8,
            top + 12,
            text=f"{series[-1]:.1f}",
            fill=COLOR_TEXT,
            font=("Helvetica Neue", 10, "bold"),
            anchor="e",
        )
