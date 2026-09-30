"""SDR Receiver view — RTL-SDR telemetry dashboard (embeddable frame)."""

import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Deque, Dict, Optional

import customtkinter as ctk

from activity_terminal import ActivityTerminalPanel
from charts import SdrRfCharts
from config import APP_NAME, DEFAULT_PRESET, FREQUENCY_PRESETS, get_rtl433_exe
from dialogs import ask_save_path
from rtl433_runner import Rtl433Runner, TelemetryReading
from session_export import export_session_excel, export_session_pdf
from session_persist import clear_session_file, load_session, save_session
from setup_manager import SetupManager
from setup_wizard import SetupWizard
from themes import (
  COLOR_BG,
  COLOR_BG_CARD,
  COLOR_BG_PANEL,
  COLOR_BORDER,
  COLOR_BTN_EXPORT,
  COLOR_BTN_EXPORT_HOVER,
  COLOR_BTN_PRIMARY,
  COLOR_BTN_PRIMARY_HOVER,
  COLOR_BTN_PRIMARY_TEXT,
  COLOR_BTN_SECONDARY,
  COLOR_BTN_SECONDARY_HOVER,
  COLOR_BTN_STOP,
  COLOR_BTN_STOP_HOVER,
  COLOR_BTN_PAUSE,
  COLOR_BTN_PAUSE_HOVER,
  COLOR_BLUE,
  COLOR_BLUE_BG,
  COLOR_CYAN_BG,
  COLOR_GREEN,
  COLOR_GREEN_BG,
  COLOR_HEADER_ACCENT,
  COLOR_HEADER_BG,
  COLOR_ORANGE,
  COLOR_ORANGE_BG,
  COLOR_RED,
  COLOR_RED_BG,
  COLOR_TEXT,
  COLOR_TEXT_DIM,
  COLOR_TEXT_MUTED,
  combo_colors,
  entry_colors,
  switch_colors,
)
from widgets import LiveTelemetryBar, StatCard


