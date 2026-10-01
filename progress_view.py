"""Process Progress tab — live Board + SDR pipelines with per-step detail cards."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, Iterable, Optional

import customtkinter as ctk

from themes import (
    COLOR_BG,
    COLOR_BG_CARD,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_GREEN,
    COLOR_GREEN_BG,
    COLOR_HEADER_ACCENT,
    COLOR_ORANGE,
    COLOR_ORANGE_BG,
    COLOR_RED,
    COLOR_RED_BG,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_TEXT_MUTED,
)

_LOG_MAX = 48


_STEP_STYLE = {
    "idle": {
        "fg": COLOR_BG_PANEL,
        "border": COLOR_BORDER,
        "title": COLOR_TEXT_MUTED,
        "body": COLOR_TEXT_MUTED,
    },
    "active": {
        "fg": COLOR_ORANGE_BG,
        "border": COLOR_ORANGE,
        "title": COLOR_ORANGE,
        "body": COLOR_TEXT,
    },
    "done": {
        "fg": COLOR_GREEN_BG,
        "border": COLOR_GREEN,
        "title": COLOR_GREEN,
        "body": COLOR_TEXT_DIM,
    },
    "error": {
        "fg": COLOR_RED_BG,
        "border": COLOR_RED,
        "title": COLOR_RED,
        "body": COLOR_TEXT,
    },
}


BOARD_STEPS: tuple[tuple[str, str], ...] = (
    ("connect", "Connect"),
    ("row", "Load Row"),
    ("program", "Program"),
    ("trigger", "Trigger"),
    ("query", "Query"),
    ("result", "Result"),
)

SDR_STEPS: tuple[tuple[str, str], ...] = (
    ("open", "Open Dongle"),
    ("listen", "Listening"),
    ("decode", "Decode"),
    ("match", "Match"),
    ("result", "Result"),
)


def _clean(*parts: object, sep: str = " · ") -> str:
    out = []
    for part in parts:
        text = str(part or "").strip()
        if text and text.lower() not in {"na", "n/a", "none", "-", "—", ""}:
            out.append(text)
    return sep.join(out) if out else ""


def _fmt_codes(a: str = "", b: str = "", c: str = "") -> str:
    a, b, c = (str(a or "").strip(), str(b or "").strip(), str(c or "").strip())
    if not (a or b or c):
        return ""
    return f"A {a or '—'}  B {b or '—'}  C {c or '—'}"


def _story(info: Dict[str, str], fallback: str = "") -> str:
    """Build a lasting per-step story: input → output, tool, how."""
    lines: list[str] = []
    source = _clean(info.get("input"), info.get("codes"))
    decoded = _clean(info.get("decoded"), info.get("sensor_id") and f"ID {info.get('sensor_id')}")
    if source and decoded:
        lines.append(f"{source}")
        lines.append(f"→  {decoded}")
    elif decoded:
        lines.append(f"→  {decoded}")
    elif source:
        lines.append(source)
    values = info.get("values") or ""
    if values:
        lines.append(values)
    tool = info.get("tool") or ""
    path = info.get("path") or ""
    if tool:
        lines.append(f"Tool: {tool}")
    if path and path != tool:
        lines.append(f"How: {path}")
    vehicle = info.get("vehicle") or ""
    if vehicle:
        lines.append(vehicle)
    note = info.get("note") or ""
    if note and note not in lines:
        lines.append(note)
    if lines:
        return "\n".join(lines)
    return fallback or "Waiting…"


def _log_line_from_info(status: str, summary: str, info: Optional[Dict[str, str]]) -> str:
    """One compact log line for the step activity feed."""
    info = info or {}
    bits = [
        status.upper(),
        summary,
        _clean(info.get("decoded"), info.get("sensor_id") and f"ID {info.get('sensor_id')}"),
        info.get("values") or "",
        info.get("note") or "",
    ]
    return _clean(*bits, sep=" · ") or status.upper()


@dataclass
class _StepState:
    key: str
    label: str
    status: str = "idle"
    summary: str = ""
    info: Dict[str, str] = field(default_factory=dict)
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=_LOG_MAX))


class ProcessStepCard(ctk.CTkFrame):
    """One step with lasting detail + expandable activity log."""

    def __init__(self, master, label: str, **kwargs) -> None:
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 2)
        kwargs.setdefault("fg_color", COLOR_BG_PANEL)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._status = "idle"
        self._logs_open = False
        self._log_lines: list[str] = []

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 2))
        self.title = ctk.CTkLabel(
            head,
            text=label,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.title.pack(side="left")
        self.badge = ctk.CTkLabel(
            head,
            text="WAITING",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
            anchor="e",
        )
        self.badge.pack(side="right")

        self.body = ctk.CTkLabel(
            self,
            text="Waiting…",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="nw",
            justify="left",
            wraplength=220,
        )
        self.body.pack(fill="x", expand=False, padx=10, pady=(2, 2))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=8, pady=(0, 4))
        self.log_btn = ctk.CTkButton(
            foot,
            text="Logs ▾  (0)",
            width=100,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT_MUTED,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=6,
            command=self._toggle_logs,
        )
        self.log_btn.pack(side="left")

        self.log_box = ctk.CTkTextbox(
            self,
            height=92,
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color=COLOR_BG,
            text_color=COLOR_TEXT_DIM,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=6,
            activate_scrollbars=True,
            wrap="word",
        )
        # Collapsed by default — open Logs to see step activity.

    def _toggle_logs(self) -> None:
        self._logs_open = not self._logs_open
        if self._logs_open:
            self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self._refresh_log_view()
            self.log_btn.configure(text=f"Logs ▴  ({len(self._log_lines)})")
        else:
            self.log_box.pack_forget()
            self.log_btn.configure(text=f"Logs ▾  ({len(self._log_lines)})")

    def _refresh_log_view(self) -> None:
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            if self._log_lines:
                self.log_box.insert("1.0", "\n".join(self._log_lines))
                self.log_box.see("end")
            else:
                self.log_box.insert("1.0", "No activity yet for this step.")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def clear_logs(self) -> None:
        self._log_lines.clear()
        if self._logs_open:
            self.log_box.pack_forget()
            self._logs_open = False
        self.log_btn.configure(text="Logs ▾  (0)")
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def append_log(self, line: str) -> None:
        text = str(line or "").strip()
        if not text:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"{stamp}  {text}"
        if self._log_lines and self._log_lines[-1][10:].strip() == text:
            return
        self._log_lines.append(entry)
        if len(self._log_lines) > _LOG_MAX:
            self._log_lines = self._log_lines[-_LOG_MAX:]
        self.log_btn.configure(
            text=f"Logs {'▴' if self._logs_open else '▾'}  ({len(self._log_lines)})"
        )
        if self._logs_open:
            self._refresh_log_view()

    def set_state(self, status: str, story: str = "", *, log_line: str = "") -> None:
        style = _STEP_STYLE.get(status, _STEP_STYLE["idle"])
        self._status = status
        self.configure(fg_color=style["fg"], border_color=style["border"])
        self.title.configure(text_color=style["title"])
        badge = {"idle": "WAITING", "active": "IN PROGRESS", "done": "DONE", "error": "FAILED"}.get(
            status, status.upper()
        )
        self.badge.configure(text=badge, text_color=style["title"])
        self.body.configure(
            text=story or {"idle": "Waiting…", "active": "Working…", "done": "Done", "error": "Failed"}.get(
                status, "—"
            ),
            text_color=style["body"],
        )
        if log_line:
            self.append_log(log_line)

    def pulse(self, bright: bool) -> None:
        if self._status != "active":
            return
        if bright:
            self.configure(border_color=COLOR_HEADER_ACCENT, fg_color="#FFF4E8")
        else:
            self.configure(border_color=COLOR_ORANGE, fg_color=COLOR_ORANGE_BG)


class ProcessPipeline(ctk.CTkFrame):
    """Row of independent step cards — each keeps lasting detail + activity logs."""

    def __init__(
        self,
        master,
        *,
        title: str,
        steps: Iterable[tuple[str, str]],
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", COLOR_BG_CARD)
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLOR_BORDER)
        super().__init__(master, **kwargs)
        self._steps: list[_StepState] = [_StepState(k, label) for k, label in steps]
        self._cards: dict[str, ProcessStepCard] = {}
        self._active_key: Optional[str] = None

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            head,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")
        self.headline = ctk.CTkLabel(
            head,
            text="Idle",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT_DIM,
        )
        self.headline.pack(side="right")

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        count = len(self._steps)
        for col in range(count):
            grid.grid_columnconfigure(col, weight=1, uniform="steps")
        grid.grid_rowconfigure(0, weight=1)

        for col, step in enumerate(self._steps):
            card = ProcessStepCard(grid, step.label)
            card.grid(row=0, column=col, sticky="nsew", padx=4, pady=2)
            self._cards[step.key] = card
            card.set_state("idle")

    def reset(self) -> None:
        self._active_key = None
        for step in self._steps:
            step.status = "idle"
            step.summary = ""
            step.info = {}
            step.logs.clear()
            card = self._cards[step.key]
            card.clear_logs()
            card.set_state("idle")
        self.headline.configure(text="Idle", text_color=COLOR_TEXT_DIM)

    def _paint(self, step: _StepState, *, log: bool = True) -> None:
        story = _story(step.info, step.summary)
        log_line = ""
        if log:
            log_line = _log_line_from_info(step.status, step.summary, step.info)
            if log_line:
                step.logs.append(log_line)
        self._cards[step.key].set_state(step.status, story, log_line=log_line)

    def set_active(
        self,
        key: str,
        *,
        summary: str = "",
        info: Optional[Dict[str, str]] = None,
        headline: str = "",
    ) -> None:
        found = False
        for step in self._steps:
            if step.key == key:
                step.status = "active"
                if summary:
                    step.summary = summary
                if info:
                    step.info.update({k: v for k, v in info.items() if v})
                self._paint(step, log=True)
                found = True
                self._active_key = key
            elif not found:
                # Prior steps stay done and keep their last story — except Decode,
                # which must not fake "Done" before LF trigger / a real RF packet.
                if step.key == "decode" and step.status in {"idle", "active"}:
                    if step.status == "idle":
                        step.status = "active"
                        if not step.summary:
                            step.summary = "Waiting for LF-triggered RF…"
                        if not step.info:
                            step.info = {
                                "input": "LF trigger first",
                                "decoded": "Decode starts after Board Trigger",
                                "note": "Dongle may already be listening",
                            }
                        self._paint(step, log=True)
                    continue
                if step.status == "idle":
                    step.status = "done"
                    if not step.info and not step.summary:
                        step.summary = "Done"
                    self._paint(step, log=False)
                elif step.status == "active":
                    step.status = "done"
                    self._paint(step, log=False)
            # Later steps keep whatever they last showed (don't wipe history).
        label = next((s.label for s in self._steps if s.key == key), key)
        self.headline.configure(text=headline or f"{label}…", text_color=COLOR_ORANGE)

    def mark_done(self, key: str, *, summary: str = "", info: Optional[Dict[str, str]] = None) -> None:
        for step in self._steps:
            if step.key == key:
                step.status = "done"
                if summary:
                    step.summary = summary
                if info:
                    step.info.update({k: v for k, v in info.items() if v})
                self._paint(step, log=True)
                break
        if self._active_key == key:
            self._active_key = None
            self.headline.configure(text="Done", text_color=COLOR_GREEN)

    def mark_error(self, key: str, *, summary: str = "failed", info: Optional[Dict[str, str]] = None) -> None:
        for step in self._steps:
            if step.key == key:
                step.status = "error"
                step.summary = summary
                if info:
                    step.info.update({k: v for k, v in info.items() if v})
                self._paint(step, log=True)
                break
        self._active_key = key
        self.headline.configure(text="Failed", text_color=COLOR_RED)

    def finish_success(self, *, summary: str = "Complete") -> None:
        for step in self._steps:
            if step.status == "active":
                step.status = "done"
                self._paint(step, log=True)
            elif step.status == "idle":
                pass
        self._active_key = None
        self.headline.configure(text=summary, text_color=COLOR_GREEN)

    def finish_stopped(self, *, summary: str = "Stopped") -> None:
        for step in self._steps:
            if step.status == "active" or step.key == "listen":
                step.status = "done"
                if step.key == "listen":
                    step.summary = summary or "Listening stopped"
                    step.info = {
                        "input": "Board session settled",
                        "decoded": summary or "SDR listening stopped",
                        "note": "Dongle idle until next Start",
                    }
                self._paint(step, log=True)
        self._active_key = None
        self.headline.configure(text=summary or "Stopped", text_color=COLOR_TEXT_DIM)

    def pulse(self, bright: bool) -> None:
        if self._active_key and self._active_key in self._cards:
            self._cards[self._active_key].pulse(bright)

    def append_step_log(self, key: str, line: str) -> None:
        """Extra activity line on a step without changing its badge."""
        card = self._cards.get(key)
        if not card:
            return
        text = str(line or "").strip()
        if not text:
            return
        for step in self._steps:
            if step.key == key:
                step.logs.append(text)
                break
        card.append_log(text)


class ProgressView(ctk.CTkFrame):
    """Dedicated tab — each Board/SDR step keeps its own lasting detail card."""

    def __init__(self, master, **kwargs) -> None:
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._pulse = 0
        self._board_ctx: Dict[str, str] = {}
        self._sdr_ctx: Dict[str, str] = {}
        # UI-only: Decode must not show done until Board LF Trigger for this row.
        self._decode_armed = False
        self._decode_seen_after_trigger = False
        self._build()
        self.after(420, self._tick_pulse)

    def _build(self) -> None:
        head = ctk.CTkFrame(
            self, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER
        )
        head.pack(fill="x", pady=(0, 10))
        inner = ctk.CTkFrame(head, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(
            inner,
            text="Process Progress",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            inner,
            text="Each step keeps what it did  ·  open Logs on a card for activity detail",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
        ).pack(side="left", padx=14)
        self.now_label = ctk.CTkLabel(
            inner, text="", font=ctk.CTkFont(size=11), text_color=COLOR_HEADER_ACCENT
        )
        self.now_label.pack(side="right")
        ctk.CTkButton(
            inner,
            text="Clear all",
            width=88,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_BG_PANEL,
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            border_width=1,
            border_color=COLOR_BORDER,
            command=self._confirm_clear_all,
        ).pack(side="right", padx=(0, 10))

        self.board = ProcessPipeline(self, title="TPMS Board", steps=BOARD_STEPS)
        self.board.pack(fill="both", expand=True, pady=(0, 10))

        self.sdr = ProcessPipeline(self, title="SDR Receiver", steps=SDR_STEPS)
        self.sdr.pack(fill="both", expand=True)

        self.board.reset()
        self.sdr.reset()

    def _confirm_clear_all(self) -> None:
        """Ask before wiping every Progress step story + log."""
        from tkinter import messagebox

        ok = messagebox.askyesno(
            "Clear Progress",
            "Clear all Progress data?\n\n"
            "This resets every Board and SDR step card and deletes their Logs.\n"
            "It does not stop a running Board/SDR test or erase Excel/results.",
            parent=self.winfo_toplevel(),
        )
        if ok:
            self.clear_all()

    def clear_all(self) -> None:
        """Wipe Progress UI state (steps, stories, logs, context)."""
        self.board.reset()
        self.sdr.reset()
        self._board_ctx.clear()
        self._sdr_ctx.clear()
        self._decode_armed = False
        self._decode_seen_after_trigger = False
        self.now_label.configure(text="Progress cleared")

    def reset(self) -> None:
        """Alias used by older callers — same as Clear all without prompt."""
        self.clear_all()

    def _disarm_decode_for_new_row(self) -> None:
        """New Board row: keep Open/Listen, park Decode until LF Trigger."""
        self._decode_armed = False
        self._decode_seen_after_trigger = False
        for key in ("decode", "match", "result"):
            for step in self.sdr._steps:
                if step.key != key:
                    continue
                step.status = "idle"
                step.summary = ""
                step.info = {}
                if key == "decode":
                    step.info = {
                        "input": "LF trigger first",
                        "decoded": "Idle until Board Trigger",
                        "note": "SDR may already be listening — that is OK",
                    }
                    step.summary = "Waiting for LF trigger…"
                card = self.sdr._cards.get(key)
                if card:
                    card.append_log("— new Board row —")
                self.sdr._paint(step, log=False)
                if key == "decode" and card:
                    card.append_log("WAITING · Decode parked until LF Trigger")
                break
        if self.sdr._active_key in {"decode", "match", "result"}:
            # Prefer showing listen as the live SDR stage before trigger.
            listen = next((s for s in self.sdr._steps if s.key == "listen"), None)
            if listen and listen.status in {"done", "active"}:
                self.sdr._active_key = "listen"
                self.sdr.headline.configure(text="Listening", text_color=COLOR_ORANGE)
            else:
                self.sdr._active_key = None

    def _arm_decode_after_trigger(self, *, message: str = "") -> None:
        """Board LF Trigger fired — Decode may now reflect real RF for this row."""
        self._decode_armed = True
        if self._decode_seen_after_trigger:
            return
        self.sdr.set_active(
            "decode",
            summary=message or "Waiting for triggered RF…",
            info={
                "input": "LF-triggered sensor burst",
                "decoded": "Listening for rtl_433 after Trigger",
                "tool": "rtl_433 + RTL-SDR",
                "path": "LF → sensor TX → antenna → rtl_433",
                "note": message or "Decode armed — waiting for this row’s RF packet",
            },
            headline="Decode",
        )

    def _tick_pulse(self) -> None:
        self._pulse = (self._pulse + 1) % 2
        bright = bool(self._pulse)
        try:
            self.board.pulse(bright)
            self.sdr.pulse(bright)
        except Exception:
            pass
        self.after(420, self._tick_pulse)

    def _remember_board(self, **kwargs) -> None:
        for key, value in kwargs.items():
            text = str(value or "").strip()
            if text and text.lower() not in {"na", "n/a", "none"}:
                self._board_ctx[key] = text

    def _remember_sdr(self, **kwargs) -> None:
        for key, value in kwargs.items():
            text = str(value or "").strip()
            if text and text.lower() not in {"na", "n/a", "none"}:
                self._sdr_ctx[key] = text

    def _now(self, source: str, message: str) -> None:
        self.now_label.configure(text=f"{source} · {message[:72]}")

    @staticmethod
    def _format_board_version(extras: dict, message: str = "") -> str:
        """Format Chapter 4.0 versions — firmware (TPMS software) first."""
        if not extras:
            return (message or "Firmware — no reply").strip()

        def _one(key: str):
            raw = extras.get(key)
            if raw in (None, ""):
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return raw

        fw = _one("firmware_version")
        if fw is None:
            fw = _one("software_version")
        parts = [f"Firmware {fw}" if fw is not None else "Firmware —"]
        for key, short in (
            ("hardware_version", "HW"),
            ("boot_version", "Boot"),
            ("trigger_database_version", "Trigger"),
            ("programming_database_version", "Prog DB"),
        ):
            val = _one(key)
            if val is not None:
                parts.append(f"{short} {val}")
        return " · ".join(parts)

    # ── Board API ──────────────────────────────────────────────
    def board_event(self, kind: str, *, path: str = "", message: str = "", **extra) -> None:
        kind = (kind or "").lower()
        path = (path or "").lower()
        msg = (message or "").strip()
        self._remember_board(
            code_a=extra.get("code_a"),
            code_b=extra.get("code_b"),
            code_c=extra.get("code_c"),
            sensor_id=extra.get("sensor_id"),
            make=extra.get("make"),
            model=extra.get("model"),
            transport=extra.get("transport"),
            tool_path=extra.get("tool_path") or extra.get("path"),
            performance=extra.get("performance"),
            temperature=extra.get("temperature"),
            pressure=extra.get("pressure"),
            voltage=extra.get("voltage"),
            excel_row=extra.get("excel_row"),
            freq=extra.get("freq"),
        )
        codes = _fmt_codes(
            extra.get("code_a") or self._board_ctx.get("code_a"),
            extra.get("code_b") or self._board_ctx.get("code_b"),
            extra.get("code_c") or self._board_ctx.get("code_c"),
        )
        vehicle = _clean(
            f"Row {extra.get('excel_row')}" if extra.get("excel_row") else "",
            f"{extra.get('make') or self._board_ctx.get('make', '')} "
            f"{extra.get('model') or self._board_ctx.get('model', '')}".strip(),
        )
        tool = _clean(
            extra.get("transport") or self._board_ctx.get("transport"),
            extra.get("tool_path") or extra.get("path") or self._board_ctx.get("tool_path"),
        )
        sid = str(extra.get("sensor_id") or self._board_ctx.get("sensor_id") or "").strip()

        if kind == "comm":
            how = msg or path or "USB-TTL / J-Link"
            self.board.set_active(
                "connect",
                summary=how,
                info={
                    "input": "Board USB link",
                    "decoded": how,
                    "tool": "Hamaton Board (USB-TTL / J-Link)",
                    "path": how,
                    "note": "Checking board connection",
                },
                headline="Connect",
            )
            self._now("Board", how)
            return

        if kind == "board_version":
            extras = dict(extra.get("extras") or {})
            version_line = self._format_board_version(extras, msg)
            self.board.set_active(
                "connect",
                summary=version_line,
                info={
                    "input": "Query Version (0x40)",
                    "decoded": version_line,
                    "tool": "Hamaton Query Version",
                    "path": tool or "USB-TTL / J-Link",
                    "note": "Chapter 4.0 — HW / Boot / SW / Trigger / Prog DB",
                },
                headline="Connect",
            )
            self.board.mark_done(
                "connect",
                summary=version_line,
                info={
                    "input": "Query Version (0x40)",
                    "decoded": version_line,
                    "tool": "Hamaton Query Version",
                    "path": tool or "USB-TTL / J-Link",
                    "note": "Board firmware versions reported",
                },
            )
            self._now("Board", version_line)
            return

        if kind == "started":
            extras = dict(extra.get("extras") or {})
            version_note = self._format_board_version(extras, "") if extras else ""
            summary = msg or "Session started"
            if version_note and "Firmware" in version_note:
                summary = f"{summary} · {version_note}" if msg else version_note
            self.board.set_active(
                "connect",
                summary=summary,
                info={
                    "input": "Start Board session",
                    "decoded": version_note or tool or "Board link ready",
                    "tool": "Hamaton Board session",
                    "path": tool or msg,
                    "note": version_note or "Board link ready",
                },
                headline="Connect",
            )
            self.board.mark_done(
                "connect",
                summary=version_note or tool or "connected",
                info={
                    "input": "Start Board session",
                    "decoded": version_note or tool or "Connected",
                    "tool": "Hamaton Board",
                    "path": tool or msg,
                    "note": version_note or "Connected",
                },
            )
            self._now("Board", summary)
            return

        if kind == "phase":
            if path == "wait_sdr":
                self.sdr.set_active(
                    "match",
                    summary=msg or "Waiting for rtl_433…",
                    info={
                        "input": f"Board ID {sid}" if sid else "Board RF burst",
                        "decoded": "Waiting for rtl_433 library decode",
                        "tool": "rtl_433 (RTL-SDR)",
                        "path": "Compare Board OEID ↔ SDR packet",
                        "note": msg or "Listening for matching packet",
                    },
                    headline="Match",
                )
                self._now("SDR", msg or "Waiting for rtl_433")
                return
            if path == "program":
                self.board.set_active(
                    "program",
                    summary=codes or "Programming…",
                    info={
                        "input": codes or "CODE A / B / C",
                        "decoded": "Programming sensor OEID on board…",
                        "tool": "Hamaton Program Sensor",
                        "path": tool or "USB-TTL TX → board",
                        "vehicle": vehicle,
                        "note": msg or "Writing vehicle codes to sensor",
                    },
                    headline="Program",
                )
                self._now("Board", msg or f"Program {codes}")
                return
            if path == "trigger":
                self.board.set_active(
                    "trigger",
                    summary=msg or "LF trigger…",
                    info={
                        "input": codes or "Programmed sensor",
                        "decoded": "LF activate — waiting for RF response",
                        "tool": "Hamaton LF Trigger",
                        "path": tool or "LF → sensor → Board RX",
                        "vehicle": vehicle,
                        "note": msg or "Waiting for sensor RF response",
                    },
                    headline="Trigger",
                )
                # UI-only: arm SDR Decode now — not during early Listening.
                self._arm_decode_after_trigger(message=msg or "LF trigger fired")
                self._now("Board", msg or "Trigger")
                return
            if path == "query":
                self.board.set_active(
                    "query",
                    summary=msg or "Query…",
                    info={
                        "input": sid or "Triggered sensor",
                        "decoded": "Reading temp / pressure / battery from board",
                        "tool": "Hamaton Query Sensor",
                        "path": tool or "Query over Board link",
                        "vehicle": vehicle,
                        "note": msg or "Pulling telemetry",
                    },
                    headline="Query",
                )
                self._now("Board", msg or "Query")
                return
            key = path if path in {s[0] for s in BOARD_STEPS} else "program"
            self.board.set_active(
                key,
                summary=msg or key,
                info={"note": msg, "input": key, "decoded": msg or key},
                headline=key.title(),
            )
            self._now("Board", msg or path)
            return

        if kind == "row_start":
            self._disarm_decode_for_new_row()
            self.board.set_active(
                "row",
                summary=vehicle or msg,
                info={
                    "input": f"Excel / catalog row {extra.get('excel_row') or self._board_ctx.get('excel_row') or '—'}",
                    "decoded": codes or "CODE A / B / C for this vehicle",
                    "tool": "Excel catalog / manual codes",
                    "path": _clean(extra.get("freq") or self._board_ctx.get("freq"), "next: program"),
                    "vehicle": vehicle,
                    "note": msg or "Selected next vehicle codes",
                },
                headline="Load Row",
            )
            self._now("Board", msg or f"Row {extra.get('excel_row')} {vehicle}")
            return

        if kind == "board_ok":
            # Board ABC finished — if Trigger phase was missed in UI, arm Decode now.
            if not self._decode_armed:
                self._arm_decode_after_trigger(message="Board ABC done — arming Decode")
            values = _clean(
                f"T {extra.get('temperature')}" if extra.get("temperature") else "",
                f"P {extra.get('pressure')}" if extra.get("pressure") else "",
                f"Batt {extra.get('voltage')}" if extra.get("voltage") else "",
            )
            perf = str(extra.get("performance") or self._board_ctx.get("performance") or "OK").upper()
            # Lock in prior stages with final stories when we learn the ID.
            if codes:
                self.board.mark_done(
                    "program",
                    summary=codes,
                    info={
                        "input": codes,
                        "decoded": f"Programmed / returned ID {sid}" if sid else "Program complete",
                        "tool": "Hamaton Program Sensor",
                        "path": tool or "USB-TTL TX → board",
                        "vehicle": vehicle,
                    },
                )
            if sid or values:
                self.board.mark_done(
                    "trigger",
                    summary=sid or "triggered",
                    info={
                        "input": codes or "LF activate",
                        "decoded": f"Sensor answered · ID {sid}" if sid else "Sensor RF heard",
                        "tool": "Hamaton LF Trigger",
                        "path": tool or "LF → sensor → Board RX",
                        "values": values,
                    },
                )
                self.board.mark_done(
                    "query",
                    summary=values or sid or "read",
                    info={
                        "input": sid or "Sensor after trigger",
                        "decoded": values or "Telemetry read",
                        "tool": "Hamaton Query Sensor",
                        "path": tool or "Board query",
                        "sensor_id": sid,
                        "values": values,
                    },
                )
            info = {
                "input": codes or "Board ABC cycle",
                "decoded": f"{perf} · Sensor ID {sid}" if sid else perf,
                "tool": "Hamaton Board (program + trigger + query)",
                "path": tool or "Board RF path",
                "vehicle": vehicle,
                "sensor_id": sid,
                "values": values,
                "note": msg or "Board finished this row",
            }
            if perf == "NOK":
                self.board.mark_error("result", summary=f"NOK · {sid or 'fail'}", info=info)
                self.board._active_key = None
                self.board.headline.configure(
                    text=_clean("Board NOK", sid) or "Board NOK", text_color=COLOR_RED
                )
            else:
                self.board.mark_done("result", summary=f"{perf} · {sid}", info=info)
                self.board.finish_success(summary=_clean(perf, sid) or "Board OK")
            self._now("Board", msg or f"Board {perf} ID {sid}")
            return

        if kind == "row_done":
            values = _clean(
                f"T {extra.get('temperature')}" if extra.get("temperature") else "",
                f"P {extra.get('pressure')}" if extra.get("pressure") else "",
                f"Batt {extra.get('voltage')}" if extra.get("voltage") else "",
            )
            perf = str(extra.get("performance") or self._board_ctx.get("performance") or "").upper()
            info = {
                "input": codes or "Board ABC cycle",
                "decoded": f"{perf or 'DONE'} · ID {sid}" if sid else (perf or "Row complete"),
                "tool": "Hamaton Board",
                "vehicle": vehicle,
                "sensor_id": sid,
                "values": values,
                "note": msg or "Row complete",
            }
            if perf == "NOK":
                self.board.mark_error("result", summary=info["decoded"], info=info)
            else:
                self.board.mark_done("result", summary=info["decoded"], info=info)
                self.board.finish_success(summary=msg or "Row complete")
            self._now("Board", msg or f"Row done {perf} {sid}")
            return

        if kind in {"paused", "chunk_complete"}:
            self.board.headline.configure(text="Paused", text_color=COLOR_ORANGE)
            if self.board._active_key:
                self.board.mark_done(self.board._active_key, summary="Paused", info={"note": msg or "Paused"})
            self._now("Board", msg or "Paused")
            return
        if kind in {"stopping", "stopped"}:
            self.board.finish_stopped(summary=msg or "Stopped")
            self._now("Board", msg or "Stopped")
            return
        if kind == "finished":
            self.board.finish_success(summary=msg or "All rows finished")
            self._now("Board", msg or "Finished")
            return
        if kind == "error":
            key = self.board._active_key or "connect"
            self.board.mark_error(
                key,
                summary=msg or "Error",
                info={"input": "Board step", "decoded": msg or "Error", "note": msg},
            )
            self._now("Board", msg or "Error")
            return
        if kind == "resumed":
            self.board.set_active(
                "row",
                summary=msg or "Resumed",
                info={"input": "Resume", "decoded": "Continue next row", "tool": "Hamaton Board"},
                headline="Running",
            )
            self._now("Board", msg or "Resumed")

    # ── SDR API ────────────────────────────────────────────────
    def sdr_event(self, kind: str, *, message: str = "", **extra) -> None:
        kind = (kind or "").lower()
        msg = (message or "").strip()
        self._remember_sdr(
            decoder=extra.get("decoder"),
            sensor_id=extra.get("sensor_id"),
            board_id=extra.get("board_id"),
            rtl_id=extra.get("rtl_id"),
            pressure=extra.get("pressure"),
            temperature=extra.get("temperature"),
            battery=extra.get("battery"),
            rssi=extra.get("rssi"),
            freq=extra.get("freq"),
            tool=extra.get("tool"),
        )
        decoder = str(extra.get("decoder") or self._sdr_ctx.get("decoder") or "").strip()
        sid = str(extra.get("sensor_id") or extra.get("rtl_id") or self._sdr_ctx.get("sensor_id") or "").strip()
        board_id = str(extra.get("board_id") or self._sdr_ctx.get("board_id") or "").strip()
        values = _clean(
            f"PSI {extra.get('pressure')}" if extra.get("pressure") else "",
            f"T {extra.get('temperature')}" if extra.get("temperature") else "",
            f"Batt {extra.get('battery')}" if extra.get("battery") else "",
            f"RSSI {extra.get('rssi')}" if extra.get("rssi") else "",
        )
        tool = str(extra.get("tool") or self._sdr_ctx.get("tool") or "rtl_433 + RTL-SDR").strip()
        freq = str(extra.get("freq") or self._sdr_ctx.get("freq") or "").strip()

        if kind in {"idle", "stopped"}:
            if kind == "stopped":
                self.sdr.finish_stopped(summary=msg or "Stopped")
            else:
                self.sdr.reset()
            self._now("SDR", msg or kind)
            return

        if kind in {"starting", "open", "reconnecting"}:
            self.sdr.set_active(
                "open",
                summary=msg or "Opening…",
                info={
                    "input": "USB RTL-SDR dongle",
                    "decoded": "rtl_433 process starting",
                    "tool": tool,
                    "path": "libusb → rtl_433 JSON",
                    "note": msg or "Starting decoder on dongle",
                },
                headline="Open Dongle",
            )
            self._now("SDR", msg or "Opening dongle")
            return

        if kind in {"listening", "running"}:
            self.sdr.mark_done(
                "open",
                summary="Dongle open",
                info={
                    "input": "USB RTL-SDR dongle",
                    "decoded": "rtl_433 running",
                    "tool": tool,
                    "path": freq or "libusb → rtl_433",
                },
            )
            self.sdr.set_active(
                "listen",
                summary=msg or "Listening…",
                info={
                    "input": freq or "TPMS RF band",
                    "decoded": "Waiting for sensor packets",
                    "tool": tool,
                    "path": "Antenna → RTL-SDR → rtl_433",
                    "note": msg or "Listening for RF burst",
                },
                headline="Listening",
            )
            self._now("SDR", msg or "Listening")
            return

        if kind == "paused":
            self.sdr.set_active(
                "listen",
                summary=msg or "Paused",
                info={
                    "input": freq or "TPMS RF band",
                    "decoded": "Paused — not listening",
                    "tool": tool,
                    "note": msg,
                },
                headline="Paused",
            )
            self.sdr.headline.configure(text="Paused", text_color=COLOR_ORANGE)
            self._now("SDR", msg or "Paused")
            return

        if kind == "decode":
            # UI-only gate: ignore ambient / pre-trigger rtl_433 IDs on Progress.
            if not self._decode_armed:
                self._now("SDR", "Decode held until LF Trigger")
                return
            self._decode_seen_after_trigger = True
            self.sdr.set_active(
                "decode",
                summary=_clean(decoder, sid) or msg,
                info={
                    "input": "LF-triggered RF / Manchester bits",
                    "decoded": _clean(decoder, f"ID {sid}" if sid else "") or "Decoded packet",
                    "tool": tool,
                    "path": "rtl_433 after Board Trigger",
                    "sensor_id": sid,
                    "values": values,
                    "note": msg or "Packet decoded by rtl_433",
                },
                headline="Decode",
            )
            # Persist done story immediately so the card keeps "decoded X into Y".
            self.sdr.mark_done(
                "decode",
                summary=_clean(decoder, sid),
                info={
                    "input": "LF-triggered RF / Manchester bits",
                    "decoded": _clean(decoder, f"ID {sid}" if sid else "") or "Decoded packet",
                    "tool": tool,
                    "path": "rtl_433 after Board Trigger",
                    "sensor_id": sid,
                    "values": values,
                },
            )
            self._now("SDR", msg or f"Decode {decoder} {sid}")
            return

        if kind in {"match", "waiting"}:
            if not self._decode_armed:
                self._arm_decode_after_trigger(message="Match window — arming Decode")
            # If no post-trigger decode event yet, keep Decode as IN PROGRESS (not fake Done).
            if not self._decode_seen_after_trigger:
                dec_step = next((s for s in self.sdr._steps if s.key == "decode"), None)
                if dec_step and dec_step.status != "done":
                    self.sdr.set_active(
                        "decode",
                        summary="Waiting for triggered RF…",
                        info={
                            "input": "LF-triggered sensor burst",
                            "decoded": "No post-trigger rtl_433 ID yet",
                            "tool": tool,
                            "path": "LF → sensor TX → rtl_433",
                            "note": "Match is waiting on Decode",
                        },
                        headline="Decode",
                    )
            self.sdr.set_active(
                "match",
                summary=msg or "Matching…",
                info={
                    "input": f"Board ID {board_id}" if board_id else "Board trigger burst",
                    "decoded": _clean(decoder, f"SDR ID {sid}" if sid else "waiting library decode")
                    or "Aligning IDs",
                    "tool": tool,
                    "path": "Board OEID ↔ rtl_433 ID (bit-shift family allowed)",
                    "sensor_id": sid or board_id,
                    "note": msg or "Matching Board row to SDR packet",
                },
                headline="Match",
            )
            self._now("SDR", msg or "Match")
            return

        if kind == "result_ok":
            self._decode_armed = True
            self._decode_seen_after_trigger = True
            info = {
                "input": f"Board {board_id}" if board_id else "Board row + RF burst",
                "decoded": _clean(decoder, f"ID {sid}", "OK") or "OK",
                "tool": tool,
                "path": "rtl_433 library / OE flex OK",
                "sensor_id": sid,
                "values": values,
                "note": msg or "SDR match OK",
            }
            if decoder or sid:
                self.sdr.mark_done(
                    "decode",
                    summary=_clean(decoder, sid),
                    info={
                        "input": "LF-triggered RF / Manchester bits",
                        "decoded": _clean(decoder, f"ID {sid}"),
                        "tool": tool,
                        "path": "rtl_433 after Board Trigger",
                        "values": values,
                    },
                )
            self.sdr.mark_done(
                "match",
                summary=_clean(f"Board {board_id}", f"SDR {sid}"),
                info={
                    "input": f"Board ID {board_id}" if board_id else "Board row",
                    "decoded": f"Matched SDR ID {sid}" if sid else "Matched",
                    "tool": tool,
                    "path": "Board OEID ↔ rtl_433 ID",
                },
            )
            self.sdr.mark_done("result", summary=_clean("OK", sid, decoder), info=info)
            # Settle the pipeline — do not leave Listening as IN PROGRESS after a result.
            self.sdr.mark_done(
                "listen",
                summary="Ready for next row",
                info={
                    "input": freq or "TPMS RF band",
                    "decoded": "Row settled — waiting for next Board trigger",
                    "tool": tool,
                    "path": "Antenna → RTL-SDR → rtl_433",
                },
            )
            self.sdr.finish_success(summary=_clean("OK", sid, decoder) or "SDR OK")
            self._now("SDR", msg or f"OK {decoder} {sid}")
            return

        if kind == "result_nok":
            self._decode_armed = True
            info = {
                "input": f"Board {board_id}" if board_id else "Board row",
                "decoded": decoder or "No library decode",
                "tool": tool,
                "path": "rtl_433 miss / timeout",
                "sensor_id": sid or board_id,
                "note": msg or "SDR failed to decode",
            }
            if not self._decode_seen_after_trigger:
                self.sdr.mark_done(
                    "decode",
                    summary="No post-trigger decode",
                    info={
                        "input": "LF-triggered RF expected",
                        "decoded": decoder or "No rtl_433 ID after Trigger",
                        "tool": tool,
                        "note": "Decode window closed without a packet",
                    },
                )
            self.sdr.mark_done(
                "match",
                summary=_clean(f"Board {board_id}", "no SDR match"),
                info={
                    "input": f"Board ID {board_id}" if board_id else "Board row",
                    "decoded": "No matching rtl_433 / OE RF ID",
                    "tool": tool,
                },
            )
            self.sdr.mark_error("result", summary="NOK", info=info)
            self.sdr.mark_done(
                "listen",
                summary="Ready for next row",
                info={
                    "input": freq or "TPMS RF band",
                    "decoded": "Row settled after NOK — waiting for next Board trigger",
                    "tool": tool,
                },
            )
            # Clear active so nothing pulses IN PROGRESS after the row result.
            self.sdr._active_key = None
            self.sdr.headline.configure(text=_clean("NOK", sid) or "SDR NOK", text_color=COLOR_RED)
            self._now("SDR", msg or "NOK")
            return

        if kind == "error":
            key = self.sdr._active_key or "open"
            self.sdr.mark_error(
                key,
                summary=msg or "Error",
                info={"input": "SDR step", "decoded": msg or "Error", "note": msg},
            )
            self._now("SDR", msg or "Error")
