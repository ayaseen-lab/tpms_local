"""SDR Receiver view — RTL-SDR telemetry dashboard (embeddable frame)."""

import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Deque, Dict, Optional

import customtkinter as ctk

from activity_terminal import ActivityTerminalPanel
from config import APP_NAME, DEFAULT_PRESET, FREQUENCY_PRESETS, get_rtl433_exe
from dialogs import ask_save_path
from rtl433_runner import Rtl433Runner, TelemetryReading
from session_export import export_session_excel, export_session_pdf
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

    self.setup_mgr = SetupManager()
    self.history: Deque[TelemetryReading] = deque(maxlen=50000)
    self._sensors: Dict[str, TelemetryReading] = {}
    self._sensor_items: Dict[str, str] = {}
    self._sensor_reads: Dict[str, int] = {}
    self._sensor_first_seen: Dict[str, datetime] = {}
    self._listening = False
    self._sdr_paused = False
    self._total_readings = 0
    self._latest: Optional[TelemetryReading] = None
    self._session_start: Optional[datetime] = None
    self._exporting = False

    self.runner = Rtl433Runner(
      on_reading=self._on_reading,
      on_log=self._on_log,
      on_state_change=self._on_state_change,
    )

    self._setup_styles()
    self._build_ui()
    self._load_prefs()
    self._update_stats()
    self._notify_status()

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

    results = tk.Frame(self, bg=COLOR_BG, highlightbackground=COLOR_BORDER, highlightthickness=1)
    results.pack(side="bottom", fill="x", pady=(6, 2))

    table_header = tk.Frame(results, bg=COLOR_BG_PANEL)
    table_header.pack(fill="x")
    tk.Label(
      table_header, text="Detected sensors — OK / NOK", bg=COLOR_BG_PANEL, fg=COLOR_TEXT, font=("Segoe UI", 10, "bold")
    ).pack(side="left", padx=8, pady=4)
    self.table_count_label = tk.Label(
      table_header, text="0 sensors", bg=COLOR_BG_PANEL, fg=COLOR_TEXT_DIM, font=("Segoe UI", 9)
    )
    self.table_count_label.pack(side="right", padx=8)

    tree_host = tk.Frame(results, bg=COLOR_BG)
    tree_host.pack(fill="x", padx=4, pady=(0, 4))
    columns = ("num", "protocol", "id", "result", "pressure", "temp", "battery", "reads", "time", "reason")
    self.tree = ttk.Treeview(tree_host, columns=columns, show="headings", height=6, style="Combined.Treeview")
    headings = {
      "num": "#",
      "protocol": "rtl_433 Decoder",
      "id": "Sensor ID",
      "result": "Result",
      "pressure": "Pressure",
      "temp": "°C",
      "battery": "Batt",
      "reads": "Reads",
      "time": "Seen",
      "reason": "Notes / NOK reason",
    }
    self._tree_col_weights = {
      "num": 0.04,
      "protocol": 0.16,
      "id": 0.11,
      "result": 0.07,
      "pressure": 0.09,
      "temp": 0.06,
      "battery": 0.07,
      "reads": 0.06,
      "time": 0.08,
      "reason": 0.26,
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
    self.tree.tag_configure("flash", background=COLOR_CYAN_BG)
    self.tree.bind("<Configure>", self._fit_tree_columns, add="+")
    self.after(50, self._fit_tree_columns)

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
      text="rtl_433  ·  1 Msps decode boost  ·  OK/NOK from packet completeness",
      font=ctk.CTkFont(size=11),
      text_color=COLOR_TEXT_DIM,
    ).pack(side="right", padx=(0, 12))

    actions_inner = ctk.CTkFrame(top_inner, fg_color="transparent")
    actions_inner.pack(fill="x", pady=(0, 6))
    self.start_btn = ctk.CTkButton(
      actions_inner, text="START", width=130, height=34, font=ctk.CTkFont(size=12, weight="bold"),
      fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER, command=self._start_listen,
    )
    self.start_btn.pack(side="left", padx=(0, 6))
    self.pause_btn = ctk.CTkButton(
      actions_inner, text="PAUSE", width=90, height=34, font=ctk.CTkFont(size=12, weight="bold"),
      fg_color=COLOR_BTN_PAUSE, hover_color=COLOR_BTN_PAUSE_HOVER, state="disabled", command=self._pause_listen,
    )
    self.pause_btn.pack(side="left", padx=(0, 6))
    self.stop_btn = ctk.CTkButton(
      actions_inner, text="STOP", width=90, height=34, font=ctk.CTkFont(size=12, weight="bold"),
      fg_color=COLOR_BTN_STOP, hover_color=COLOR_BTN_STOP_HOVER, state="disabled", command=self._stop_listen,
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
      settings_row, values=preset_names, width=160, height=28, command=self._on_preset_change, **combo_colors()
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
    self.gain_combo.set("40")
    self.gain_combo.pack(side="left", padx=(0, 8))
    ctk.CTkLabel(settings_row, text="PPM", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      side="left", padx=(0, 4)
    )
    self.ppm_entry = ctk.CTkEntry(settings_row, width=50, height=28, **entry_colors())
    self.ppm_entry.insert(0, "0")
    self.ppm_entry.pack(side="left", padx=(0, 8))
    ctk.CTkLabel(settings_row, text="Dev", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).pack(
      side="left", padx=(0, 4)
    )
    self.device_entry = ctk.CTkEntry(settings_row, width=46, height=28, **entry_colors())
    self.device_entry.insert(0, "0")
    self.device_entry.pack(side="left", padx=(0, 8))
    self.units_combo = ctk.CTkComboBox(
      settings_row, values=["PSI / Fahrenheit", "kPa / Celsius"], width=140, height=28, **combo_colors()
    )
    self.units_combo.set("PSI / Fahrenheit")
    self.units_combo.pack(side="left", padx=(0, 8))
    self.tpms_only_switch = ctk.CTkSwitch(
      settings_row, text="TPMS only", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT, **switch_colors()
    )
    self.tpms_only_switch.select()
    self.tpms_only_switch.pack(side="left")
    self.record_iq_switch = ctk.CTkSwitch(
      settings_row,
      text="Record IQ",
      font=ctk.CTkFont(size=11),
      text_color=COLOR_TEXT,
      **switch_colors(),
    )
    self.record_iq_switch.select()
    self.record_iq_switch.pack(side="left", padx=(10, 0))
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

    current = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
    current.pack(fill="x", pady=(0, 6))
    current_inner = ctk.CTkFrame(current, fg_color="transparent")
    current_inner.pack(fill="x", padx=10, pady=6)
    freq_row = ctk.CTkFrame(current_inner, fg_color="transparent")
    freq_row.pack(fill="x")
    self.freq_label = ctk.CTkLabel(
      freq_row, text=f"Frequency Band: {DEFAULT_PRESET}", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
    )
    self.freq_label.pack(side="left")
    self.freq_detail = ctk.CTkLabel(
      freq_row, text=FREQUENCY_PRESETS[DEFAULT_PRESET]["description"], font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
    )
    self.freq_detail.pack(side="left", padx=(10, 0))
    self.live_bar = LiveTelemetryBar(current_inner)
    self.live_bar.pack(fill="x", pady=(6, 0))

    stats_row = ctk.CTkFrame(self, fg_color="transparent")
    stats_row.pack(fill="x", pady=(0, 4))
    for i in range(5):
      stats_row.grid_columnconfigure(i, weight=1)
    self.stat_sensors = StatCard(stats_row, "DETECTED", "0", COLOR_BLUE, COLOR_BLUE_BG, compact=True)
    self.stat_sensors.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    self.stat_readings = StatCard(stats_row, "READINGS", "0", COLOR_ORANGE, COLOR_ORANGE_BG, compact=True)
    self.stat_readings.grid(row=0, column=1, sticky="nsew", padx=4)
    self.stat_ok = StatCard(stats_row, "PASSED (OK)", "0", COLOR_GREEN, COLOR_GREEN_BG, compact=True)
    self.stat_ok.grid(row=0, column=2, sticky="nsew", padx=4)
    self.stat_nok = StatCard(stats_row, "FAILED (NOK)", "0", COLOR_RED, COLOR_RED_BG, compact=True)
    self.stat_nok.grid(row=0, column=3, sticky="nsew", padx=4)
    self.stat_rate = StatCard(stats_row, "PASS RATE", "0.0%", COLOR_HEADER_ACCENT, COLOR_CYAN_BG, compact=True)
    self.stat_rate.grid(row=0, column=4, sticky="nsew", padx=(4, 0))

    prog_row = ctk.CTkFrame(self, fg_color="transparent")
    prog_row.pack(fill="x")
    self.progress_label = ctk.CTkLabel(
      prog_row, text="Session: 0 readings  ·  Record IQ saves full-rate .cu8 (kept after stop for IQ / URH replay)",
      font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED,
    )
    self.progress_label.pack(side="left")
    self.progress = ctk.CTkProgressBar(self, height=6, progress_color=COLOR_GREEN, fg_color=COLOR_BORDER)
    self.progress.pack(fill="x", pady=(2, 6))
    self.progress.set(0)

  def _flash_row(self, item_id: str, tag: str, step: int = 0) -> None:
    if not self.tree.exists(item_id):
      return
    try:
      if step < 3:
        self.tree.item(item_id, tags=("flash",))
        self.after(70, lambda i=item_id, t=tag, s=step + 1: self._flash_row(i, t, s))
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
    n = len(self._sensors)
    self.table_count_label.configure(text=f"{n} sensor{'s' if n != 1 else ''}")

  def _sensor_counts(self) -> tuple[int, int]:
    ok = sum(1 for reading in self._sensors.values() if reading.qualifies_ok())
    return ok, len(self._sensors) - ok

  def _row_values(self, index: int, reading: TelemetryReading, reads: int) -> tuple:
    result = "OK" if reading.qualifies_ok() else "NOK"
    return (
      index,
      reading.display_decoder,
      reading.sensor_id or "na",
      result,
      reading.display_pressure,
      reading.display_temp,
      reading.display_battery,
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
    self._start_listen()

  def _start_listen(self):
    if self._listening:
      return
    preset = self.preset_combo.get()
    custom_mhz = None
    if FREQUENCY_PRESETS.get(preset, {}).get("custom"):
      try:
        custom_mhz = float(self.custom_freq.get().strip())
      except ValueError:
        self._log("Invalid center frequency — enter a number in MHz.")
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
      return

    self.runner.tpms_only = self.tpms_only_switch.get() == 1
    if not get_rtl433_exe().is_file():
      self._log("rtl_433 decoder missing — installing…")
      installed = SetupManager(on_progress=lambda msg, _pct: self._log(msg)).run_full_setup()
      if not installed or not get_rtl433_exe().is_file():
        self._log("ERROR: rtl_433 could not be installed. Open Driver Setup.")
        messagebox.showerror(APP_NAME, "rtl_433 decoder is missing and could not be installed.\n\nOpen Driver Setup and try again.", parent=self._toplevel())
        return
    self._sdr_paused = False
    record_iq = self.record_iq_switch.get() == 1
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
      if self._session_start is None:
        self._session_start = datetime.now()
      self._update_export_button()
      iq_note = " · IQ recording (full rate, kept)" if record_iq else ""
      self.footer_label.configure(text=f"Listening on {preset}{iq_note}…")

  def _pause_listen(self):
    if self._listening:
      self._sdr_paused = True
      self.runner.stop()
      self._log("SDR listening paused — session data is kept.")
      return
    if self._sdr_paused:
      self._start_listen()

  def _stop_listen(self):
    self._sdr_paused = False
    if self._listening:
      self.runner.stop()

  def _on_reading(self, reading: TelemetryReading):
    self.after(0, lambda r=reading: self._apply_reading(r))

  def _apply_reading(self, reading: TelemetryReading):
    self.history.appendleft(reading)
    self._total_readings += 1
    self._latest = reading
    self.live_bar.update_reading(reading)

    if not reading.has_sensor_id():
      self._update_stats()
      self.footer_label.configure(
        text=f"Last reading ignored for OK/NOK (no sensor ID): {reading.model} — {reading.display_pressure}"
      )
      self._log(f"{reading.model} | no sensor ID | skipped for detected OK/NOK")
      return

    sid = reading.sensor_id
    first_seen = self._sensor_first_seen.setdefault(sid, reading.timestamp)
    elapsed = max(0.0, (reading.timestamp - first_seen).total_seconds())

    if sid not in self._sensors:
      merged = reading
      if merged.qualifies_ok():
        merged.acquire_seconds = elapsed
      else:
        merged.acquire_seconds = elapsed
      self._sensors[sid] = merged
      self._sensor_reads[sid] = 1
      index = len(self._sensors)
      result = "OK" if merged.qualifies_ok() else "NOK"
      item = self.tree.insert("", 0, values=self._row_values(index, merged, 1), tags=(result,))
      self._sensor_items[sid] = item
    else:
      previous = self._sensors[sid]
      already_ok = previous.qualifies_ok()
      frozen = previous.acquire_seconds if already_ok else None
      merged = previous.merged_with(reading)
      if already_ok:
        merged.acquire_seconds = frozen
      elif merged.qualifies_ok():
        merged.acquire_seconds = elapsed
      else:
        merged.acquire_seconds = elapsed
      self._sensors[sid] = merged
      self._sensor_reads[sid] = self._sensor_reads.get(sid, 1) + 1
      item = self._sensor_items.get(sid)
      if item and self.tree.exists(item):
        try:
          index = int(self.tree.set(item, "num"))
        except (TypeError, ValueError):
          index = list(self._sensors.keys()).index(sid) + 1
        result = "OK" if merged.qualifies_ok() else "NOK"
        self.tree.item(
          item,
          values=self._row_values(index, merged, self._sensor_reads[sid]),
          tags=(result,),
        )
      else:
        result = "OK" if merged.qualifies_ok() else "NOK"
        item = self.tree.insert(
          "", 0, values=self._row_values(len(self._sensors), merged, self._sensor_reads[sid]), tags=(result,)
        )
        self._sensor_items[sid] = item

    result = "OK" if merged.qualifies_ok() else "NOK"
    if item and self.tree.exists(item):
      self._flash_row(item, result)
      self.tree.see(item)

    self._refresh_table_count()
    self._update_stats()
    reads = self._sensor_reads.get(sid, 1)
    self.footer_label.configure(
      text=f"Sensor {sid}: {result}  ·  {merged.display_pressure}  ·  {reads} read(s)"
    )
    self._log(
      f"{merged.model} | ID {sid} | {result} | {merged.display_pressure} | {merged.display_temp} | {reads} reads"
    )

  def _update_stats(self):
    sensors = len(self._sensors)
    ok, nok = self._sensor_counts()
    self.stat_sensors.set_value(str(sensors))
    self.stat_readings.set_value(str(self._total_readings))
    self.stat_ok.set_value(str(ok))
    self.stat_nok.set_value(str(nok))
    if sensors > 0:
      rate = (ok / sensors) * 100
      self.stat_rate.set_value(f"{rate:.1f}%")
      self.progress.set(ok / sensors)
    else:
      self.stat_rate.set_value("0.0%")
      self.progress.set(0)
    self.progress_label.configure(
      text=(
        f"Session: {self._total_readings} readings from {sensors} detected sensors  ·  "
        f"OK/NOK is per sensor (values merged across packets)"
      )
    )
    self._update_export_button()

  def _on_log(self, message: str):
    self.after(0, lambda m=message: self._log(m))

  def _on_state_change(self, running: bool):
    self.after(0, lambda r=running: self._set_status(r))

  def _set_status(self, running: bool):
    self._listening = running
    if running:
      self._sdr_paused = False
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
    else:
      label = "STOPPED"
    try:
      self.on_status_change(self._listening or self._sdr_paused, label)
    except Exception:
      pass

  def is_running(self) -> bool:
    return self._listening or self._sdr_paused

  def _log(self, message: str, level: str = "info"):
    if message.startswith("ERROR") or "Failed" in message:
      level = "error"
    elif message.startswith("Starting:"):
      level = "cmd"
    elif message.startswith("RAW ") or message.startswith("SKIP "):
      level = "rx" if message.startswith("RAW") else "dim"
    elif "| ID " in message:
      level = "rx"

    if hasattr(self, "activity_terminal"):
      self.activity_terminal.write(message, level=level)

  def get_sensor_snapshot(self) -> Dict[str, Any]:
    """Merged per-sensor readings for comparative OK/NOK analysis."""
    return dict(self._sensors)

  def _clear_session(self):
    for item in self.tree.get_children():
      self.tree.delete(item)
    self.history.clear()
    self._sensors.clear()
    self._sensor_items.clear()
    self._sensor_reads.clear()
    self._sensor_first_seen.clear()
    self._total_readings = 0
    self._latest = None
    self.live_bar.update_reading(None)
    self._refresh_table_count()
    self._update_stats()
    if hasattr(self, "activity_terminal"):
      self.activity_terminal.clear()
    self._log("Session cleared.")
    self.footer_label.configure(text="Session cleared — ready for new readings")

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
    self.runner.stop()
    self._save_prefs()
