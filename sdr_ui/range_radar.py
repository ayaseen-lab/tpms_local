"""Live RF range — SDR dongle (center) and TPMS sensor (range blip)."""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Any, Optional

import customtkinter as ctk

from themes import (
  COLOR_BG_CARD,
  COLOR_BORDER,
  COLOR_HEADER_ACCENT,
  COLOR_ORANGE,
  COLOR_TEXT,
  COLOR_TEXT_DIM,
  COLOR_TEXT_MUTED,
  FYRQOM_TEAL,
)

# 433.92 MHz λ ≈ 0.69 m — bench distances under ~1.5 m are near-field.
# Log-distance FSPL maps strong RSSI to ~8 cm; real bench at 60 cm is still
# RSSI ≈ −5 to −12 dB on RTL-SDR. Use empirical RSSI(+SNR) interpolation.
_MAX_RANGE_M = 12.0
# (rssi_db, metres) — stronger (less negative) → closer.
_RSSI_RANGE_KNOTS: tuple[tuple[float, float], ...] = (
  (6.0, 0.18),
  (2.0, 0.28),
  (-2.0, 0.40),
  (-5.0, 0.52),
  (-8.0, 0.60),
  (-12.0, 0.78),
  (-16.0, 0.95),
  (-22.0, 1.30),
  (-28.0, 1.75),
  (-36.0, 2.60),
  (-45.0, 4.00),
  (-55.0, 6.20),
  (-70.0, 9.50),
  (-90.0, 12.00),
)


def _first_float(mapping: dict, *keys: str) -> Optional[float]:
  for key in keys:
    if key not in mapping or mapping[key] in (None, ""):
      continue
    try:
      return float(mapping[key])
    except (TypeError, ValueError):
      continue
  return None


def _fuse_rf_level(rssi_db: float, raw: Any = None) -> float:
  """Blend rtl_433 RSSI with SNR so a single noisy packet does not jump range."""
  level = rssi_db
  if not isinstance(raw, dict):
    return level
  snr = _first_float(raw, "snr", "SNR")
  noise = _first_float(raw, "noise", "Noise")
  if snr is None:
    return level
  if noise is not None:
    reconstructed = noise + snr
  else:
    reconstructed = -40.0 + snr
  # RSSI dominates; SNR only tugs the estimate (near-field RSSI is flatter).
  return 0.82 * level + 0.18 * reconstructed


def _interp_knots(rssi_db: float) -> float:
  knots = _RSSI_RANGE_KNOTS
  if rssi_db >= knots[0][0]:
    return knots[0][1]
  if rssi_db <= knots[-1][0]:
    return knots[-1][1]
  for (r0, d0), (r1, d1) in zip(knots, knots[1:]):
    if r1 <= rssi_db <= r0:
      span = r0 - r1
      t = 0.0 if span <= 1e-9 else (r0 - rssi_db) / span
      # Log-distance between knots (smoother than linear metres).
      lo, hi = math.log(max(d0, 0.05)), math.log(max(d1, 0.05))
      return math.exp(lo + t * (hi - lo))
  return knots[-1][1]


def estimate_distance_m(rssi_dbm: Optional[float], raw: Any = None) -> Optional[float]:
  """433 MHz near-field ranging via empirical RSSI/SNR interpolation (not FSPL)."""
  if rssi_dbm is None and not isinstance(raw, dict):
    return None
  rssi = None
  if rssi_dbm is not None and rssi_dbm != "":
    try:
      rssi = float(rssi_dbm)
    except (TypeError, ValueError):
      rssi = None
  if rssi is None:
    rssi = coerce_rssi_dbm(None, raw=raw)
  if rssi is None:
    return None
  level = _fuse_rf_level(rssi, raw)
  level = max(-95.0, min(10.0, level))
  dist = _interp_knots(level)
  return max(0.12, min(_MAX_RANGE_M, dist))


