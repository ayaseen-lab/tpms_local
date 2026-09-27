"""Light-theme dashboard widgets for TPMS telemetry."""

import tkinter as tk
import customtkinter as ctk
from typing import Dict, List, Optional

from config import PRESSURE_LOW_PSI, PRESSURE_WARN_PSI
from rtl433_runner import TelemetryReading
from themes import (
  COLOR_BG,
  COLOR_BG_CARD,
  COLOR_BG_PANEL,
  COLOR_BORDER,
  COLOR_CYAN_BG,
  COLOR_DANGER,
  COLOR_GREEN,
  COLOR_GREEN_BG,
  COLOR_HEADER_ACCENT,
  COLOR_HEADER_BG,
  COLOR_OK,
  COLOR_ORANGE_BG,
  COLOR_RED,
  COLOR_RED_BG,
  COLOR_TEXT,
  COLOR_TEXT_DIM,
  COLOR_TEXT_MUTED,
  COLOR_WARN,
)


def pressure_color(psi: Optional[float]) -> str:
  if psi is None:
    return COLOR_TEXT_DIM
  if psi < PRESSURE_LOW_PSI:
    return COLOR_DANGER
  if psi < PRESSURE_WARN_PSI:
    return COLOR_WARN
  return COLOR_OK


class StatCard(ctk.CTkFrame):
  """Title on the left, number on the right — same row, always visible."""

  def __init__(self, master, title: str, value: str, accent: str, bg: str, compact: bool = False, **kwargs):
    kwargs.setdefault("fg_color", bg)
    kwargs.setdefault("corner_radius", 8)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", COLOR_BORDER)
    super().__init__(master, **kwargs)
    row = ctk.CTkFrame(self, fg_color="transparent")
    row.pack(fill="x", padx=12, pady=10)
    ctk.CTkLabel(
      row,
      text=title,
      font=ctk.CTkFont(size=11, weight="bold"),
      text_color=accent,
      anchor="w",
    ).pack(side="left")
    self.value_label = ctk.CTkLabel(
      row,
      text=str(value),
      font=ctk.CTkFont(size=20, weight="bold"),
      text_color="#102226",
      anchor="e",
      height=28,
    )
    self.value_label.pack(side="right")

  def set_value(self, value: str):
    self.value_label.configure(text=str(value), text_color="#102226")


class LiveTelemetryBar(ctk.CTkFrame):
  def __init__(self, master, **kwargs):
    super().__init__(master, fg_color=COLOR_CYAN_BG, corner_radius=6, **kwargs)
    inner = ctk.CTkFrame(self, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=10)
    ctk.CTkLabel(
      inner,
      text="LIVE TELEMETRY",
      font=ctk.CTkFont(size=9, weight="bold"),
      text_color=COLOR_TEXT_DIM,
      anchor="w",
    ).pack(anchor="w")
    self.label = ctk.CTkLabel(
      inner,
      text="Waiting for sensor data…",
      font=ctk.CTkFont(size=12, weight="bold"),
      text_color=COLOR_TEXT,
      anchor="w",
    )
    self.label.pack(fill="x", anchor="w", pady=(2, 0))

  def update_reading(self, reading: Optional[TelemetryReading]):
    if reading is None:
      self.label.configure(text="Waiting for sensor data…")
      return
    parts = [
      reading.display_decoder,
      f"ID {reading.sensor_id}",
      reading.display_temp,
      reading.display_pressure,
    ]
    if reading.battery_ok is not None:
      parts.append("Battery OK" if reading.battery_ok else "Battery LOW")
    self.label.configure(text="  ·  ".join(parts))


class SensorCard(ctk.CTkFrame):
  def __init__(self, master, **kwargs):
    super().__init__(
      master, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER, **kwargs
    )
    self._build()

  def _build(self):
    self.grid_columnconfigure(0, weight=1)

    header = ctk.CTkFrame(self, fg_color="transparent")
    header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
    header.grid_columnconfigure(0, weight=1)

    self.model_label = ctk.CTkLabel(
      header, text="Protocol", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_HEADER_ACCENT, anchor="w"
    )
    self.model_label.grid(row=0, column=0, sticky="w")

    self.status_dot = ctk.CTkLabel(header, text="●", font=ctk.CTkFont(size=12), text_color=COLOR_GREEN)
    self.status_dot.grid(row=0, column=1, padx=(8, 0))

    self.id_label = ctk.CTkLabel(
      self, text="Sensor ID: —", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_TEXT, anchor="w"
    )
    self.id_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))

    metrics = ctk.CTkFrame(self, fg_color="transparent")
    metrics.grid(row=2, column=0, sticky="ew", padx=14, pady=4)
    metrics.grid_columnconfigure((0, 1), weight=1)

    p_frame = ctk.CTkFrame(metrics, fg_color=COLOR_BG_PANEL, corner_radius=6)
    p_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    ctk.CTkLabel(p_frame, text="PRESSURE", font=ctk.CTkFont(size=9, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      anchor="w", padx=12, pady=(10, 0)
    )
    self.pressure_label = ctk.CTkLabel(
      p_frame, text="—", font=ctk.CTkFont(size=24, weight="bold"), text_color=COLOR_HEADER_ACCENT
    )
    self.pressure_label.pack(anchor="w", padx=12, pady=(2, 10))

    t_frame = ctk.CTkFrame(metrics, fg_color=COLOR_BG_PANEL, corner_radius=6)
    t_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    ctk.CTkLabel(t_frame, text="TEMPERATURE", font=ctk.CTkFont(size=9, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      anchor="w", padx=12, pady=(10, 0)
    )
    self.temp_label = ctk.CTkLabel(
      t_frame, text="—", font=ctk.CTkFont(size=24, weight="bold"), text_color=COLOR_TEXT
    )
    self.temp_label.pack(anchor="w", padx=12, pady=(2, 10))

    footer = ctk.CTkFrame(self, fg_color="transparent")
    footer.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 12))
    self.time_label = ctk.CTkLabel(
      footer, text="", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED, anchor="w"
    )
    self.time_label.pack(side="left")
    self.battery_label = ctk.CTkLabel(
      footer, text="", font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED, anchor="e"
    )
    self.battery_label.pack(side="right")

  def update_reading(self, reading: TelemetryReading):
    self.model_label.configure(text=reading.display_decoder[:48])
    self.id_label.configure(text=f"Sensor ID: {reading.sensor_id}")

    psi = reading.psi

    color = pressure_color(psi)
    self.pressure_label.configure(text=reading.display_pressure, text_color=color)
    self.temp_label.configure(text=reading.display_temp)
    self.status_dot.configure(text_color=color)

    ts = reading.timestamp.strftime("%H:%M:%S")
    self.time_label.configure(text=f"Last received {ts}")

    if reading.battery_ok is not None:
      bat = "Battery OK" if reading.battery_ok else "Battery LOW"
      bat_color = COLOR_OK if reading.battery_ok else COLOR_WARN
      self.battery_label.configure(text=bat, text_color=bat_color)
    else:
      self.battery_label.configure(text="")


