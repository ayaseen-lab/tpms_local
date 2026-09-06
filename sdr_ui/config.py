"""Application configuration and frequency presets."""

import os
import sys
from pathlib import Path

APP_NAME = "TPMS Suite"
APP_VERSION = "1.0.0"
APP_VENDOR = "Xynovix"

# Bundled rtl_433 MSVC build (included in executable)
RTL_433_VERSION = "25.12"
RTL_433_ZIP_NAME = f"rtl_433-win-msvc-x64-{RTL_433_VERSION}.zip"
RTL_433_DOWNLOAD_URL = (
    f"https://github.com/merbanan/rtl_433/releases/download/"
    f"{RTL_433_VERSION}/{RTL_433_ZIP_NAME}"
)

# Prefer rtl_433-rtlsdr for RTL-SDR dongles; fall back to generic build
RTL_433_EXE_CANDIDATES = ("rtl_433-rtlsdr.exe", "rtl_433.exe")

# Zadig for RTL-SDR driver setup (bundled in executable)
ZADIG_VERSION = "2.9"
ZADIG_EXE_NAME = "zadig.exe"
ZADIG_DOWNLOAD_URL = "https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe"
ZADIG_URL = ZADIG_DOWNLOAD_URL  # website / fallback download


def is_frozen() -> bool:
  return bool(getattr(sys, "frozen", False))


def get_install_dir() -> Path:
  """Folder that contains the .exe when packaged, or the repo root in source."""
  if is_frozen():
    return Path(sys.executable).resolve().parent
  return Path(__file__).resolve().parents[1]


def get_project_root() -> Path:
  if is_frozen():
    return Path(getattr(sys, "_MEIPASS", get_install_dir()))
  return Path(__file__).resolve().parent


def resolve_rtl433_exe_in(dir_path: Path) -> Path | None:
  for name in RTL_433_EXE_CANDIDATES:
    candidate = dir_path / name
    if candidate.is_file():
      return candidate
  return None


def _first_existing_rtl433_dir(candidates: list[Path]) -> Path:
  for path in candidates:
    if resolve_rtl433_exe_in(path):
      return path
  return candidates[0]


def get_bundled_rtl433_dir() -> Path:
  """rtl_433 folder shipped inside the app / PyInstaller bundle."""
  if is_frozen():
    root = get_project_root()
    install = get_install_dir()
    return _first_existing_rtl433_dir(
      [install / "rtl_433", root / "rtl_433", root / "vendor" / "rtl_433"]
    )
  return get_project_root() / "vendor" / "rtl_433"


def get_bundled_zadig_exe() -> Path:
  """Zadig shipped inside the app / PyInstaller bundle."""
  if is_frozen():
    root = get_project_root()
    install = get_install_dir()
    for candidate in (
      install / "zadig" / ZADIG_EXE_NAME,
      root / "zadig" / ZADIG_EXE_NAME,
      root / "vendor" / ZADIG_EXE_NAME,
    ):
      if candidate.is_file():
        return candidate
    return root / "zadig" / ZADIG_EXE_NAME
  return get_project_root() / "vendor" / ZADIG_EXE_NAME


def get_zadig_exe() -> Path:
  """Runtime Zadig path (deployed copy preferred)."""
  deployed = get_app_data_dir() / ZADIG_EXE_NAME
  if deployed.is_file():
    return deployed
  bundled = get_bundled_zadig_exe()
  if bundled.is_file():
    return bundled
  return deployed


def get_app_data_dir() -> Path:
  base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
  path = Path(base) / "TPMSMonitor"
  path.mkdir(parents=True, exist_ok=True)
  return path


def get_rtl433_dir() -> Path:
  """Directory used as rtl_433 cwd. Prefer the bundled folder; AppData is fallback."""
  bundled = get_bundled_rtl433_dir()
  if resolve_rtl433_exe_in(bundled):
    return bundled
  return get_app_data_dir() / "rtl_433"


def get_rtl433_version_marker() -> Path:
  return get_app_data_dir() / "rtl_433_version.txt"


def get_rtl433_exe() -> Path:
  deployed = resolve_rtl433_exe_in(get_rtl433_dir())
  if deployed:
    return deployed
  bundled = resolve_rtl433_exe_in(get_bundled_rtl433_dir())
  if bundled:
    return bundled
  return get_rtl433_dir() / RTL_433_EXE_CANDIDATES[0]


def get_config_file() -> Path:
  return get_app_data_dir() / "settings.json"


# Frequency presets for TPMS and ISM bands
# 1 Msps + autolevel/minmax is recommended for FSK TPMS (default 250k often misses packets).
FREQUENCY_PRESETS = {
  "315 MHz — US / Canada TPMS": {
    "frequencies": ["315M"],
    "description": "North American tire pressure sensors (315 MHz ISM)",
    "sample_rate": 1000000,
    "hop_interval": None,
  },
  "433 MHz — EU / Asia TPMS": {
    "frequencies": ["433.92M"],
    "description": "European and Asian TPMS (433.92 MHz ISM)",
    "sample_rate": 1000000,
    "hop_interval": None,
  },
  "868 MHz — EU SRD": {
    "frequencies": ["868M"],
    "description": "European short-range devices band",
    "sample_rate": 1000000,
    "hop_interval": None,
  },
  "345 MHz — US TPMS (alt)": {
    "frequencies": ["345M"],
    "description": "Alternate US TPMS band",
    "sample_rate": 1000000,
    "hop_interval": None,
  },
  "Dual — 315 + 433 MHz": {
    "frequencies": ["315M", "433.92M"],
    "description": "Hop between US and EU TPMS bands",
    "sample_rate": 1000000,
    "hop_interval": 8,
  },
  "Custom": {
    "frequencies": ["433.92M"],
    "description": "User-defined center frequency",
    "sample_rate": 1000000,
    "hop_interval": None,
    "custom": True,
  },
}

DEFAULT_PRESET = "433 MHz — EU / Asia TPMS"

# Pressure thresholds for visual alerts (PSI)
PRESSURE_LOW_PSI = 28.0
PRESSURE_WARN_PSI = 32.0