def coerce_rssi_dbm(value: Any = None, *, raw: Any = None) -> Optional[float]:
  if value is not None and value != "":
    try:
      return float(value)
    except (TypeError, ValueError):
      text = str(value).strip().replace("dB", "").replace("dbm", "").strip()
      try:
        return float(text)
      except ValueError:
        pass
  if isinstance(raw, dict):
    for key in ("rssi", "RSSI", "rssi_db"):
      if key in raw and raw[key] not in (None, ""):
        try:
          return float(raw[key])
        except (TypeError, ValueError):
          continue
    try:
      snr = float(raw["snr"]) if raw.get("snr") not in (None, "") else None
      noise = float(raw["noise"]) if raw.get("noise") not in (None, "") else None
      if snr is not None and noise is not None:
        return noise + snr
      if snr is not None:
        return -40.0 + snr
    except (TypeError, ValueError):
      pass
  return None


def format_distance(metres: Optional[float], *, dual: bool = True) -> str:
  """Human distance — cm + m when dual."""
  if metres is None:
    return "—"
  try:
    m = float(metres)
  except (TypeError, ValueError):
    return "—"
  cm = m * 100.0
  if dual:
    if m < 10.0:
      return f"{cm:.0f} cm  ·  {m:.2f} m"
    return f"{m:.1f} m  ·  {cm:.0f} cm"
  if m < 1.0:
    return f"{cm:.0f} cm"
  if m < 10.0:
    return f"{m:.2f} m"
  return f"{m:.1f} m"


def format_distance_short(metres: Optional[float]) -> str:
  if metres is None:
    return "—"
  try:
    m = float(metres)
  except (TypeError, ValueError):
    return "—"
  if m < 2.0:
    return f"{m * 100:.0f} cm"
  if m < 10.0:
    return f"{m:.2f} m"
  return f"{m:.1f} m"