class SensorGrid(ctk.CTkScrollableFrame):
  def __init__(self, master, **kwargs):
    super().__init__(master, fg_color=COLOR_BG, corner_radius=0, **kwargs)
    self._cards: Dict[str, SensorCard] = {}
    self._cols = 2

  def update_reading(self, reading: TelemetryReading):
    key = f"{reading.model}:{reading.sensor_id}"
    if key not in self._cards:
      card = SensorCard(self)
      self._cards[key] = card
      self._relayout()
    self._cards[key].update_reading(reading)

  def _relayout(self):
    keys = list(self._cards.keys())
    for i, key in enumerate(keys):
      row, col = divmod(i, self._cols)
      self._cards[key].grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
    for c in range(self._cols):
      self.grid_columnconfigure(c, weight=1)

  def clear(self):
    for card in self._cards.values():
      card.destroy()
    self._cards.clear()

  def sensor_count(self) -> int:
    return len(self._cards)

  def get_sensor_states(self) -> List[tuple[str, Optional[float]]]:
    states = []
    for key, card in self._cards.items():
      text = card.pressure_label.cget("text")
      psi = None
      if "PSI" in text:
        try:
          psi = float(text.replace("PSI", "").strip())
        except ValueError:
          pass
      states.append((key, psi))
    return states


class HistoryTable(ctk.CTkFrame):
  COLUMNS = ("#", "rtl_433 Decoder", "Sensor ID", "Pressure", "Temp", "Battery", "Time", "Status")
  MAX_VISIBLE_ROWS = 200

  def __init__(self, master, **kwargs):
    super().__init__(master, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER, **kwargs)
    self._row_count = 0
    self._row_widgets: List = []
    self._build()

  def _build(self):
    header = ctk.CTkFrame(self, fg_color=COLOR_HEADER_BG, corner_radius=0)
    header.pack(fill="x")
    widths = [40, 180, 110, 90, 70, 80, 70, 70]
    for i, (col, w) in enumerate(zip(self.COLUMNS, widths)):
      ctk.CTkLabel(
        header,
        text=col,
        width=w,
        font=ctk.CTkFont(size=10, weight="bold"),
        text_color="#ffffff",
        anchor="w",
      ).pack(side="left", padx=6, pady=8)

    self.scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_CARD, corner_radius=0, height=200)
    self.scroll.pack(fill="both", expand=True)

  def add_row(self, reading: TelemetryReading):
    self._row_count += 1
    psi = reading.psi

    status = "OK"
    bg = COLOR_GREEN_BG
    if psi is not None:
      if psi < PRESSURE_LOW_PSI:
        status = "LOW"
        bg = COLOR_RED_BG
      elif psi < PRESSURE_WARN_PSI:
        status = "WARN"
        bg = COLOR_ORANGE_BG

    row = ctk.CTkFrame(self.scroll, fg_color=bg, corner_radius=0)
    row.pack(fill="x")
    self._row_widgets.append(row)
    extra = len(self._row_widgets) - self.MAX_VISIBLE_ROWS
    if extra > 0:
      for old in self._row_widgets[:extra]:
        old.destroy()
      self._row_widgets = self._row_widgets[extra:]

    battery = "—"
    if reading.battery_ok is not None:
      battery = "OK" if reading.battery_ok else "LOW"

    values = [
      str(self._row_count),
      reading.display_decoder[:28],
      reading.sensor_id[:12],
      reading.display_pressure,
      reading.display_temp.replace(" °C", "°C"),
      battery,
      reading.timestamp.strftime("%H:%M:%S"),
      status,
    ]
    widths = [40, 180, 110, 90, 70, 80, 70, 70]
    status_color = COLOR_GREEN if status == "OK" else COLOR_RED if status == "LOW" else COLOR_WARN

    for val, w in zip(values, widths):
      color = status_color if val == status else COLOR_TEXT
      ctk.CTkLabel(row, text=val, width=w, font=ctk.CTkFont(size=11), text_color=color, anchor="w").pack(
        side="left", padx=6, pady=6
      )

  def clear(self):
    for child in self.scroll.winfo_children():
      child.destroy()
    self._row_count = 0
    self._row_widgets = []
