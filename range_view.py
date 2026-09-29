"""Range Radar tab — SDR dongle ↔ TPMS sensor scene + distance graph."""

from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk

from charts import TelemetryCharts
from range_radar import RangeRadarPanel, coerce_rssi_dbm, estimate_distance_m, format_distance
from themes import (
  COLOR_BG,
  COLOR_BG_CARD,
  COLOR_BORDER,
  COLOR_HEADER_ACCENT,
  COLOR_TEXT,
  COLOR_TEXT_DIM,
  COLOR_TEXT_MUTED,
)


class RangeView(ctk.CTkFrame):
  """Dedicated tab for SDR dongle ↔ TPMS sensor distance."""

  def __init__(
    self,
    master,
    *,
    get_sdr: Optional[Callable[[], dict]] = None,
    **kwargs,
  ) -> None:
    kwargs.setdefault("fg_color", COLOR_BG)
    super().__init__(master, **kwargs)
    self._get_sdr = get_sdr
    self._build()
    self.after(250, self._poll_sdr)

  def _build(self) -> None:
    head = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
    head.pack(fill="x", pady=(0, 8))
    inner = ctk.CTkFrame(head, fg_color="transparent")
    inner.pack(fill="x", padx=14, pady=12)
    ctk.CTkLabel(
      inner,
      text="Range Radar",
      font=ctk.CTkFont(size=16, weight="bold"),
      text_color=COLOR_TEXT,
    ).pack(side="left")
    ctk.CTkLabel(
      inner,
      text="SDR Dongle  ↔  TPMS Sensor   ·   distance in cm + m (auto-scale)",
      font=ctk.CTkFont(size=12),
      text_color=COLOR_TEXT_DIM,
    ).pack(side="left", padx=14)
    self.status_label = ctk.CTkLabel(
      inner,
      text="Waiting for live RF…",
      font=ctk.CTkFont(size=11, weight="bold"),
      text_color=COLOR_HEADER_ACCENT,
    )
    self.status_label.pack(side="right")

    self.radar = RangeRadarPanel(self, height=420)
    self.radar.pack(fill="both", expand=True)

    self.charts = TelemetryCharts(
      self,
      height=120,
      title="Range graphs  ·  SDR ↔ sensor only",
      series_titles=("Distance (cm)", "RSSI (dB)", "SNR (dB)"),
    )
    self.charts.pack(fill="x", pady=(8, 0))

    foot = ctk.CTkLabel(
      self,
      text="Distance shows cm and metres; radar scope auto-zooms (50 cm → 12 m). Board/TPMS range is not used.",
      font=ctk.CTkFont(size=10),
      text_color=COLOR_TEXT_MUTED,
      anchor="w",
    )
    foot.pack(fill="x", pady=(6, 0))

  def update_sdr(self, *, rssi_dbm: Any = None, sensor_id: str = "", raw: Any = None) -> None:
    rssi = coerce_rssi_dbm(rssi_dbm, raw=raw)
    self.radar.update_sdr(rssi_dbm=rssi, sensor_id=sensor_id or "", raw=raw)
    dist = estimate_distance_m(rssi, raw=raw)
    snr = None
    if isinstance(raw, dict) and raw.get("snr") not in (None, ""):
      try:
        snr = float(raw["snr"])
      except (TypeError, ValueError):
        snr = None
    dist_cm = dist * 100.0 if dist is not None else None
    self.charts.push(a=dist_cm, b=rssi, c=snr)
    if rssi is not None:
      dist_txt = format_distance(dist, dual=True) if dist is not None else ""
      self.status_label.configure(
        text=f"LINKED  ·  {rssi:.1f} dB" + (f"  ·  {dist_txt}" if dist_txt else "")
      )
    elif sensor_id:
      self.status_label.configure(text="Sensor ID (no RSSI yet)")

  def clear(self) -> None:
    self.radar.clear()
    self.charts.reset()
    self.status_label.configure(text="Waiting for live RF…")

  def _poll_sdr(self) -> None:
    try:
      if not self.winfo_exists():
        return
    except Exception:
      return
    try:
      snap = self._get_sdr() if self._get_sdr else None
    except Exception:
      snap = None
    if snap:
      latest = None
      for reading in snap.values():
        ts = getattr(reading, "timestamp", None)
        if latest is None or (ts and getattr(latest, "timestamp", None) and ts > latest.timestamp):
          latest = reading
      if latest is None:
        latest = next(iter(snap.values()), None)
      if latest is not None:
        raw = getattr(latest, "raw", None)
        rssi = getattr(latest, "rssi_db", None)
        if rssi is None:
          rssi = coerce_rssi_dbm(None, raw=raw if isinstance(raw, dict) else None)
        self.update_sdr(
          rssi_dbm=rssi,
          sensor_id=str(getattr(latest, "sensor_id", "") or ""),
          raw=raw if isinstance(raw, dict) else None,
        )
    try:
      if self.winfo_ismapped():
        self.after(250, self._poll_sdr)
      else:
        self.after(900, self._poll_sdr)
    except Exception:
      self.after(900, self._poll_sdr)