class RangeRadarPanel(ctk.CTkFrame):
  """Clean radar: SDR dongle at center + TPMS sensor on the range ring."""

  def __init__(self, master, height: int = 168, **kwargs):
    kwargs.setdefault("fg_color", COLOR_BG_CARD)
    kwargs.setdefault("corner_radius", 12)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", COLOR_BORDER)
    super().__init__(master, **kwargs)
    self._height = height
    self._sweep = 0.0
    self._pulse = 0.0
    self._sdr_rssi: Optional[float] = None
    self._sdr_m: Optional[float] = None
    self._sdr_m_smooth: Optional[float] = None
    self._sdr_id = "—"
    self._sensor_angle = 55.0
    self._trails: list[tuple[float, float, float]] = []
    self._dist_history: list[float] = []
    self._last_draw = 0.0
    self._build()
    self.after(33, self._tick)

  def _build(self) -> None:
    header = ctk.CTkFrame(self, fg_color="transparent")
    header.pack(fill="x", padx=14, pady=(10, 4))
    ctk.CTkLabel(
      header,
      text="RANGE SCENE",
      font=ctk.CTkFont(size=11, weight="bold"),
      text_color=COLOR_HEADER_ACCENT,
      anchor="w",
    ).pack(side="left")
    self.hint_label = ctk.CTkLabel(
      header,
      text="SDR Dongle  ↔  TPMS Sensor",
      font=ctk.CTkFont(size=10),
      text_color=COLOR_TEXT_MUTED,
      anchor="e",
    )
    self.hint_label.pack(side="right")

    body = ctk.CTkFrame(self, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    self.canvas = tk.Canvas(
      body,
      height=self._height,
      bg="#071412",
      highlightthickness=0,
      bd=0,
    )
    self.canvas.pack(side="left", fill="both", expand=True, padx=(0, 10))

    side = ctk.CTkFrame(body, fg_color="transparent", width=200)
    side.pack(side="right", fill="y")
    side.pack_propagate(False)

    self._object_card(side, "SDR DONGLE", "Receiver  ·  center", FYRQOM_TEAL)
    self._object_card(side, "SENSOR", "RF target  ·  range from SDR", COLOR_ORANGE)

    self.sdr_dist_label = self._metric_block(side, "DISTANCE", FYRQOM_TEAL)
    self.sdr_rssi_label = ctk.CTkLabel(
      side, text="RSSI  —", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM, anchor="w"
    )
    self.sdr_rssi_label.pack(fill="x", pady=(8, 0))
    self.id_label = ctk.CTkLabel(
      side, text="ID  —", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT, anchor="w"
    )
    self.id_label.pack(fill="x", pady=(6, 0))
    self.range_label = ctk.CTkLabel(
      side,
      text="Scope  auto",
      font=ctk.CTkFont(size=9),
      text_color=COLOR_TEXT_MUTED,
      anchor="w",
    )
    self.range_label.pack(fill="x", pady=(10, 0))

  def _object_card(self, master, title: str, subtitle: str, accent: str) -> None:
    wrap = ctk.CTkFrame(master, fg_color="#F3FAF8", corner_radius=8, border_width=1, border_color="#D5E8E3")
    wrap.pack(fill="x", pady=(0, 6))
    row = ctk.CTkFrame(wrap, fg_color="transparent")
    row.pack(fill="x", padx=10, pady=8)
    dot = ctk.CTkFrame(row, width=10, height=10, corner_radius=5, fg_color=accent)
    dot.pack(side="left", padx=(0, 8))
    dot.pack_propagate(False)
    texts = ctk.CTkFrame(row, fg_color="transparent")
    texts.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(
      texts, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color=accent, anchor="w"
    ).pack(fill="x")
    ctk.CTkLabel(
      texts, text=subtitle, font=ctk.CTkFont(size=9), text_color=COLOR_TEXT_MUTED, anchor="w"
    ).pack(fill="x")

  def _metric_block(self, master, title: str, accent: str) -> ctk.CTkLabel:
    wrap = ctk.CTkFrame(master, fg_color="#EAF6F4", corner_radius=10)
    wrap.pack(fill="x", pady=(4, 6))
    ctk.CTkLabel(
      wrap, text=title, font=ctk.CTkFont(size=9, weight="bold"), text_color=accent, anchor="w"
    ).pack(fill="x", padx=12, pady=(10, 0))
    value = ctk.CTkLabel(
      wrap, text="—", font=ctk.CTkFont(size=22, weight="bold"), text_color=COLOR_TEXT, anchor="w"
    )
    value.pack(fill="x", padx=12, pady=(0, 10))
    return value

  def _smooth_metres(self, prev: Optional[float], new: Optional[float]) -> Optional[float]:
    if new is None:
      return prev
    if prev is None:
      return new
    if abs(new - prev) >= 0.12:
      return 0.88 * new + 0.12 * prev
    return 0.72 * new + 0.28 * prev

  def update_sdr(
    self,
    *,
    rssi_dbm: Optional[float],
    sensor_id: str = "",
    distance_m: Optional[float] = None,
    raw: Any = None,
  ) -> None:
    rssi_dbm = coerce_rssi_dbm(rssi_dbm, raw=raw)
    if rssi_dbm is None:
      return
    self._sdr_rssi = rssi_dbm
    instant = distance_m if distance_m is not None else estimate_distance_m(rssi_dbm, raw=raw)
    self._sdr_m_smooth = self._smooth_metres(self._sdr_m_smooth, instant)
    self._sdr_m = self._sdr_m_smooth
    if sensor_id:
      self._sdr_id = str(sensor_id)
    if self._sdr_m is not None:
      scope = self._scope_max_m()
      self._sensor_angle = (50.0 + (self._sdr_m / scope) * 40.0) % 360.0
      self._trails.append((self._sensor_angle, self._sdr_m, time.monotonic()))
      if len(self._trails) > 40:
        self._trails = self._trails[-40:]
      self._dist_history.append(self._sdr_m)
      self._dist_history = self._dist_history[-60:]
    self._refresh_labels()

  def update_tpms(self, **_kwargs) -> None:
    return

  def distance_history(self) -> list[float]:
    return list(self._dist_history)

  def clear(self) -> None:
    self._sdr_rssi = None
    self._sdr_m = None
    self._sdr_m_smooth = None
    self._sdr_id = "—"
    self._trails.clear()
    self._dist_history.clear()
    self._refresh_labels()

  def _refresh_labels(self) -> None:
    self.sdr_dist_label.configure(text=format_distance(self._sdr_m, dual=True))
    if self._sdr_rssi is None:
      self.sdr_rssi_label.configure(text="RSSI  —")
    else:
      self.sdr_rssi_label.configure(text=f"RSSI  {self._sdr_rssi:.1f} dB")
    self.id_label.configure(text=f"ID  {self._sdr_id or '—'}")

  def _tick(self) -> None:
    try:
      if not self.winfo_exists():
        return
      if not self.winfo_ismapped():
        self.after(250, self._tick)
        return
    except tk.TclError:
      return
    now = time.monotonic()
    dt = max(0.01, min(0.08, now - self._last_draw)) if self._last_draw else 0.033
    self._last_draw = now
    self._sweep = (self._sweep + 100.0 * dt) % 360.0
    self._pulse = (self._pulse + 2.0 * dt) % (math.pi * 2)
    cutoff = now - 3.0
    self._trails = [t for t in self._trails if t[2] >= cutoff]
    self._draw_radar()
    self.after(33, self._tick)

  def _polar(self, cx: float, cy: float, radius: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg - 90.0)
    return cx + radius * math.cos(rad), cy + radius * math.sin(rad)

  def _scope_max_m(self) -> float:
    if self._sdr_m is None:
      return 1.0
    m = self._sdr_m
    if m <= 0.35:
      return 0.50
    if m <= 0.70:
      return 1.0
    if m <= 1.40:
      return 2.0
    if m <= 3.50:
      return 5.0
    if m <= 7.0:
      return 8.0
    return _MAX_RANGE_M

  def _ring_label(self, metres: float) -> str:
    if metres < 1.0:
      return f"{metres * 100:.0f} cm"
    if abs(metres - round(metres)) < 0.05:
      return f"{metres:.0f} m"
    return f"{metres:.1f} m"

  def _metres_to_r(self, metres: float, max_r: float) -> float:
    """Map distance to radius — keep icons clearly separated even at short range."""
    scope = self._scope_max_m()
    m = max(0.03, min(scope, float(metres)))
    frac = m / scope
    # Min ~38% of dial so SDR + SENSOR never sit on top of each other.
    return max(max_r * 0.38, min(max_r * 0.90, max_r * (0.28 + 0.62 * frac)))

  def _draw_radar(self) -> None:
    c = self.canvas
    w = max(c.winfo_width(), 280)
    h = max(c.winfo_height(), self._height)
    c.delete("all")

    c.create_rectangle(0, 0, w, h, fill="#071412", outline="")
    cx, cy = w * 0.50, h * 0.52
    max_r = min(w * 0.40, h * 0.40)
    scope = self._scope_max_m()

    # Dial
    c.create_oval(cx - max_r - 6, cy - max_r - 6, cx + max_r + 6, cy + max_r + 6, fill="#0A1A16", outline="#1A433C", width=2)
    c.create_oval(cx - max_r, cy - max_r, cx + max_r, cy + max_r, outline="#00C9B1", width=2)

    for frac in (0.25, 0.5, 0.75, 1.0):
      r = max_r * frac
      c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#163E37", width=1)
      # Scale tick on the right edge only — no boxes.
      lx, ly = self._polar(cx, cy, r, 90)
      c.create_text(lx + 6, ly, text=self._ring_label(scope * frac), anchor="w", fill="#3A7A6E", font=("Segoe UI", 8))

    for deg in range(0, 360, 45):
      x1, y1 = self._polar(cx, cy, 26, deg)
      x2, y2 = self._polar(cx, cy, max_r, deg)
      c.create_line(x1, y1, x2, y2, fill="#143630", width=1)

    # Soft sweep
    sweep = self._sweep
    for i in range(10, 0, -1):
      a0 = sweep - i * 3.0
      a1 = sweep - (i - 1) * 3.0
      fade = int(6 + (10 - i) * 6)
      color = f"#{0:02x}{min(255, 30 + fade):02x}{min(255, 24 + fade // 2):02x}"
      pts = [cx, cy]
      for step in range(6):
        ang = a0 + (a1 - a0) * (step / 5.0)
        px, py = self._polar(cx, cy, max_r, ang)
        pts.extend([px, py])
      if len(pts) >= 6:
        c.create_polygon(pts, fill=color, outline="")
    bx, by = self._polar(cx, cy, max_r, sweep)
    c.create_line(cx, cy, bx, by, fill="#6AE8D6", width=1)

    # Faint trail dots only (no labels)
    now = time.monotonic()
    for ang, metres, ts in self._trails:
      age = now - ts
      if age > 3.0:
        continue
      alpha = 1.0 - age / 3.0
      r = self._metres_to_r(metres, max_r)
      px, py = self._polar(cx, cy, r, ang)
      size = 1.5 + 2.0 * alpha
      c.create_oval(px - size, py - size, px + size, py + size, fill="#C47A3A", outline="")

    # —— Object 1: SDR dongle (center) ——
    self._draw_sdr_dongle(c, cx, cy)

    # —— Object 2: TPMS sensor ——
    if self._sdr_m is not None:
      angle = 50.0 + (self._sdr_m / max(scope, 0.1)) * 40.0
      self._sensor_angle = angle % 360.0
      sr = self._metres_to_r(self._sdr_m, max_r)
      sx, sy = self._polar(cx, cy, sr, self._sensor_angle)
      c.create_line(cx, cy, sx, sy, fill="#3ECFBE", width=2, dash=(4, 3))
      self._draw_tpms_sensor(c, sx, sy)
    else:
      sx, sy = self._polar(cx, cy, max_r * 0.55, 50)
      self._draw_tpms_sensor(c, sx, sy, active=False)

    # Minimal corner status (no pills / legends)
    status = "LINKED" if self._sdr_m is not None else "SEARCHING"
    c.create_text(12, 14, text=status, anchor="w", fill="#5AD9C4", font=("Segoe UI", 10, "bold"))
    c.create_text(
      w - 12,
      14,
      text=f"0 – {self._ring_label(scope)}",
      anchor="e",
      fill="#3A7A6E",
      font=("Segoe UI", 9),
    )

    try:
      self.range_label.configure(text=f"Scope  0 – {self._ring_label(scope)}  (auto)")
    except Exception:
      pass

  def _draw_sdr_dongle(self, c: tk.Canvas, cx: float, cy: float) -> None:
    pulse = 12 + int(2 * (0.5 + 0.5 * math.sin(self._pulse)))
    c.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse, outline="#1F5A4E", width=1)
    c.create_rectangle(cx - 10, cy - 7, cx + 10, cy + 9, fill="#0E3D36", outline=FYRQOM_TEAL, width=2)
    c.create_rectangle(cx - 5, cy - 13, cx + 5, cy - 7, fill="#1A5C52", outline=FYRQOM_TEAL, width=1)
    c.create_line(cx, cy - 13, cx, cy - 20, fill=FYRQOM_TEAL, width=2)
    c.create_oval(cx - 2.5, cy - 24, cx + 2.5, cy - 19, fill=FYRQOM_TEAL, outline="")
    c.create_text(cx, cy + 18, text="SDR", fill="#7FE8D8", font=("Segoe UI", 8, "bold"))

  def _draw_tpms_sensor(self, c: tk.Canvas, x: float, y: float, *, active: bool = True) -> None:
    color = COLOR_ORANGE if active else "#6A4A2E"
    glow = 11 + int(2 * (0.5 + 0.5 * math.sin(self._pulse + 1.2))) if active else 8
    c.create_oval(x - glow, y - glow, x + glow, y + glow, outline=color, width=1)
    c.create_oval(x - 9, y - 9, x + 9, y + 9, fill="#2A1A0E", outline=color, width=2)
    c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="#FFE8D4", width=1)
    c.create_rectangle(x - 2.5, y - 15, x + 2.5, y - 9, fill=color, outline="")
    c.create_text(x, y + 20, text="SENSOR" if active else "…", fill=color, font=("Segoe UI", 8, "bold"))
