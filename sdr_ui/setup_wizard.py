"""First-run setup wizard — light theme."""

import customtkinter as ctk
import webbrowser
from typing import Callable

from config import APP_NAME, ZADIG_URL
from setup_manager import SetupManager
from themes import (
  COLOR_BG,
  COLOR_BG_CARD,
  COLOR_BORDER,
  COLOR_BTN_PRIMARY,
  COLOR_BTN_PRIMARY_HOVER,
  COLOR_BTN_SECONDARY,
  COLOR_BTN_SECONDARY_HOVER,
  COLOR_HEADER_BG,
  COLOR_HEADER_SUB,
  COLOR_HEADER_TEXT,
  COLOR_TEXT,
  COLOR_TEXT_DIM,
)


class SetupWizard(ctk.CTkToplevel):
  def __init__(self, master, on_complete: Callable[[], None]):
    super().__init__(master)
    self.on_complete = on_complete
    self.setup_mgr = SetupManager(on_progress=self._on_progress)
    self.title(f"{APP_NAME} — Driver Setup")
    self.geometry("580x440")
    self.resizable(False, False)
    self.configure(fg_color=COLOR_BG)
    self.transient(master)
    self.grab_set()

    self._build()
    self.after(300, self._start_setup)

  def _build(self):
    header = ctk.CTkFrame(self, fg_color=COLOR_HEADER_BG, corner_radius=0, height=52)
    header.pack(fill="x")
    header.pack_propagate(False)
    ctk.CTkLabel(
      header, text="Plug & Play Setup", font=ctk.CTkFont(size=16, weight="bold"), text_color=COLOR_HEADER_TEXT
    ).pack(anchor="w", padx=24, pady=(10, 0))
    ctk.CTkLabel(
      header, text="RTL-SDR driver configuration", font=ctk.CTkFont(size=11), text_color=COLOR_HEADER_SUB
    ).pack(anchor="w", padx=24)

    ctk.CTkLabel(
      self,
      text="rtl_433 is bundled with this application. Verify your RTL-SDR receiver and install the USB driver if needed.",
      font=ctk.CTkFont(size=12),
      text_color=COLOR_TEXT_DIM,
      wraplength=520,
      justify="left",
    ).pack(anchor="w", padx=24, pady=(20, 8))

    self.progress = ctk.CTkProgressBar(self, width=500, progress_color=COLOR_BTN_PRIMARY, fg_color=COLOR_BORDER)
    self.progress.pack(padx=24, pady=12)
    self.progress.set(0)

    self.status_label = ctk.CTkLabel(self, text="Initializing…", text_color=COLOR_TEXT, wraplength=500)
    self.status_label.pack(anchor="w", padx=24)

    driver_frame = ctk.CTkFrame(
      self, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER
    )
    driver_frame.pack(fill="x", padx=24, pady=16)

    ctk.CTkLabel(
      driver_frame,
      text="RTL-SDR USB Driver (Zadig)",
      font=ctk.CTkFont(size=13, weight="bold"),
      text_color=COLOR_TEXT,
    ).pack(anchor="w", padx=16, pady=(14, 4))

    ctk.CTkLabel(
      driver_frame,
      text="1. Connect RTL-SDR dongle\n2. Open Zadig → Options → List All Devices\n3. Select RTL2832U device\n4. Install WinUSB driver",
      font=ctk.CTkFont(size=11),
      text_color=COLOR_TEXT_DIM,
      wraplength=460,
      justify="left",
    ).pack(anchor="w", padx=16, pady=(0, 10))

    btn_row = ctk.CTkFrame(driver_frame, fg_color="transparent")
    btn_row.pack(anchor="w", padx=16, pady=(0, 14))

    ctk.CTkButton(
      btn_row,
      text="Run Zadig",
      width=140,
      fg_color=COLOR_BTN_PRIMARY,
      hover_color=COLOR_BTN_PRIMARY_HOVER,
      command=self._open_zadig,
    ).pack(side="left", padx=(0, 8))

    ctk.CTkButton(
      btn_row,
      text="Zadig Website",
      width=120,
      fg_color=COLOR_BTN_SECONDARY,
      hover_color=COLOR_BTN_SECONDARY_HOVER,
      command=lambda: webbrowser.open(ZADIG_URL),
    ).pack(side="left")

    self.continue_btn = ctk.CTkButton(
      self,
      text="Continue to Dashboard",
      width=200,
      height=38,
      state="disabled",
      fg_color=COLOR_BTN_PRIMARY,
      hover_color=COLOR_BTN_PRIMARY_HOVER,
      command=self._finish,
    )
    self.continue_btn.pack(pady=16)

  def _on_progress(self, message: str, percent: float):
    self.after(0, lambda: self._update_progress(message, percent))

  def _update_progress(self, message: str, percent: float):
    self.status_label.configure(text=message)
    self.progress.set(min(1.0, max(0.0, percent)))

  def _start_setup(self):
    ok = self.setup_mgr.run_full_setup()
    if ok:
      _, msg = self.setup_mgr.test_rtl433_device()
      self._update_progress(msg, 1.0)
    self.continue_btn.configure(state="normal")

  def _open_zadig(self):
    self.setup_mgr.open_zadig()

  def _finish(self):
    self.setup_mgr.mark_setup_complete()
    self.grab_release()
    self.destroy()
    self.on_complete()