class SdrView(ctk.CTkFrame):
  """SDR receiver UI. Switching away from this frame does not stop rtl_433."""

  def __init__(self, master, on_status_change: Optional[Callable[[bool, str], None]] = None, **kwargs):
    kwargs.setdefault("fg_color", COLOR_BG)
    super().__init__(master, **kwargs)
    self.on_status_change = on_status_change or (lambda _running, _label: None)
    self.on_range_update: Optional[Callable[..., None]] = None

    self.setup_mgr = SetupManager()
    self.history: Deque[TelemetryReading] = deque(maxlen=50000)
    self._sensors: Dict[str, TelemetryReading] = {}
    self._sensor_items: Dict[str, str] = {}
    self._sensor_reads: Dict[str, int] = {}
    self._sensor_first_seen: Dict[str, datetime] = {}
    # One entry per Board row that produced an RF ID — so MATCHES tracks Board rows, not unique IDs.
    self._row_matches: list[dict] = []
    self._listening = False
    self._sdr_paused = False
    self._want_listening = False
    self._manual_restarting = False
    self._restart_scheduled = False
    self._auto_restarts = 0
    self._starting = False
    self._listen_grace_until = 0.0
    self._total_readings = 0
    self._latest: Optional[TelemetryReading] = None
    self._session_start: Optional[datetime] = None
    self._exporting = False
    # Batch UI work — per-packet tree/stat updates freeze the GUI under dense TPMS RF.
    self._pending_readings: Deque[TelemetryReading] = deque(maxlen=4096)
    self._pending_lock = threading.Lock()
    self._flush_scheduled = False
    self._quiet_restarted = False
    self._autosave_dirty = False
    self._last_live_bar_ts = 0.0
    self._last_rf_charts_ts = 0.0
    self._last_match_scan_ts = 0.0
    self._UI_FLUSH_MS = 50
    self._AUTOSAVE_MS = 8000
    self._LIVE_BAR_MIN_MS = 50
    self._RF_CHARTS_MIN_MS = 120
    self._FLUSH_BATCH_MAX = 96
    self._log_rx_count = 0
    self._range_focus_id = ""
    self._range_watch_until = 0.0

    self.runner = Rtl433Runner(
      on_reading=self._on_reading,
      on_log=self._on_log,
      on_state_change=self._on_state_change,
    )

    self._setup_styles()
    self._build_ui()
    self._load_prefs()
    # Session restore deferred — CombinedApp asks Continue vs New Session at startup.
    self._update_stats()
    self._notify_status()
    self.after(self._AUTOSAVE_MS, self._autosave_tick)
    self.after(self._UI_FLUSH_MS, self._flush_readings_tick)
    self.after(2500, self._keepalive_tick)

    if self.setup_mgr.is_first_run():
      self.after(400, self._show_setup)

  def _toplevel(self):
    return self.winfo_toplevel()

  def _setup_styles(self) -> None:
    style = ttk.Style(self._toplevel())
    style.theme_use("clam")
    style.configure(
      "Combined.Treeview",
      background=COLOR_BG,
      foreground=COLOR_TEXT,
      fieldbackground=COLOR_BG,
      rowheight=24,
      font=("Segoe UI", 10),
      bordercolor=COLOR_BORDER,
      borderwidth=0,
    )
    style.configure(
      "Combined.Treeview.Heading",
      background=COLOR_HEADER_BG,
      foreground="#ffffff",
      font=("Segoe UI", 9, "bold"),
      relief="flat",
      padding=6,
    )
    style.map(
      "Combined.Treeview.Heading",
      background=[("active", "#12263A")],
      foreground=[("active", "#ffffff")],
    )
    style.map("Combined.Treeview", background=[("selected", "#D6E8F5")], foreground=[("selected", COLOR_TEXT)])
    style.configure(
      "Combined.Vertical.TScrollbar",
      background="#C5CED8",
      troughcolor=COLOR_BG,
      arrowcolor=COLOR_HEADER_BG,
      bordercolor=COLOR_BORDER,
    )
    style.configure(
      "Combined.Horizontal.TScrollbar",
      background="#C5CED8",
      troughcolor=COLOR_BG,
      arrowcolor=COLOR_HEADER_BG,
      bordercolor=COLOR_BORDER,
    )

  def _build_ui(self):
    footer = ctk.CTkFrame(self, fg_color="transparent")
    footer.pack(side="bottom", fill="x")
    self.footer_label = ctk.CTkLabel(
      footer,
      text="Ready — connect RTL-SDR and press START",
      font=ctk.CTkFont(size=10),
      text_color=COLOR_TEXT_MUTED,
      anchor="w",
    )
    self.footer_label.pack(side="left")

    self.activity_terminal = ActivityTerminalPanel(self, start_expanded=False)
    self.activity_terminal.pack(side="bottom", fill="x", pady=(4, 0))

    # Pack table before stats so stats sit above the table (never clipped by top panels).
    results = tk.Frame(self, bg=COLOR_BG, highlightbackground=COLOR_BORDER, highlightthickness=1)
    results.pack(side="bottom", fill="x", pady=(6, 2))

    table_header = tk.Frame(results, bg=COLOR_BG_PANEL)
    table_header.pack(fill="x")
    tk.Label(
      table_header, text="SDR matches — one row per Board test (same ID can repeat)", bg=COLOR_BG_PANEL, fg=COLOR_TEXT, font=("Segoe UI", 10, "bold")
    ).pack(side="left", padx=8, pady=4)
    self.table_count_label = tk.Label(
      table_header, text="0 sensors", bg=COLOR_BG_PANEL, fg=COLOR_TEXT_DIM, font=("Segoe UI", 9)
    )
    self.table_count_label.pack(side="right", padx=8)

    tree_host = tk.Frame(results, bg=COLOR_BG)
    tree_host.pack(fill="x", padx=4, pady=(0, 4))
    columns = (
      "num", "protocol", "id", "result", "pressure", "pressure_bar",
      "temp", "battery", "rssi", "reads", "time", "reason",
    )
    self.tree = ttk.Treeview(tree_host, columns=columns, show="headings", height=6, style="Combined.Treeview")
    headings = {
      "num": "#",
      "protocol": "rtl_433 Decoder",
      "id": "Sensor ID",
      "result": "Result",
      "pressure": "PSI",
      "pressure_bar": "bar",
      "temp": "°C",
      "battery": "Batt",
      "rssi": "RSSI",
      "reads": "Reads",
      "time": "Seen",
      "reason": "Notes / NOK reason",
    }
    self._tree_col_weights = {
      "num": 0.04,
      "protocol": 0.14,
      "id": 0.10,
      "result": 0.06,
      "pressure": 0.07,
      "pressure_bar": 0.07,
      "temp": 0.05,
      "battery": 0.06,
      "rssi": 0.06,
      "reads": 0.05,
      "time": 0.07,
      "reason": 0.23,
    }
    for col in columns:
      self.tree.heading(col, text=headings[col])
      self.tree.column(
        col,
        width=80,
        minwidth=36,
        stretch=True,
        anchor="center" if col not in ("reason", "protocol") else "w",
      )
    scroll_y = ttk.Scrollbar(
      tree_host, orient="vertical", command=self.tree.yview, style="Combined.Vertical.TScrollbar"
    )
    self.tree.configure(yscrollcommand=scroll_y.set)
    tree_host.grid_columnconfigure(0, weight=1)
    self.tree.grid(row=0, column=0, sticky="ew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    self.tree.tag_configure("OK", background=COLOR_GREEN_BG, foreground="#047857")
    self.tree.tag_configure("NOK", background=COLOR_RED_BG, foreground="#B91C1C")
    self.tree.tag_configure("WAIT", background=COLOR_CYAN_BG, foreground="#0F766E")
    self.tree.tag_configure("flash", background=COLOR_CYAN_BG)
    self.tree.bind("<Configure>", self._fit_tree_columns, add="+")
    self.after(50, self._fit_tree_columns)

    stats_anchor = ctk.CTkFrame(self, fg_color="transparent")
    stats_anchor.pack(side="bottom", fill="x", pady=(4, 0))

    # Graphs reserved on bottom stack so they stay visible under the live table/stats.
    charts_anchor = ctk.CTkFrame(self, fg_color="transparent")
    charts_anchor.pack(side="bottom", fill="x", pady=(0, 4))
    self.rf_charts = SdrRfCharts(
      charts_anchor, height=128, title="SDR RF graphs  ·  RSSI histogram / scatter / unique IDs"
    )
    self.rf_charts.pack(fill="x")

    top = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
    top.pack(fill="x", pady=(0, 6))
    top_inner = ctk.CTkFrame(top, fg_color="transparent")
    top_inner.pack(fill="x", padx=10, pady=8)

    title_row = ctk.CTkFrame(top_inner, fg_color="transparent")
    title_row.pack(fill="x", pady=(0, 6))
    ctk.CTkLabel(title_row, text="SDR Receiver", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_TEXT).pack(side="left")
    self.running_badge = ctk.CTkLabel(
      title_row, text="● STOPPED", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_RED
    )
    self.running_badge.pack(side="right")
    ctk.CTkLabel(
      title_row,
      text="rtl_433  ·  live KPIs  ·  RF graphs  ·  auto distance",
      font=ctk.CTkFont(size=11),
      text_color=COLOR_TEXT_DIM,
    ).pack(side="right", padx=(0, 12))

    actions_inner = ctk.CTkFrame(top_inner, fg_color="transparent")
    actions_inner.pack(fill="x", pady=(0, 6))
    self.start_btn = ctk.CTkButton(
      actions_inner, text="START", width=130, height=34, font=ctk.CTkFont(size=12, weight="bold"),
      fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER,
      text_color=COLOR_BTN_PRIMARY_TEXT, command=self._start_listen,
    )
    self.start_btn.pack(side="left", padx=(0, 6))
    self.pause_btn = ctk.CTkButton(
      actions_inner, text="PAUSE", width=90, height=34, font=ctk.CTkFont(size=12, weight="bold"),
      fg_color=COLOR_BTN_PAUSE, hover_color=COLOR_BTN_PAUSE_HOVER, text_color="#FFFFFF",
      state="disabled", command=self._pause_listen,
    )
    self.pause_btn.pack(side="left", padx=(0, 6))
    self.stop_btn = ctk.CTkButton(
      actions_inner, text="STOP", width=90, height=34, font=ctk.CTkFont(size=12, weight="bold"),
      fg_color=COLOR_BTN_STOP, hover_color=COLOR_BTN_STOP_HOVER, text_color="#FFFFFF",
      state="disabled", command=self._stop_listen,
    )
    self.stop_btn.pack(side="left")
    ctk.CTkButton(
      actions_inner, text="Clear", width=70, height=28, font=ctk.CTkFont(size=11),
      fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER, command=self._clear_session,
    ).pack(side="left", padx=(12, 0))

    self.export_pdf_btn = ctk.CTkButton(
      actions_inner, text="Export SDR PDF", width=140, height=30, font=ctk.CTkFont(size=11, weight="bold"),
      fg_color=COLOR_BTN_EXPORT, hover_color=COLOR_BTN_EXPORT_HOVER, command=lambda: self._export_session("pdf"),
    )
    self.export_pdf_btn.pack(side="right")
    self.export_btn = ctk.CTkButton(
      actions_inner, text="Export SDR Excel", width=150, height=30, font=ctk.CTkFont(size=11, weight="bold"),
      fg_color=COLOR_BTN_EXPORT, hover_color=COLOR_BTN_EXPORT_HOVER, command=lambda: self._export_session("xlsx"),
    )
    self.export_btn.pack(side="right", padx=(0, 6))

    settings_row = ctk.CTkFrame(top_inner, fg_color="transparent")
    settings_row.pack(fill="x")
    ctk.CTkLabel(settings_row, text="Band", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      side="left", padx=(0, 4)
    )
    preset_names = list(FREQUENCY_PRESETS.keys())
    self.preset_combo = ctk.CTkComboBox(
      settings_row, values=preset_names, width=150, height=28, command=self._on_preset_change, **combo_colors()
    )
    self.preset_combo.set(DEFAULT_PRESET)
    self.preset_combo.pack(side="left", padx=(0, 8))
    ctk.CTkLabel(settings_row, text="MHz", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      side="left", padx=(0, 4)
    )
    self.custom_freq = ctk.CTkEntry(settings_row, width=70, height=28, **entry_colors())
    self.custom_freq.insert(0, "433.92")
    self.custom_freq.pack(side="left", padx=(0, 8))
    ctk.CTkLabel(settings_row, text="Gain", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      side="left", padx=(0, 4)
    )
    self.gain_combo = ctk.CTkComboBox(
      settings_row, values=["auto", "0", "20", "30", "40", "49.6"], width=72, height=28, **combo_colors()
    )
    self.gain_combo.set("auto")
    self.gain_combo.pack(side="left", padx=(0, 8))
    self.tpms_only_switch = ctk.CTkSwitch(
      settings_row, text="TPMS only", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT, **switch_colors()
    )
    self.tpms_only_switch.deselect()
    self.tpms_only_switch.pack(side="left", padx=(4, 0))
    self.record_iq_switch = ctk.CTkSwitch(
      settings_row,
      text="Record IQ",
      font=ctk.CTkFont(size=11),
      text_color=COLOR_TEXT,
      **switch_colors(),
    )
    self.record_iq_switch.deselect()
    self.record_iq_switch.pack(side="left", padx=(10, 0))
    # Advanced fields kept for Setup / runtime API but not crowding the main bar.
    self.ppm_entry = ctk.CTkEntry(settings_row, width=50, height=28, **entry_colors())
    self.ppm_entry.insert(0, "0")
    self.device_entry = ctk.CTkEntry(settings_row, width=46, height=28, **entry_colors())
    self.device_entry.insert(0, "0")
    self.units_combo = ctk.CTkComboBox(
      settings_row, values=["PSI / Fahrenheit", "kPa / Celsius"], width=140, height=28, **combo_colors()
    )
    self.units_combo.set("PSI / Fahrenheit")
    ctk.CTkButton(
      settings_row,
      text="IQ folder",
      width=80,
      height=28,
      font=ctk.CTkFont(size=11),
      fg_color=COLOR_BTN_SECONDARY,
      hover_color=COLOR_BTN_SECONDARY_HOVER,
      command=self._open_iq_folder,
    ).pack(side="left", padx=(8, 0))
    ctk.CTkButton(
      settings_row, text="Setup", width=70, height=28, font=ctk.CTkFont(size=11),
      fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_SECONDARY_HOVER, command=self._show_setup,
    ).pack(side="right")

    # Live KPI strip — pressure / temp / RSSI / estimated SDR↔sensor range.
    current = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
    current.pack(fill="x", pady=(0, 6))
    current_inner = ctk.CTkFrame(current, fg_color="transparent")
    current_inner.pack(fill="x", padx=10, pady=8)
    freq_row = ctk.CTkFrame(current_inner, fg_color="transparent")
    freq_row.pack(fill="x")
    self.freq_label = ctk.CTkLabel(
      freq_row, text=f"Band · {DEFAULT_PRESET}", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
    )
    self.freq_label.pack(side="left")
    self.freq_detail = ctk.CTkLabel(
      freq_row, text=FREQUENCY_PRESETS[DEFAULT_PRESET]["description"], font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
    )
    self.freq_detail.pack(side="left", padx=(10, 0))

    kpi = ctk.CTkFrame(current_inner, fg_color="transparent")
    kpi.pack(fill="x", pady=(8, 0))
    for i in range(4):
      kpi.grid_columnconfigure(i, weight=1, minsize=120)
    self.kpi_pressure = self._make_kpi(kpi, 0, "PRESSURE", "—", COLOR_HEADER_ACCENT)
    self.kpi_temp = self._make_kpi(kpi, 1, "TEMPERATURE", "—", COLOR_TEXT)
    self.kpi_rssi = self._make_kpi(kpi, 2, "RSSI", "—", COLOR_BLUE)
    self.kpi_range = self._make_kpi(kpi, 3, "SDR ↔ SENSOR", "—", COLOR_ORANGE)

    self.live_bar = LiveTelemetryBar(current_inner)
    self.live_bar.pack(fill="x", pady=(8, 0))

    stats_row = ctk.CTkFrame(stats_anchor, fg_color="transparent")
    stats_row.pack(fill="x", pady=(0, 4))
    for i in range(5):
      stats_row.grid_columnconfigure(i, weight=1, minsize=96)
    self.stat_sensors = StatCard(stats_row, "ROW MATCHES", "0", COLOR_BLUE, COLOR_BLUE_BG, compact=True)
    self.stat_sensors.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    self.stat_readings = StatCard(
      stats_row,
      "UNIQUE IDs",
      "0",
      COLOR_ORANGE,
      COLOR_ORANGE_BG,
      compact=True,
      on_click=self._show_unique_ids_window,
      hover_bg="#F0DCC8",
    )
    self.stat_readings.grid(row=0, column=1, sticky="ew", padx=4)
    self.stat_ok = StatCard(stats_row, "PASSED (OK)", "0", COLOR_GREEN, COLOR_GREEN_BG, compact=True)
    self.stat_ok.grid(row=0, column=2, sticky="ew", padx=4)
    self.stat_nok = StatCard(stats_row, "FAILED (NOK)", "0", COLOR_RED, COLOR_RED_BG, compact=True)
    self.stat_nok.grid(row=0, column=3, sticky="ew", padx=4)
    self.stat_rate = StatCard(stats_row, "PASS RATE", "0.0%", COLOR_HEADER_ACCENT, COLOR_CYAN_BG, compact=True)
    self.stat_rate.grid(row=0, column=4, sticky="ew", padx=(4, 0))

    prog_row = ctk.CTkFrame(stats_anchor, fg_color="transparent")
    prog_row.pack(fill="x")
    self.progress_label = ctk.CTkLabel(
      prog_row, text="Session: 0 readings  ·  Record IQ saves full-rate .cu8 (kept after stop for IQ / URH replay)",
      font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED,
    )
    self.progress_label.pack(side="left")
    self.progress = ctk.CTkProgressBar(stats_anchor, height=6, progress_color=COLOR_GREEN, fg_color=COLOR_BORDER)
    self.progress.pack(fill="x", pady=(2, 6))
    self.progress.set(0)

  def _flash_row(self, item_id: str, tag: str, step: int = 0) -> None:
    if not self.tree.exists(item_id):
      return
    # Keep flashes short — long animations stack up and freeze SDR under packet load.
    try:
      if step < 2:
        self.tree.item(item_id, tags=("flash",))
        self.after(50, lambda i=item_id, t=tag, s=step + 1: self._flash_row(i, t, s))
      else:
        self.tree.item(item_id, tags=(tag,))
    except tk.TclError:
      pass

  def _fit_tree_columns(self, _event=None) -> None:
    if not hasattr(self, "tree"):
      return
    try:
      width = int(self.tree.winfo_width())
    except tk.TclError:
      return
    if width < 80:
      return
    usable = max(200, width - 4)
    weights = getattr(self, "_tree_col_weights", None) or {}
    total_w = sum(weights.values()) or 1.0
    for col, weight in weights.items():
      self.tree.column(col, width=max(36, int(usable * (weight / total_w))))

  def _refresh_table_count(self) -> None:
    matches = len(self._row_matches)
    unique = len(self._sensors)
    if matches:
      self.table_count_label.configure(
        text=f"{matches} match{'es' if matches != 1 else ''}  ·  {unique} unique ID{'s' if unique != 1 else ''}"
      )
    else:
      self.table_count_label.configure(text=f"{unique} sensor{'s' if unique != 1 else ''}")

  def _sensor_counts(self) -> tuple[int, int]:
    # SDR OK/NOK only — never count Board-mirrored placeholders as passed.
    if self._row_matches:
      ok = sum(1 for row in self._row_matches if str(row.get("result") or "").upper() == "OK")
      nok = sum(1 for row in self._row_matches if str(row.get("result") or "").upper() == "NOK")
      return ok, nok
    ok = sum(
      1
      for reading in self._sensors.values()
      if self._is_rtl_decoder(reading.display_decoder) and reading.qualifies_ok()
    )
    nok = sum(
      1
      for reading in self._sensors.values()
      if self._is_rtl_decoder(reading.display_decoder) and not reading.qualifies_ok()
    )
    return ok, nok

  def _unique_rtl_ids(self) -> int:
    if self._row_matches:
      ids = {
        str(row.get("rtl_id") or row.get("sensor_id") or "").upper()
        for row in self._row_matches
        if self._is_rtl_decoder(row.get("decoder"))
      }
      return len({i for i in ids if i})
    return sum(1 for r in self._sensors.values() if self._is_rtl_decoder(r.display_decoder))

  def _update_stats(self):
    matches = len(self._row_matches)
    unique = self._unique_rtl_ids() if matches else len(self._sensors)
    ok, nok = self._sensor_counts()
    # ROW MATCHES = Board rows waiting on / resolved by rtl_433.
    self.stat_sensors.set_value(str(matches if matches else self._total_readings))
    self.stat_readings.set_value(str(unique))
    self.stat_ok.set_value(str(ok))
    self.stat_nok.set_value(str(nok))
    decided = ok + nok
    if decided > 0:
      rate = (ok / decided) * 100
      self.stat_rate.set_value(f"{rate:.1f}%")
      self.progress.set(ok / decided)
    else:
      self.stat_rate.set_value("0.0%")
      self.progress.set(0)
    if hasattr(self, "rf_charts"):
      self.rf_charts.set_counts(ok, nok)
    wait = matches - decided if matches else 0
    self.progress_label.configure(
      text=(
        f"Session: {matches if matches else self._total_readings} row match(es) · "
        f"{unique} rtl Sensor ID(s) · {self._total_readings} packet(s)"
        + (f" · {wait} waiting rtl_433" if wait else "")
        + " · OK only when rtl_433 library decoded"
      )
    )
    self._update_export_button()
    self._refresh_table_count()

  def _make_kpi(self, master, column: int, title: str, value: str, accent: str):
    card = ctk.CTkFrame(master, fg_color=COLOR_BG_PANEL, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
    card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0 if column == 3 else 4))
    ctk.CTkLabel(
      card, text=title, font=ctk.CTkFont(size=9, weight="bold"), text_color=COLOR_TEXT_DIM, anchor="w"
    ).pack(fill="x", padx=12, pady=(8, 0))
    label = ctk.CTkLabel(
      card, text=value, font=ctk.CTkFont(size=18, weight="bold"), text_color=accent, anchor="w"
    )
    label.pack(fill="x", padx=12, pady=(2, 10))
    return label

  def _update_kpis(self, reading: Optional[TelemetryReading] = None) -> None:
    if not hasattr(self, "kpi_pressure"):
      return
    if reading is None:
      self.kpi_pressure.configure(text="—")
      self.kpi_temp.configure(text="—")
      self.kpi_rssi.configure(text="—")
      self.kpi_range.configure(text="—")
      return
    self.kpi_pressure.configure(text=reading.display_pressure)
    self.kpi_temp.configure(text=reading.display_temp)
    rssi = reading.display_rssi
    self.kpi_rssi.configure(text=f"{rssi} dB" if rssi != "—" else "—")
    try:
      from range_radar import estimate_distance_m, format_distance

      dist = estimate_distance_m(reading.rssi_db, raw=reading.raw if isinstance(reading.raw, dict) else None)
      self.kpi_range.configure(text=format_distance(dist, dual=True) if dist is not None else "—")
    except Exception:
      self.kpi_range.configure(text="—")

  def _row_values(self, index: int, reading: TelemetryReading, reads: int) -> tuple:
    result = "OK" if reading.qualifies_ok() else "NOK"
    return (
      index,
      reading.display_decoder,
      reading.sensor_id or "na",
      result,
      reading.display_pressure,
      reading.display_pressure_bar,
      reading.display_temp,
      reading.display_battery,
      reading.display_rssi,
      reads,
      reading.timestamp.strftime("%H:%M:%S"),
      reading.nok_reason(),
    )

  def _update_export_button(self):
    state = "disabled" if getattr(self, "_exporting", False) else ("normal" if self._total_readings > 0 else "disabled")
    if hasattr(self, "export_btn"):
      self.export_btn.configure(state=state)
    if hasattr(self, "export_pdf_btn"):
      self.export_pdf_btn.configure(state=state)

  def _export_session(self, kind: str = "xlsx"):
    if getattr(self, "_exporting", False):
      return
    if not self.history:
      messagebox.showinfo(APP_NAME, "No SDR readings in this session to export.", parent=self._toplevel())
      return
    self.after(20, lambda: self._export_session_run(kind))

  def _export_session_run(self, kind: str):
    if getattr(self, "_exporting", False):
      return
    if not self.history:
      messagebox.showinfo(APP_NAME, "No SDR readings in this session to export.", parent=self._toplevel())
      return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if kind == "pdf":
      title = "Save SDR Receiver Report (PDF) — RTL-SDR telemetry, not TPMS board"
      default_name = f"SDR_Receiver_Report_{stamp}.pdf"
      filetypes = [("PDF — SDR Receiver Report", "*.pdf"), ("All files", "*.*")]
      ext = ".pdf"
    else:
      title = "Save SDR Receiver Report (Excel) — RTL-SDR telemetry, not TPMS board"
      default_name = f"SDR_Receiver_Report_{stamp}.xlsx"
      filetypes = [("Excel — SDR Receiver Report", "*.xlsx"), ("All files", "*.*")]
      ext = ".xlsx"

    path = ask_save_path(title, default_name, filetypes, ext, parent=self._toplevel())
    if not path:
      return

    readings = list(self.history)
    session_span = "—"
    if self._session_start:
      session_span = f"{max(0.0, (datetime.now() - self._session_start).total_seconds()):.0f}s"
    meta = {
      "Report type": "SDR Receiver (RTL-SDR / rtl_433) — not TPMS Board",
      "Frequency Band": self.preset_combo.get(),
      "Center Freq (MHz)": self.custom_freq.get(),
      "Total Readings": self._total_readings,
      "Exported Readings": len(readings),
      "Unique Sensors": len(self._sensors),
      "OK sensors": self._sensor_counts()[0],
      "NOK sensors": self._sensor_counts()[1],
      "rtl_433 Decoder column": "Protocol number + full library decoder name that decoded each packet",
      "OK/NOK rule": "Per detected sensor: ID + temperature + (pressure or battery), values merged across packets",
      "Time to reading": "Seconds from first packet for that Sensor ID until OK (or until last packet if still NOK)",
      "Session Start": self._session_start.strftime("%Y-%m-%d %H:%M:%S") if self._session_start else "—",
      "Session End": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "Session duration": session_span,
    }
    self._exporting = True
    self._update_export_button()
    label = "PDF" if kind == "pdf" else "Excel"
    self.footer_label.configure(text=f"Exporting SDR Receiver Report ({label})…")
    self._log(f"Exporting SDR Receiver Report ({label}, {len(readings)} readings) to {path}")

    def worker():
      try:
        if kind == "pdf":
          saved = export_session_pdf(readings, path, meta)
        else:
          saved = export_session_excel(readings, path, meta)
        self.after(0, lambda: self._export_finished(saved, None, kind))
      except Exception as exc:
        self.after(0, lambda e=exc: self._export_finished(None, e, kind))

    threading.Thread(target=worker, daemon=True, name="sdr-export").start()

  def _export_finished(self, saved: Optional[Path], error: Optional[Exception], kind: str = "xlsx"):
    self._exporting = False
    self._update_export_button()
    top = self._toplevel()
    if error is not None:
      self._log(f"ERROR: SDR export failed: {error}")
      self.footer_label.configure(text="SDR report export failed")
      messagebox.showerror(APP_NAME, f"SDR Receiver Report export failed:\n{error}", parent=top)
      return
    assert saved is not None
    kind_label = "PDF" if kind == "pdf" else "Excel"
    self._log(f"Exported SDR Receiver Report ({kind_label}) to {saved}")
    self.footer_label.configure(text=f"SDR Receiver Report exported: {saved.name}")
    messagebox.showinfo(
      APP_NAME,
      f"SDR Receiver Report ({kind_label}) saved.\n\nThis file is RTL-SDR telemetry, not a TPMS board report.\n\n{saved}",
      parent=top,
    )

  def _on_preset_change(self, choice: str):
    preset = FREQUENCY_PRESETS.get(choice, {})
    desc = preset.get("description", "")
    self.freq_label.configure(text=f"Frequency Band: {choice}")
    self.freq_detail.configure(text=desc)
    if preset.get("custom"):
      self.custom_freq.configure(state="normal")
    else:
      freqs = preset.get("frequencies", [])
      if freqs:
        mhz = freqs[0].replace("M", "")
        self.custom_freq.delete(0, "end")
        self.custom_freq.insert(0, mhz)
    if self._listening:
      self._log("Frequency changed — stop and restart listening to apply.")

  def _get_units(self) -> str:
    return "si" if "kPa" in self.units_combo.get() else "customary"

  def start_listen(self) -> None:
    """Public entry used by the combined Start Both control."""
    self._want_listening = True
    self._start_listen(auto=False)

  def restart_listen(self) -> None:
    """Stop then start so a replugged RTL-SDR is reopened cleanly."""
    self._want_listening = True
    self._sdr_paused = False
    self._manual_restarting = True
    self._listen_grace_until = time.monotonic() + 28.0
    self._cancel_auto_restart()
    if self._listening or self.runner.is_running:
      try:
        self.runner.stop()
      except Exception:
        pass
      self._log("Reclaiming RTL-SDR…")
      try:
        from tpms_bench.rtl433 import free_dongle
        free_dongle()
      except Exception:
        pass
      self.after(1200, self._finish_manual_restart)
      return
    try:
      from tpms_bench.rtl433 import free_dongle
      free_dongle()
    except Exception:
      pass
    self.after(400, self._finish_manual_restart)

  def _finish_manual_restart(self) -> None:
    self._manual_restarting = False
    if self._want_listening and not self._sdr_paused:
      self._start_listen(auto=True)

  def _cancel_auto_restart(self) -> None:
    self._restart_scheduled = False

  def _rtl433_subprocess_alive(self) -> bool:
    proc = getattr(self.runner, "_process", None)
    if proc is None:
      return False
    try:
      return proc.poll() is None
    except Exception:
      return False

  def _listen_alive(self) -> bool:
    """True when rtl_433 is up — UI flags can lag a Tk tick behind the runner."""
    if self._rtl433_subprocess_alive():
      return True
    return bool(self._listening and self.runner.is_running)

  def _schedule_auto_restart(self, reason: str) -> None:
    if not self._want_listening or self._sdr_paused or self._manual_restarting or self._starting:
      return
    if time.monotonic() < self._listen_grace_until:
      return
    if self._listen_alive():
      return
    if self._restart_scheduled:
      return
    # Never permanently give up — just slow down after many drops.
    self._restart_scheduled = True
    self._auto_restarts += 1
    if self._auto_restarts <= 8:
      delay_ms = min(4000, 400 + (self._auto_restarts - 1) * 400)
    else:
      delay_ms = 8000
    self._log(f"SDR reconnecting ({self._auto_restarts})… {reason}")
    self.footer_label.configure(text=f"SDR reconnecting ({self._auto_restarts})…")
    self.after(delay_ms, self._do_auto_restart)

  def _do_auto_restart(self) -> None:
    self._restart_scheduled = False
    if not self._want_listening or self._sdr_paused or self._manual_restarting:
      return
    if self._listening or self.runner.is_running or self._starting:
      return
    self._start_listen(auto=True)

  def _keepalive_tick(self) -> None:
    """Keep rtl_433 alive for the whole session once the operator pressed Start."""
    try:
      if not self.winfo_exists():
        return
    except Exception:
      return
    try:
      if self._want_listening and not self._sdr_paused and not self._manual_restarting and not self._starting:
        if time.monotonic() < self._listen_grace_until:
          pass
        elif not self._listen_alive():
          self._schedule_auto_restart("listener idle — keeping session smooth")
    except Exception:
      pass
    try:
      self.after(3000, self._keepalive_tick)
    except Exception:
      pass

  def _start_listen(self, auto: bool = False):
    if self._listening or self.runner.is_running or self._starting:
      return
    self._starting = True
    self._want_listening = True
    try:
      self._start_listen_body(auto=auto)
    finally:
      self._starting = False

  def _start_listen_body(self, auto: bool = False):
    preset = self.preset_combo.get()
    custom_mhz = None
    if FREQUENCY_PRESETS.get(preset, {}).get("custom"):
      try:
        custom_mhz = float(self.custom_freq.get().strip())
      except ValueError:
        self._log("Invalid center frequency — enter a number in MHz.")
        if not auto:
          self._want_listening = False
        return
    else:
      try:
        custom_mhz = float(self.custom_freq.get().strip())
      except ValueError:
        custom_mhz = None

    try:
      ppm = int(self.ppm_entry.get().strip() or "0")
      device = int(self.device_entry.get().strip() or "0")
    except ValueError:
      self._log("Invalid PPM offset or device index.")
      if not auto:
        self._want_listening = False
      return

    # Honor the UI switch (do not force TPMS-only on).
    self.runner.tpms_only = bool(self.tpms_only_switch.get() == 1)
    if not get_rtl433_exe().is_file():
      self._log("rtl_433 decoder missing — installing…")
      installed = SetupManager(on_progress=lambda msg, _pct: self._log(msg)).run_full_setup()
      if not installed or not get_rtl433_exe().is_file():
        self._log("ERROR: rtl_433 could not be installed. Open Driver Setup.")
        if not auto:
          messagebox.showerror(APP_NAME, "rtl_433 decoder is missing and could not be installed.\n\nOpen Driver Setup and try again.", parent=self._toplevel())
          self._want_listening = False
        return
    self._sdr_paused = False
    record_iq = self.record_iq_switch.get() == 1
    # Only reclaim dongle aggressively on manual start — auto-reconnect lets Rtl433Runner start cleanly.
    if not auto:
      try:
        from tpms_bench.rtl433 import free_dongle
        free_dongle()
        time.sleep(0.8)
      except Exception:
        pass
    if not self._want_listening:
      return
    ok = self.runner.start(
      preset_name=preset,
      custom_freq_mhz=custom_mhz,
      gain=self.gain_combo.get(),
      ppm=ppm,
      device_index=device,
      units=self._get_units(),
      record_iq=record_iq,
    )
    if ok:
      self._start_retried = False
      self._auto_restarts = 0
      self._listen_grace_until = time.monotonic() + 22.0
      self._listening = True
      if self._session_start is None:
        self._session_start = datetime.now()
      self._update_export_button()
      iq_note = " · IQ recording (full rate, kept)" if record_iq else ""
      self.footer_label.configure(text=f"Listening on {preset}{iq_note}…")
      self.after(18000, self._sdr_quiet_watchdog)
    else:
      self.footer_label.configure(text="SDR reconnecting — dongle busy or not ready")
      if hasattr(self, "activity_terminal") and not auto:
        self.activity_terminal.expand()
      if not auto and not getattr(self, "_start_fail_dialog_open", False):
        self._start_fail_dialog_open = True
        try:
          messagebox.showerror(
            APP_NAME,
            "SDR could not start rtl_433.\n\n"
            "Close any other TPMS Suite / SDR window, unplug/replug the RTL-SDR, then press START again.",
            parent=self._toplevel(),
          )
        finally:
          self._start_fail_dialog_open = False
      if self._want_listening:
        # One reclaim before the next auto attempt.
        try:
          from tpms_bench.rtl433 import free_dongle
          free_dongle()
        except Exception:
          pass
        self._schedule_auto_restart("start failed — retrying")

  def _pause_listen(self):
    if self._listening:
      self._want_listening = False
      self._cancel_auto_restart()
      self._sdr_paused = True
      self.runner.stop()
      self._log("SDR listening paused — session data is kept.")
      return
    if self._sdr_paused:
      self._want_listening = True
      self._start_listen(auto=False)

  def _stop_listen(self):
    self._want_listening = False
    self._sdr_paused = False
    self._cancel_auto_restart()
    self._auto_restarts = 0
    if self._listening or self.runner.is_running:
      self.runner.stop()
    else:
      self._set_status(False)
  def _on_reading(self, reading: TelemetryReading):
    # rtl_433 thread — only queue. Keep lock hold tiny so RSSI never stalls here.
    self._pending_lock.acquire()
    try:
      self._pending_readings.append(reading)
    finally:
      self._pending_lock.release()

  def _flush_readings_tick(self) -> None:
    self._flush_readings()
    try:
      self.after(self._UI_FLUSH_MS, self._flush_readings_tick)
    except Exception:
      pass

  def _flush_readings(self) -> None:
    self._pending_lock.acquire()
    try:
      if not self._pending_readings:
        self._flush_scheduled = False
        return
      n = min(len(self._pending_readings), self._FLUSH_BATCH_MAX)
      batch = [self._pending_readings.popleft() for _ in range(n)]
      self._flush_scheduled = bool(self._pending_readings)
    finally:
      self._pending_lock.release()
    if not batch:
      return

    touched: Dict[str, TelemetryReading] = {}
    footer_sid: Optional[str] = None
    new_ids: list[str] = []
    skipped_no_id = 0
    now = time.monotonic()
    scan_matches = (now - self._last_match_scan_ts) * 1000.0 >= 250.0

    for reading in batch:
      self.history.appendleft(reading)
      self._total_readings += 1
      self._latest = reading
      if not reading.has_sensor_id():
        skipped_no_id += 1
        continue
      sid = reading.sensor_id
      first_seen = self._sensor_first_seen.setdefault(sid, reading.timestamp)
      elapsed = max(0.0, (reading.timestamp - first_seen).total_seconds())
      is_new = sid not in self._sensors
      if is_new:
        merged = reading
        merged.acquire_seconds = elapsed
        self._sensors[sid] = merged
        self._sensor_reads[sid] = 1
        new_ids.append(sid)
      else:
        previous = self._sensors[sid]
        already_ok = previous.qualifies_ok()
        frozen = previous.acquire_seconds if already_ok else None
        merged = previous.merged_with(reading)
        if already_ok:
          merged.acquire_seconds = frozen
        else:
          merged.acquire_seconds = elapsed
        self._sensors[sid] = merged
        self._sensor_reads[sid] = self._sensor_reads.get(sid, 1) + 1
      touched[sid] = merged
      footer_sid = sid
      if scan_matches:
        self._apply_rtl_decoder_to_matches(sid, merged)

    if scan_matches:
      self._last_match_scan_ts = now
    range_pkt = self._packet_for_range(batch)
    if range_pkt is not None:
      self._emit_live_range(range_pkt)
    if self._latest is not None and (now - self._last_live_bar_ts) * 1000.0 >= self._LIVE_BAR_MIN_MS:
      self.live_bar.update_reading(self._latest)
      self._update_kpis(range_pkt or self._latest)
      if hasattr(self, "rf_charts") and (now - self._last_rf_charts_ts) * 1000.0 >= self._RF_CHARTS_MIN_MS:
        try:
          src = range_pkt or self._latest
          snr = None
          raw = src.raw if isinstance(src.raw, dict) else None
          if raw and raw.get("snr") not in (None, ""):
            try:
              snr = float(raw["snr"])
            except (TypeError, ValueError):
              snr = None
          self.rf_charts.push(
            rssi=src.rssi_db,
            snr=snr,
            sensor_id=src.sensor_id if src.has_sensor_id() else None,
            result="OK" if src.qualifies_ok() else None,
          )
          self._last_rf_charts_ts = now
        except Exception:
          pass
      self._last_live_bar_ts = now

    for sid, merged in touched.items():
      reads = self._sensor_reads.get(sid, 1)
      result = "OK" if merged.qualifies_ok() else "NOK"
      # While Board is feeding per-row matches, keep the table as one line per Board row.
      if self._row_matches:
        if reads == 1 or reads % 50 == 0:
          self._log(
            f"{merged.display_decoder} | ID {sid} | {result} | "
            f"{merged.display_pressure} | {merged.display_temp} | {reads} reads"
          )
        continue
      item = self._sensor_items.get(sid)
      if sid in new_ids or not item or not self.tree.exists(item):
        index = list(self._sensors.keys()).index(sid) + 1
        item = self.tree.insert("", 0, values=self._row_values(index, merged, reads), tags=(result,))
        self._sensor_items[sid] = item
        if sid in new_ids:
          self.tree.see(item)
      else:
        try:
          index = int(self.tree.set(item, "num"))
        except (TypeError, ValueError):
          index = list(self._sensors.keys()).index(sid) + 1
        self.tree.item(
          item,
          values=self._row_values(index, merged, reads),
          tags=(result,),
        )
      if reads == 1 or reads % 50 == 0:
        self._log(
          f"{merged.display_decoder} | ID {sid} | {result} | "
          f"{merged.display_pressure} | {merged.display_temp} | {reads} reads"
        )

    if skipped_no_id and skipped_no_id == len(batch):
      self._log(f"{skipped_no_id} packet(s) with no sensor ID skipped for OK/NOK")

    self._refresh_table_count()
    self._update_stats()
    self._autosave_dirty = True
    if footer_sid and footer_sid in self._sensors:
      merged = self._sensors[footer_sid]
      reads = self._sensor_reads.get(footer_sid, 1)
      result = "OK" if merged.qualifies_ok() else "NOK"
      self.footer_label.configure(
        text=(
          f"Sensor {footer_sid}: {result}  ·  {merged.display_decoder}  ·  "
          f"{merged.display_pressure}  ·  {reads} read(s)  ·  +{len(batch)} pkt"
        )
      )

    if self._flush_scheduled:
      self.after(0 if len(batch) >= self._FLUSH_BATCH_MAX else self._UI_FLUSH_MS, self._flush_readings)

  def _on_log(self, message: str):
    self.after(0, lambda m=message: self._log(m))

  def _on_state_change(self, running: bool):
    self.after(0, lambda r=running: self._set_status(r))

  def _set_status(self, running: bool):
    self._listening = running
    if running:
      self._sdr_paused = False
      self._auto_restarts = 0
      self.running_badge.configure(text="● RUNNING", text_color=COLOR_GREEN)
      self.start_btn.configure(state="disabled")
      self.pause_btn.configure(state="normal", text="PAUSE")
      self.stop_btn.configure(state="normal")
    elif self._sdr_paused:
      self.running_badge.configure(text="● PAUSED", text_color=COLOR_ORANGE)
      self.start_btn.configure(state="disabled")
      self.pause_btn.configure(state="normal", text="RESUME")
      self.stop_btn.configure(state="normal")
      self.footer_label.configure(text="Paused — press RESUME to keep listening or STOP to end")
    elif self._want_listening and not self._manual_restarting:
      # Operator still wants RF — show reconnecting instead of hard STOPPED.
      self.running_badge.configure(text="● RECONNECTING", text_color=COLOR_ORANGE)
      self.start_btn.configure(state="disabled")
      self.pause_btn.configure(state="disabled", text="PAUSE")
      self.stop_btn.configure(state="normal")
      self._schedule_auto_restart("rtl_433 exited")
    else:
      self.running_badge.configure(text="● STOPPED", text_color=COLOR_RED)
      self.start_btn.configure(state="normal")
      self.pause_btn.configure(state="disabled", text="PAUSE")
      self.stop_btn.configure(state="disabled")
      if self._total_readings > 0:
        self.footer_label.configure(
          text=f"Stopped — {self._total_readings} SDR readings captured. Export from the top bar."
        )
      else:
        self.footer_label.configure(text="Stopped — press START to resume")
    self._update_export_button()
    self._notify_status()

  def _notify_status(self):
    if self._listening:
      label = "RUNNING"
    elif self._sdr_paused:
      label = "PAUSED"
    elif self._want_listening:
      label = "RECONNECTING"
    else:
      label = "STOPPED"
    try:
      self.on_status_change(self._listening or self._sdr_paused or self._want_listening, label)
    except Exception:
      pass

  def is_running(self) -> bool:
    return self._listening or self._sdr_paused or self._want_listening

  def _sdr_quiet_watchdog(self) -> None:
    if not self._want_listening or self._sdr_paused:
      return
    # Only count real rtl_433 library packets, not Board WAIT placeholders.
    rtl_packets = sum(
      1 for r in self._sensors.values() if self._is_rtl_decoder(r.display_decoder)
    )
    if not self._listen_alive():
      if time.monotonic() >= self._listen_grace_until:
        self._schedule_auto_restart("quiet watchdog — not listening")
      return
    if rtl_packets == 0 and self._total_readings == 0 and not getattr(self, "_quiet_restarted", False):
      self._quiet_restarted = True
      self._log(
        "SDR quiet after open — soft-restarting rtl_433 once (common after dongle replug)…"
      )
      self.restart_listen()
      return
    if rtl_packets == 0 and self._total_readings == 0:
      self._log(
        "SDR is open and listening — no JSON packets yet. "
        "R82xx PLL messages are ignored. Trigger a sensor or wait for a live ID."
      )

  def _log(self, message: str, level: str = "info"):
    if message.startswith("ERROR") or "Failed" in message:
      level = "error"
    elif message.startswith("Starting:"):
      level = "cmd"
    elif message.startswith("RAW ") or message.startswith("SKIP "):
      level = "rx" if message.startswith("RAW") else "dim"
    elif "| ID " in message:
      level = "rx"
      self._log_rx_count += 1
      if self._log_rx_count > 12 and self._log_rx_count % 40 != 0:
        return

    if hasattr(self, "activity_terminal"):
      self.activity_terminal.write(message, level=level)

  def get_sensor_snapshot(self) -> Dict[str, Any]:
    """Merged per-sensor readings for comparative OK/NOK analysis."""
    # Shallow copy — safe for Board/Range threads without holding UI locks.
    return {k: v for k, v in self._sensors.items()}

  def _is_rtl_decoder(self, label: str | None) -> bool:
    """True only for stock rtl_433 library labels like '[60] Schrader' — not flex guesses."""
    text = str(label or "").strip()
    low = text.lower()
    if not text or text in {"—", "-", "na", "TPMS", "tpms"}:
      return False
    if low.startswith("board rf") or "waiting for" in low:
      return False
    if low.startswith("[flex]"):
      return False
    # Real library: "[252] BMW Gen4-Gen5 TPMS…"
    if not (text.startswith("[") and "]" in text):
      return False
    proto = text[1 : text.index("]")].strip()
    return proto.isdigit()

  def _rtl_decoder_for(self, sensor_id: str) -> str:
    """Best rtl_433 library decoder for this Sensor ID (exact or bit-shifted family)."""
    from tpms_bench.compare import ids_related

    sid = str(sensor_id or "").strip()
    # Prefer exact ID first.
    reading = self._sensors.get(sid)
    if reading is not None and self._is_rtl_decoder(reading.display_decoder):
      return reading.display_decoder
    # rtl_433 often reports a bit-shifted ID for the same RF burst.
    best = None
    best_score = -1
    for other_id, other in self._sensors.items():
      if not self._is_rtl_decoder(other.display_decoder):
        continue
      if not ids_related(sid, other_id):
        continue
      label = other.display_decoder
      score = self._sensor_reads.get(other_id, 1)
      # Prefer OEM-looking library names for this sensor family.
      low = label.lower()
      if "abarth" in low:
        score += 1000
      elif "schrader" in low:
        score += 800
      elif "continental" in low or "huf" in low or "beru" in low:
        score += 700
      elif "bmw" in low:
        score += 400
      if score > best_score:
        best_score = score
        best = label
    if best:
      return best
    for match in reversed(self._row_matches):
      if not ids_related(sid, str(match.get("sensor_id") or "")):
        continue
      label = str(match.get("decoder") or "")
      if self._is_rtl_decoder(label):
        return label
    # Recent live history (even if not yet merged into _sensors uniquely).
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(seconds=12)
    for reading in list(self.history)[:80]:
      if reading.timestamp < cutoff:
        continue
      if not self._is_rtl_decoder(reading.display_decoder):
        continue
      if ids_related(sid, reading.sensor_id):
        return reading.display_decoder
    return "rtl_433 · waiting for decode"

  def _apply_rtl_decoder_to_matches(self, sensor_id: str, reading: TelemetryReading) -> None:
    """Stamp a stock rtl_433 library decode with actual telemetry onto Board match rows."""
    from tpms_bench.compare import ids_related

    if not self._is_rtl_decoder(reading.display_decoder):
      return
    if not reading.qualifies_ok():
      # Have a library name but incomplete fields — do not mark OK / invent values.
      return
    sid = str(sensor_id or "").strip()
    label = reading.display_decoder
    updated = 0
    for match in self._row_matches:
      if str(match.get("result") or "").upper() == "OK" and self._is_rtl_decoder(match.get("decoder")):
        if match.get("rtl_id") == sid:
          continue
      board_sid = str(match.get("board_sensor_id") or match.get("sensor_id") or "")
      if board_sid and sid and board_sid != sid and not ids_related(board_sid, sid):
        continue
      prev = str(match.get("result") or "").upper()
      if prev == "OK" and self._is_rtl_decoder(match.get("decoder")):
        continue
      match["decoder"] = label
      match["rtl_id"] = sid
      match["sensor_id"] = sid
      match["result"] = "OK"
      match["reading"] = reading
      match["temperature"] = reading.temperature_c
      match["pressure"] = reading.pressure_psi
      match["voltage"] = reading.battery_voltage_v
      match["rssi"] = reading.rssi_db
      item = match.get("tree_item")
      if item and self.tree.exists(item):
        vals = list(self.tree.item(item, "values"))
        while len(vals) < 12:
          vals.append("")
        vals[1] = label
        vals[2] = sid
        vals[3] = "OK"
        vals[4] = reading.display_pressure
        vals[5] = reading.display_pressure_bar
        vals[6] = reading.display_temp
        vals[7] = reading.display_battery
        vals[8] = reading.display_rssi
        note = str(vals[11] or "")
        note = note.replace(" · waiting for rtl_433", "").replace(" · SDR FAIL — no rtl_433 decoder", "")
        note = note.replace("SDR FAIL: no rtl_433 library decoder for this Board trigger", "")
        note = note.replace("SDR FAIL: no actual rtl_433 library reading (temp+pressure/battery)", "")
        if board_sid and board_sid.upper() != sid.upper():
          if f"board ID {board_sid}" not in note:
            note = f"{note} · board ID {board_sid}".strip(" ·")
        vals[11] = note.strip(" ·")
        self.tree.item(item, values=tuple(vals), tags=("OK",))
        updated += 1
    if updated:
      self._log(f"rtl_433 {label} → {updated} SDR match(es) OK (ID {sid})")
      self._update_stats()

  def _apply_board_battery(self, reading: TelemetryReading, *, voltage: str | float | None) -> None:
    """Copy Board battery voltage onto an rtl_433 reading when RF omitted it."""
    if voltage is None or voltage == "" or str(voltage).lower() in {"na", "n/a", "none", "-"}:
      return
    try:
      volts = float(str(voltage).strip().replace("V", "").replace("v", ""))
    except (TypeError, ValueError):
      return
    if volts <= 0 or volts > 6:
      return
    reading.battery_voltage_v = volts
    reading.battery_ok = volts >= 2.5

  def _softfill_board_battery(self, sensor_id: str, *, voltage: str | float | None) -> None:
    """Apply Board volts to matching SDR sensors (exact or bit-shifted ID family)."""
    if voltage is None or voltage == "":
      return
    from tpms_bench.compare import ids_related

    sid = str(sensor_id or "").strip()
    for other_id, other in self._sensors.items():
      if other_id == sid or ids_related(sid, other_id):
        self._apply_board_battery(other, voltage=voltage)
        # Refresh tree row if present.
        item = self._sensor_items.get(other_id)
        if item and self.tree.exists(item):
          try:
            index = int(self.tree.set(item, "num"))
          except (TypeError, ValueError):
            index = 1
          reads = self._sensor_reads.get(other_id, 1)
          result = "OK" if other.qualifies_ok() else "NOK"
          self.tree.item(item, values=self._row_values(index, other, reads), tags=(result,))

  def watch_board_burst(
    self,
    sensor_id: str = "",
    *,
    excel_row: int | None = None,
    vehicle: str = "",
    **_kwargs,
  ) -> None:
    """Board just sent ABC — track the next live rtl_433 RSSI for range."""
    sid = str(sensor_id or "").strip().upper()
    if sid in {"", "NA", "N/A", "NONE", "-", "—"}:
      sid = ""
    self._range_focus_id = sid
    self._range_watch_until = time.monotonic() + 16.0
    bit = f"ID {sid}" if sid else "next RF packet"
    row = f"row {excel_row}" if excel_row else "Board trigger"
    extra = f" · {vehicle}" if vehicle else ""
    self._log(f"Range watch · {row}{extra} · {bit}")

  def _packet_for_range(self, batch: list) -> Optional[TelemetryReading]:
    """Newest packet this flush — prefer the Board-focused sensor ID."""
    focus = str(getattr(self, "_range_focus_id", "") or "").upper()
    watching = time.monotonic() < float(getattr(self, "_range_watch_until", 0) or 0)
    related = None
    if focus and watching:
      try:
        from tpms_bench.compare import ids_related
        related = ids_related
      except Exception:
        related = None
      for reading in reversed(batch):
        if not getattr(reading, "has_sensor_id", lambda: False)():
          continue
        sid = str(reading.sensor_id or "").upper()
        match = sid == focus or (related is not None and related(focus, sid))
        if match and (reading.rssi_db is not None or isinstance(reading.raw, dict)):
          return reading
    for reading in reversed(batch):
      if reading.rssi_db is not None:
        return reading
      raw = reading.raw if isinstance(getattr(reading, "raw", None), dict) else None
      if raw and (raw.get("rssi") not in (None, "") or raw.get("snr") not in (None, "")):
        return reading
    return self._latest

  def _emit_live_range(self, reading: TelemetryReading) -> None:
    """Push this packet's RSSI/SNR into Range Radar (every flush, not throttled)."""
    if not self.on_range_update or reading is None:
      return
    raw = reading.raw if isinstance(reading.raw, dict) else None
    rssi = reading.rssi_db
    if rssi is None and raw:
      try:
        from range_radar import coerce_rssi_dbm

        rssi = coerce_rssi_dbm(None, raw=raw)
      except Exception:
        rssi = None
    if rssi is None:
      return
    try:
      self.on_range_update(
        rssi_dbm=rssi,
        sensor_id=reading.sensor_id or "",
        raw=raw,
      )
    except TypeError:
      try:
        self.on_range_update(rssi_dbm=rssi, sensor_id=reading.sensor_id or "")
      except Exception:
        pass
    except Exception:
      pass

  def ingest_board_reading(
    self,
    sensor_id: str,
    *,
    excel_row: int | None = None,
    vehicle: str = "",
    temperature: str | float | None = None,
    voltage: str | float | None = None,
    pressure: str | float | None = None,
    board_result: str = "OK",
  ) -> None:
    """Open an SDR match slot for this Board row — values come only from rtl_433."""
    self.watch_board_burst(sensor_id, excel_row=excel_row, vehicle=vehicle)
    sid = str(sensor_id or "").strip()
    if not sid or sid.lower() in {"na", "n/a", "none", "-", "—"}:
      return

    row_no = int(excel_row or 0)
    note = f"Board row {row_no}" if row_no else "SDR match"
    if vehicle:
      note = f"{note} · {vehicle}"

    # If rtl_433 already decoded a related ID, resolve immediately with SDR data only.
    known = self._rtl_decoder_for(sid)
    rtl_reading = None
    if self._is_rtl_decoder(known):
      from tpms_bench.compare import ids_related
      for other_id, other in self._sensors.items():
        if self._is_rtl_decoder(other.display_decoder) and (
          other_id == sid or ids_related(sid, other_id)
        ):
          rtl_reading = other
          break

    if rtl_reading is not None:
      decoder = rtl_reading.display_decoder
      result = "OK"
      show_id = rtl_reading.sensor_id or sid
      # Soft-fill Board battery volts onto the rtl_433 sensor — Schrader RF has no volts.
      self._apply_board_battery(rtl_reading, voltage=voltage)
      pressure_s = rtl_reading.display_pressure
      pressure_bar_s = rtl_reading.display_pressure_bar
      temp_s = rtl_reading.display_temp
      batt_s = rtl_reading.display_battery
      rssi_s = rtl_reading.display_rssi
      note = note  # no waiting
    else:
      decoder = "rtl_433 · waiting for decode"
      result = "WAIT"
      show_id = "—"  # do not show Board ID as an SDR decode
      pressure_s = "—"
      pressure_bar_s = "—"
      temp_s = "—"
      batt_s = "—"
      rssi_s = "—"
      note = f"{note} · waiting for rtl_433"

    # Soft-fill battery onto any related SDR sensor IDs even when WAIT slot is shown.
    self._softfill_board_battery(sid, voltage=voltage)

    if not self._row_matches and self._sensor_items:
      for item in list(self._sensor_items.values()):
        try:
          if self.tree.exists(item):
            self.tree.delete(item)
        except tk.TclError:
          pass
      self._sensor_items.clear()

    def _write_tree(item, index: int) -> None:
      self.tree.item(
        item,
        values=(
          index,
          decoder,
          show_id,
          result,
          pressure_s,
          pressure_bar_s,
          temp_s,
          batt_s,
          rssi_s,
          index,
          datetime.now().strftime("%H:%M:%S"),
          note,
        ),
        tags=(result,),
      )

    if row_no:
      for existing_match in self._row_matches:
        if int(existing_match.get("excel_row") or 0) != row_no:
          continue
        # Never overwrite a settled rtl OK with a Board WAIT.
        if str(existing_match.get("result") or "").upper() == "OK" and self._is_rtl_decoder(
          existing_match.get("decoder")
        ):
          return
        existing_match["board_sensor_id"] = sid
        existing_match["board_result"] = str(board_result or "")
        existing_match["sensor_id"] = show_id if result == "OK" else sid
        existing_match["result"] = result
        existing_match["decoder"] = decoder
        if rtl_reading is not None:
          existing_match["rtl_id"] = rtl_reading.sensor_id
          existing_match["reading"] = rtl_reading
        item = existing_match.get("tree_item")
        if item and self.tree.exists(item):
          try:
            index = int(self.tree.set(item, "num"))
          except (TypeError, ValueError):
            index = self._row_matches.index(existing_match) + 1
          _write_tree(item, index)
        self._update_stats()
        return

    index = len(self._row_matches) + 1
    item = self.tree.insert("", 0, values=("",) * 12, tags=(result,))
    _write_tree(item, index)
    match = {
      "excel_row": row_no,
      "vehicle": (vehicle or "").strip() or "—",
      "board_sensor_id": sid,
      "board_result": str(board_result or ""),
      "sensor_id": show_id if result == "OK" else sid,
      "rtl_id": (rtl_reading.sensor_id if rtl_reading is not None else ""),
      "result": result,
      "decoder": decoder,
      "reading": rtl_reading,
      "tree_item": item,
    }
    self._row_matches.append(match)
    self.tree.see(item)
    self._log(
      f"MATCH #{index} | {decoder} | Board row {row_no or '—'} | "
      f"board ID {sid} | SDR {result}"
    )
    self._autosave_dirty = True
    self._refresh_table_count()
    self._update_stats()

  def finalize_board_match(
    self,
    *,
    excel_row: int | None = None,
    sensor_id: str | None = None,
    decoder: str | None = None,
    sdr_compare: str | None = None,
    sdr_reason: str | None = None,
  ) -> None:
    """End of SDR wait: OK only with actual rtl_433 library telemetry; else NOK."""
    from tpms_bench.compare import ids_related

    row_no = int(excel_row or 0)
    sid = str(sensor_id or "").strip()
    label = str(decoder or "").strip()
    reason = str(sdr_reason or "").strip()
    cmp = str(sdr_compare or "").strip().upper()

    # Only SUCCESS with a numbered library decoder + a live reading that qualifies_ok.
    reading = None
    if self._is_rtl_decoder(label) and cmp == "SUCCESS":
      for other_id, other in self._sensors.items():
        if not self._is_rtl_decoder(other.display_decoder):
          continue
        if not other.qualifies_ok():
          continue
        if (not sid) or other_id == sid or ids_related(sid, other_id):
          reading = other
          break
      if reading is not None:
        self._apply_rtl_decoder_to_matches(sid or reading.sensor_id, reading)
        self._log(f"SDR OK row {row_no or '—'} · {reading.display_decoder}")
        self._update_stats()
        return

    # No actual library reading → SDR NOK (Board may still be OK on its tab).
    for match in self._row_matches:
      if row_no and int(match.get("excel_row") or 0) != row_no:
        continue
      board_sid = str(match.get("board_sensor_id") or match.get("sensor_id") or "")
      if sid and board_sid and board_sid.upper() != sid.upper() and not ids_related(sid, board_sid):
        continue
      if (
        str(match.get("result") or "").upper() == "OK"
        and self._is_rtl_decoder(match.get("decoder"))
      ):
        # Keep a prior real OK if somehow already stamped.
        continue
      item = match.get("tree_item")
      if not item or not self.tree.exists(item):
        continue
      vals = list(self.tree.item(item, "values"))
      while len(vals) < 12:
        vals.append("")
      vals[1] = "rtl_433 · no decode"
      vals[2] = "—"
      vals[3] = "NOK"
      vals[4] = "—"
      vals[5] = "—"
      vals[6] = "—"
      vals[7] = "—"
      vals[8] = "—"
      note = str(vals[11] or "").replace(" · waiting for rtl_433", "")
      fail_bit = reason or "SDR FAIL — no actual rtl_433 library reading"
      if "SDR FAIL" not in note:
        note = f"{note} · {fail_bit}".strip(" ·")
      vals[11] = note
      self.tree.item(item, values=tuple(vals), tags=("NOK",))
      match["decoder"] = vals[1]
      match["result"] = "NOK"
      match["sensor_id"] = board_sid
      self._log(f"SDR NOK row {row_no or '—'} · no actual library reading · next ABC")
    self._update_stats()

  def _show_unique_ids_window(self) -> None:
    """Popup listing every unique Sensor ID heard so far in this SDR session."""
    existing = getattr(self, "_unique_ids_win", None)
    if existing is not None:
      try:
        if existing.winfo_exists():
          existing.lift()
          existing.focus_force()
          self._refresh_unique_ids_window(existing)
          return
      except tk.TclError:
        pass

    win = ctk.CTkToplevel(self)
    win.title("Unique Sensor IDs")
    win.geometry("820x480")
    win.minsize(640, 360)
    try:
      win.transient(self.winfo_toplevel())
    except tk.TclError:
      pass
    self._unique_ids_win = win

    header = ctk.CTkFrame(win, fg_color="transparent")
    header.pack(fill="x", padx=12, pady=(12, 6))
    self._unique_ids_title = ctk.CTkLabel(
      header,
      text="Unique IDs",
      font=ctk.CTkFont(size=14, weight="bold"),
      text_color=COLOR_TEXT,
      anchor="w",
    )
    self._unique_ids_title.pack(side="left")
    ctk.CTkButton(
      header,
      text="Refresh",
      width=90,
      height=28,
      fg_color=COLOR_BTN_SECONDARY,
      hover_color=COLOR_BTN_SECONDARY_HOVER,
      command=lambda: self._refresh_unique_ids_window(win),
    ).pack(side="right")

    cols = ("num", "id", "decoder", "pressure", "bar", "temp", "battery", "rssi", "reads", "result")
    host = tk.Frame(win, bg=COLOR_BG)
    host.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    tree = ttk.Treeview(host, columns=cols, show="headings", style="Combined.Treeview")
    headings = {
      "num": "#",
      "id": "Sensor ID",
      "decoder": "rtl_433 Decoder",
      "pressure": "PSI",
      "bar": "bar",
      "temp": "°C",
      "battery": "Batt",
      "rssi": "RSSI",
      "reads": "Reads",
      "result": "Result",
    }
    widths = {
      "num": 40, "id": 110, "decoder": 200, "pressure": 70, "bar": 70,
      "temp": 55, "battery": 70, "rssi": 60, "reads": 55, "result": 60,
    }
    for col in cols:
      tree.heading(col, text=headings[col])
      tree.column(col, width=widths[col], anchor="center" if col != "decoder" else "w")
    scroll = ttk.Scrollbar(host, orient="vertical", command=tree.yview, style="Combined.Vertical.TScrollbar")
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    tree.tag_configure("OK", background=COLOR_GREEN_BG, foreground="#047857")
    tree.tag_configure("NOK", background=COLOR_RED_BG, foreground="#B91C1C")
    win._unique_tree = tree  # type: ignore[attr-defined]
    self._refresh_unique_ids_window(win)

  def _refresh_unique_ids_window(self, win) -> None:
    tree = getattr(win, "_unique_tree", None)
    title = getattr(self, "_unique_ids_title", None)
    if tree is None:
      return
    for item in tree.get_children():
      tree.delete(item)
    sensors = sorted(self._sensors.items(), key=lambda kv: kv[0])
    if title is not None:
      title.configure(text=f"Unique IDs — {len(sensors)}")
    for index, (sid, reading) in enumerate(sensors, start=1):
      result = "OK" if reading.qualifies_ok() else "NOK"
      tree.insert(
        "",
        "end",
        values=(
          index,
          sid,
          reading.display_decoder,
          reading.display_pressure,
          reading.display_pressure_bar,
          reading.display_temp,
          reading.display_battery,
          reading.display_rssi,
          self._sensor_reads.get(sid, 1),
          result,
        ),
        tags=(result,),
      )

  def _autosave_tick(self) -> None:
    try:
      if self._autosave_dirty and self._sensors:
        self._persist_session(force=False)
    finally:
      self.after(self._AUTOSAVE_MS, self._autosave_tick)

  def _persist_session(self, force: bool = True) -> None:
    if not self._sensors and not force:
      return
    if not self._sensors:
      return
    try:
      save_session(
        sensors=self._sensors,
        sensor_reads=self._sensor_reads,
        sensor_first_seen=self._sensor_first_seen,
        total_readings=self._total_readings,
        session_start=self._session_start,
      )
      self._autosave_dirty = False
    except Exception as exc:
      self._log(f"SDR autosave failed: {exc}")

  def previous_sensor_count(self) -> int:
    data = load_session()
    if not data:
      return 0
    sensors = data.get("sensors") or {}
    return len(sensors) if isinstance(sensors, dict) else 0

  def restore_previous_session(self) -> bool:
    restored = self._restore_session_snapshot()
    if restored:
      self._log(
        f"Restored {len(self._sensors)} SDR sensor(s) from last session — press START to resume RF."
      )
    return restored

  def clear_session_silent(self) -> None:
    """Clear SDR live session without confirmation (startup New Session)."""
    self._clear_session()
    self.footer_label.configure(text="New session — previous SDR readings cleared")

  def _restore_session_snapshot(self) -> bool:
    data = load_session()
    if not data:
      return False
    sensors: Dict[str, TelemetryReading] = data["sensors"]
    sensor_reads: Dict[str, int] = data["sensor_reads"]
    sensor_first_seen: Dict[str, datetime] = data["sensor_first_seen"]
    self._sensors = sensors
    self._sensor_reads = sensor_reads
    for reading in self._sensors.values():
      try:
        from rtl433_runner import apply_battery_fields, renormalize_reading

        renormalize_reading(reading)
        apply_battery_fields(reading)
      except Exception:
        pass
    self._sensor_first_seen = sensor_first_seen
    self._total_readings = int(data.get("total_readings") or len(sensors))
    self._session_start = data.get("session_start")
    self._sensor_items.clear()
    for item in self.tree.get_children():
      self.tree.delete(item)
    # Insert oldest-first so newest stays at top like live capture.
    ordered = list(sensors.items())
    if hasattr(self, "rf_charts"):
      self.rf_charts.reset()
    for index, (sid, reading) in enumerate(ordered, start=1):
      reads = sensor_reads.get(sid, 1)
      result = "OK" if reading.qualifies_ok() else "NOK"
      item = self.tree.insert(
        "",
        0,
        values=self._row_values(index, reading, reads),
        tags=(result,),
      )
      self._sensor_items[sid] = item
      self.history.appendleft(reading)
      if hasattr(self, "rf_charts") and reading.rssi_db is not None:
        try:
          self.rf_charts.push(
            rssi=reading.rssi_db,
            sensor_id=sid,
            result=result,
          )
        except Exception:
          pass
    self._latest = ordered[-1][1] if ordered else None
    if self._latest is not None:
      self.live_bar.update_reading(self._latest)
      self._update_kpis(self._latest)
    self._refresh_table_count()
    self.footer_label.configure(
      text=f"Restored {len(sensors)} SDR sensor(s) — press START to keep listening"
    )
    self._autosave_dirty = False
    return True

  def _clear_session(self):
    self._pending_readings.clear()
    for item in self.tree.get_children():
      self.tree.delete(item)
    self.history.clear()
    self._sensors.clear()
    self._sensor_items.clear()
    self._sensor_reads.clear()
    self._sensor_first_seen.clear()
    self._row_matches.clear()
    self._total_readings = 0
    self._latest = None
    self._session_start = None
    self._autosave_dirty = False
    clear_session_file()
    self.live_bar.update_reading(None)
    self._update_kpis(None)
    if hasattr(self, "rf_charts"):
      self.rf_charts.reset()
    self._refresh_table_count()
    self._update_stats()
    if hasattr(self, "activity_terminal"):
      self.activity_terminal.clear()
    self._log("Session cleared.")
    self.footer_label.configure(text="Session cleared — ready for new readings")

  def update_tpms_range(
    self,
    *,
    rssi_byte: int | float | None = None,
    rssi_dbm: float | None = None,
    sensor_id: str = "",
  ) -> None:
    """Forward Board RSSI to the Range Radar tab when wired."""
    # Kept for compatibility; Range tab is fed from CombinedApp directly.
    return

  def _open_iq_folder(self) -> None:
    """Open results/iq so operators can replay .cu8 files in external SDR tools."""
    import os
    import subprocess
    import sys

    try:
      from tpms_bench.paths import results_dir

      folder = results_dir() / "iq"
    except Exception:
      folder = Path(__file__).resolve().parents[1] / "results" / "iq"
    folder.mkdir(parents=True, exist_ok=True)
    try:
      if sys.platform.startswith("win"):
        os.startfile(str(folder))  # type: ignore[attr-defined]
      elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
      else:
        subprocess.run(["xdg-open", str(folder)], check=False)
      self._log(f"IQ folder: {folder}")
    except Exception as exc:
      messagebox.showinfo(APP_NAME, f"IQ folder:\n{folder}\n\n({exc})", parent=self._toplevel())

  def _show_setup(self):
    SetupWizard(self._toplevel(), on_complete=lambda: self._log("Driver setup complete."))

  def _load_prefs(self):
    prefs = self.setup_mgr.load_settings()
    if prefs.get("preset"):
      self.preset_combo.set(prefs["preset"])
      self._on_preset_change(prefs["preset"])
    if prefs.get("gain"):
      self.gain_combo.set(prefs["gain"])
    if prefs.get("ppm"):
      self.ppm_entry.delete(0, "end")
      self.ppm_entry.insert(0, str(prefs["ppm"]))

  def _save_prefs(self):
    self.setup_mgr.save_settings(
      {
        "setup_complete": True,
        "preset": self.preset_combo.get(),
        "gain": self.gain_combo.get(),
        "ppm": self.ppm_entry.get(),
      }
    )

  def shutdown(self):
    self._want_listening = False
    self._cancel_auto_restart()
    try:
      if self._pending_readings:
        self._flush_readings()
    except Exception:
      pass
    self.runner.stop()
    self._persist_session(force=True)
    self._save_prefs()
