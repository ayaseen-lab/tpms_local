"""Collapsible activity terminal panel (embedded in main window)."""

import customtkinter as ctk
from datetime import datetime

# Terminal palette — Hamaton navy, not VS Code grey
TERM_BG = "#0B1C2C"
TERM_BG_HEADER = "#12263A"
TERM_TEXT = "#E2E8F0"
TERM_TEXT_DIM = "#7DD3FC"
TERM_GREEN = "#34D399"
TERM_YELLOW = "#FBBF24"
TERM_RED = "#F87171"
TERM_CYAN = "#22B8E6"


class ActivityTerminalPanel(ctk.CTkFrame):
  """Expandable terminal log panel — no separate window."""

  PANEL_HEIGHT = 160

  def __init__(self, master, start_expanded: bool = False, **kwargs):
    super().__init__(master, fg_color=TERM_BG, corner_radius=8, border_width=1, border_color="#22B8E6", **kwargs)
    self._expanded = False
    self._start_expanded = start_expanded
    self._build()

  def _build(self):
    self.header = ctk.CTkFrame(self, fg_color=TERM_BG_HEADER, corner_radius=0, height=40)
    self.header.pack(fill="x")
    self.header.pack_propagate(False)

    self.toggle_btn = ctk.CTkButton(
      self.header,
      text="▾  Activity Terminal  (click to expand/collapse)",
      font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
      fg_color="transparent",
      hover_color="#1A365D",
      text_color=TERM_CYAN,
      anchor="w",
      height=36,
      command=self.toggle,
    )
    self.toggle_btn.pack(side="left", fill="x", expand=True, padx=8, pady=2)

    ctk.CTkButton(
      self.header,
      text="Clear",
      width=56,
      height=22,
      font=ctk.CTkFont(size=10),
      fg_color="#1A365D",
      hover_color="#0B1C2C",
      text_color=TERM_TEXT,
      command=self.clear,
    ).pack(side="right", padx=8, pady=4)

    self.content = ctk.CTkFrame(self, fg_color=TERM_BG)
    # collapsed by default — content not packed

    self.text = ctk.CTkTextbox(
      self.content,
      height=self.PANEL_HEIGHT,
      font=ctk.CTkFont(family="Consolas", size=11),
      fg_color=TERM_BG,
      text_color=TERM_TEXT,
      wrap="word",
      border_width=0,
      activate_scrollbars=True,
    )
    self.text.pack(fill="both", expand=True, padx=6, pady=6)
    self.text.configure(state="disabled")

    self.write("Activity terminal ready.", level="dim")
    self.write("Click the bar above to expand decoder output.", level="dim")
    if self._start_expanded:
      self.toggle()

  def _color_for(self, level: str) -> str:
    if level == "error":
      return TERM_RED
    if level == "warn":
      return TERM_YELLOW
    if level == "rx":
      return TERM_GREEN
    if level == "cmd":
      return TERM_CYAN
    if level == "dim":
      return TERM_TEXT_DIM
    return TERM_TEXT

  def write(self, message: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {message}\n"
    color = self._color_for(level)

    self.text.configure(state="normal")
    self.text._textbox.insert("end", line)
    start = self.text._textbox.index("end-1c linestart")
    end = self.text._textbox.index("end-1c")
    tag = f"level_{level}"
    if tag not in self.text._textbox.tag_names():
      self.text._textbox.tag_configure(tag, foreground=color)
    self.text._textbox.tag_add(tag, start, end)
    self.text.see("end")
    self.text.configure(state="disabled")
    line_count = int(float(self.text._textbox.index("end-1c").split(".")[0]))
    if line_count > 400:
      self.text.configure(state="normal")
      self.text._textbox.delete("1.0", "120.0")
      self.text.configure(state="disabled")

    if not self._expanded:
      short = message[:48] + ("…" if len(message) > 48 else "")
      self.toggle_btn.configure(text=f"▸  Activity Terminal — {short}")

  def clear(self):
    self.text.configure(state="normal")
    self.text.delete("1.0", "end")
    self.text.configure(state="disabled")
    self.toggle_btn.configure(text="▸  Activity Terminal  (click to expand/collapse)")
    self.write("Terminal cleared.", level="dim")

  def toggle(self):
    if self._expanded:
      self.content.pack_forget()
      self.toggle_btn.configure(text="▸  Activity Terminal  (click to expand/collapse)")
      self._expanded = False
    else:
      self.content.pack(fill="both", expand=True)
      self.toggle_btn.configure(text="▾  Activity Terminal  (click to expand/collapse)")
      self._expanded = True

  def expand(self):
    if not self._expanded:
      self.toggle()
