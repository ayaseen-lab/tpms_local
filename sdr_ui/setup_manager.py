"""First-run setup: deploy bundled rtl_433, verify SDR, guide driver install."""

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests

from config import (
  get_app_data_dir,
  get_bundled_rtl433_dir,
  get_bundled_zadig_exe,
  get_config_file,
  get_rtl433_dir,
  get_rtl433_exe,
  get_rtl433_version_marker,
  get_zadig_exe,
  resolve_rtl433_exe_in,
  RTL_433_DOWNLOAD_URL,
  RTL_433_VERSION,
  RTL_433_ZIP_NAME,
  ZADIG_DOWNLOAD_URL,
  ZADIG_EXE_NAME,
)


class SetupManager:
  def __init__(self, on_progress: Optional[Callable[[str, float], None]] = None):
    self.on_progress = on_progress or (lambda msg, pct: None)

  def _report(self, message: str, percent: float) -> None:
    self.on_progress(message, percent)

  def is_rtl433_installed(self) -> bool:
    return get_rtl433_exe().is_file()

  def is_rtl433_bundled(self) -> bool:
    return resolve_rtl433_exe_in(get_bundled_rtl433_dir()) is not None

  def deploy_bundled_rtl433(self) -> bool:
    """Use rtl_433 from the install folder. Do not copy EXEs into AppData."""
    if not self.is_rtl433_bundled() and not self.is_rtl433_installed():
      return False

    marker = get_rtl433_version_marker()
    marker.write_text(RTL_433_VERSION, encoding="utf-8")
    exe = get_rtl433_exe()
    if exe.is_file():
      self._report(f"rtl_433 ready: {exe.name}", 0.9)
      return True
    return False

  def download_rtl433(self) -> bool:
    """Fallback only when bundled copy is missing (Windows). On macOS use Homebrew."""
    import sys

    if not sys.platform.startswith("win"):
      exe = get_rtl433_exe()
      if exe.is_file():
        self._report(f"Using system rtl_433: {exe}", 0.9)
        return True
      self._report("Install rtl_433 with Homebrew: brew install rtl_433", 0.0)
      return False

    target_dir = get_rtl433_dir()
    zip_path = get_app_data_dir() / RTL_433_ZIP_NAME

    try:
      self._report("Downloading rtl_433 (fallback)…", 0.1)
      response = requests.get(RTL_433_DOWNLOAD_URL, stream=True, timeout=120)
      response.raise_for_status()
      total = int(response.headers.get("content-length", 0))
      downloaded = 0

      with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
          if chunk:
            f.write(chunk)
            downloaded += len(chunk)
            if total:
              self._report("Downloading rtl_433…", 0.1 + 0.5 * downloaded / total)

      self._report("Extracting rtl_433…", 0.65)
      if target_dir.exists():
        shutil.rmtree(target_dir)
      target_dir.mkdir(parents=True, exist_ok=True)

      with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)

      children = list(target_dir.iterdir())
      if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        for item in inner.iterdir():
          dest = target_dir / item.name
          if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
          else:
            shutil.copy2(item, dest)
        shutil.rmtree(inner)

      zip_path.unlink(missing_ok=True)
      get_rtl433_version_marker().write_text(RTL_433_VERSION, encoding="utf-8")
      self._report("rtl_433 installed.", 0.9)
      return self.is_rtl433_installed()
    except Exception as exc:
      self._report(f"Install failed: {exc}", 0.0)
      return False

  def is_zadig_bundled(self) -> bool:
    return get_bundled_zadig_exe().is_file()

  def deploy_bundled_zadig(self) -> Optional[Path]:
    """Return bundled Zadig path without copying it to AppData."""
    bundled = get_bundled_zadig_exe()
    if bundled.is_file():
      self._report("Zadig driver tool ready (bundled).", 0.5)
      return bundled
    return None

  def open_zadig(self) -> Optional[Path]:
    """Launch Zadig from bundled copy (no download)."""
    path = self.deploy_bundled_zadig()
    if path and path.is_file():
      os.startfile(str(path))
      return path
    return self.download_zadig()

  def download_zadig(self) -> Optional[Path]:
    """Fallback when bundled Zadig is missing."""
    zadig_path = get_app_data_dir() / ZADIG_EXE_NAME
    if zadig_path.exists():
      os.startfile(str(zadig_path))
      return zadig_path
    try:
      self._report("Downloading Zadig (fallback)…", 0.1)
      response = requests.get(ZADIG_DOWNLOAD_URL, stream=True, timeout=120)
      response.raise_for_status()
      with open(zadig_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
          if chunk:
            f.write(chunk)
      os.startfile(str(zadig_path))
      return zadig_path
    except Exception:
      return None

  def test_rtl433_device(self) -> tuple[bool, str]:
    exe = get_rtl433_exe()
    if not exe.is_file():
      return False, "rtl_433 not found. Re-run setup."

    try:
      result = subprocess.run(
        [str(exe), "-V"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(get_rtl433_dir()),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
      )
      version_line = (result.stdout or result.stderr or "").strip().split("\n")[0]
      if not version_line:
        version_line = f"{exe.name} ready"

      probe = subprocess.run(
        [str(exe), "-f", "433.92M", "-T", "2", "-F", "null"],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(get_rtl433_dir()),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
      )
      combined = (probe.stdout or "") + (probe.stderr or "")
      if "No supported devices found" in combined or "Failed to open" in combined:
        return False, "RTL-SDR not detected. Install driver with Zadig (WinUSB)."
      # R82xx "PLL not locked" is normal chatter — do not fail the probe.
      return True, version_line
    except subprocess.TimeoutExpired:
      return True, "SDR probe timed out (device may still work)."
    except Exception as exc:
      return False, str(exc)

  def run_full_setup(self) -> bool:
    import sys

    if not sys.platform.startswith("win") and get_rtl433_exe().is_file():
      self._report(f"Using system rtl_433: {get_rtl433_exe()}", 0.9)
      self._report("Setup complete.", 1.0)
      return True

    if self.is_rtl433_bundled():
      ok = self.deploy_bundled_rtl433()
    elif not self.is_rtl433_installed():
      ok = self.download_rtl433()
    else:
      ok = True
      self._report("rtl_433 already installed.", 0.9)

    if sys.platform.startswith("win") and self.is_zadig_bundled():
      self.deploy_bundled_zadig()
      self._report("Zadig driver tool ready (bundled).", 0.95)

    self._report("Setup complete.", 1.0)
    return ok

  def load_settings(self) -> dict:
    path = get_config_file()
    if path.exists():
      try:
        with open(path, encoding="utf-8") as f:
          return json.load(f)
      except (json.JSONDecodeError, OSError):
        pass
    return {}

  def save_settings(self, settings: dict) -> None:
    path = get_config_file()
    with open(path, "w", encoding="utf-8") as f:
      json.dump(settings, f, indent=2)

  def is_first_run(self) -> bool:
    settings = self.load_settings()
    return not settings.get("setup_complete", False)

  def mark_setup_complete(self) -> None:
    settings = self.load_settings()
    settings["setup_complete"] = True
    self.save_settings(settings)
