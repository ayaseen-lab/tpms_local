"""Application configuration and frequency presets."""

import os
import sys
from pathlib import Path

APP_NAME = "Fyrqom TPMS Suite"
APP_VERSION = "1.3.0"
APP_VENDOR = "Xynovix"

# Bundled rtl_433 MSVC build (included in executable)
RTL_433_VERSION = "25.12"
RTL_433_ZIP_NAME = f"rtl_433-win-msvc-x64-{RTL_433_VERSION}.zip"
RTL_433_DOWNLOAD_URL = (
    f"https://github.com/merbanan/rtl_433/releases/download/"
    f"{RTL_433_VERSION}/{RTL_433_ZIP_NAME}"
)

# Prefer rtl_433-rtlsdr for RTL-SDR dongles; fall back to generic build.
# Include extensionless names for macOS / Linux Homebrew installs.
RTL_433_EXE_CANDIDATES = (
  "rtl_433-rtlsdr.exe",
  "rtl_433.exe",
  "rtl_433-rtlsdr",
  "rtl_433",
)

# Protocols disabled by default in rtl_433 25.12 (marked * in -R help).
# Fallback only — live IDs are read from the bundled binary via ``rtl_433 -R help``.
RTL433_DISABLED_PROTOCOL_IDS: tuple[int, ...] = (
  6, 7, 13, 14, 24, 37, 48, 61, 62, 64, 72, 86, 101, 106, 107, 117, 118, 123,
  129, 150, 162, 169, 198, 200, 216, 233, 242, 245, 248, 260, 270,
)

# Cache: resolved exe path → (catalog, disabled ids). Empty key = last successful parse.
_protocol_info_cache: dict[str, tuple[dict[int, str], tuple[int, ...]]] = {}


def _run_rtl433_help(exe: Path | None, topic: str) -> str:
  import os
  import subprocess

  binary = exe if exe is not None else get_rtl433_exe()
  if not binary or not Path(binary).is_file():
    return ""
  try:
    result = subprocess.run(
      [str(binary), topic, "help"],
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      timeout=20,
      cwd=str(Path(binary).parent),
      creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
  except Exception:
    return ""
  return (result.stdout or "") + "\n" + (result.stderr or "")


def _rtl433_cache_key(exe: Path | None) -> str:
  binary = Path(exe) if exe is not None else get_rtl433_exe()
  try:
    path = Path(binary)
    if path.is_file():
      return str(path.resolve())
  except Exception:
    pass
  return ""


def _rtl433_protocol_info(exe: Path | None = None) -> tuple[dict[int, str], tuple[int, ...]]:
  """Parse the current library's ``-R help`` once: id → name, plus disabled-by-default ids."""
  import re

  key = _rtl433_cache_key(exe)
  cached = _protocol_info_cache.get(key) if key else None
  if cached is not None:
    return cached

  text = _run_rtl433_help(exe, "-R")
  catalog: dict[int, str] = {}
  disabled: list[int] = []
  if text:
    for match in re.finditer(r"\[(\d+)\](\*)?\s+(.+)", text):
      name = match.group(3).strip()
      if name.startswith("=") or "Disabled by default" in name:
        continue
      proto_id = int(match.group(1))
      catalog[proto_id] = name
      if match.group(2):
        disabled.append(proto_id)

  disabled_ids = tuple(disabled) if disabled else RTL433_DISABLED_PROTOCOL_IDS
  info = (catalog, disabled_ids)
  if key and catalog:
    _protocol_info_cache[key] = info
  return info


def discover_disabled_protocol_ids(exe: Path | None = None) -> tuple[int, ...]:
  """Protocol ids marked ``*`` (disabled by default) in the current rtl_433 library."""
  _catalog, disabled = _rtl433_protocol_info(exe)
  return disabled


def rtl433_protocol_catalog(exe: Path | None = None) -> dict[int, str]:
  """Map protocol ID → full library decoder name from ``rtl_433 -R help``."""
  catalog, _disabled = _rtl433_protocol_info(exe)
  return catalog


def format_rtl433_decoder(
  protocol_id: int | None = None,
  model: str | None = None,
  *,
  exe: Path | None = None,
) -> str:
  """Human label for the rtl_433 library decoder that produced a packet."""
  catalog = rtl433_protocol_catalog(exe)
  model_text = (model or "").strip()
  if protocol_id is not None:
    name = catalog.get(int(protocol_id))
    if name:
      return f"[{protocol_id}] {name}"
    if model_text:
      return f"[{protocol_id}] {model_text}"
    return f"[{protocol_id}]"
  if model_text:
    model_l = model_text.lower().replace("_", " ").replace("-", " ")
    for pid, name in catalog.items():
      name_l = name.lower().replace("_", " ").replace("-", " ")
      if name_l == model_l or name_l.startswith(model_l + " ") or model_l.startswith(name_l + " "):
        return f"[{pid}] {name}"
    return model_text
  return "—"


def rtl433_tpms_protocol_ids(exe: Path | None = None) -> tuple[int, ...]:
  """Protocol ids whose library name contains ``TPMS``."""
  catalog = rtl433_protocol_catalog(exe)
  if catalog:
    return tuple(sorted(pid for pid, name in catalog.items() if "TPMS" in name.upper()))
  # Fallback catalog snapshot (rtl_433 25.12).
  return (
    59, 60, 82, 88, 89, 90, 95, 110, 123, 140, 156, 168, 180, 186,
    201, 203, 208, 212, 225, 226, 241, 248, 252, 257, 275,
  )


def rtl433_full_decoder_flags(exe: Path | None = None) -> list[str]:
  """CLI flags that enable every decoder in the current rtl_433 library.

  Listing every protocol id (not only the disabled-by-default ones) turns on
  the full catalog. The first ``-R`` replaces rtl_433's default set, so every
  id from ``-R help`` must be included.
  """
  catalog, disabled = _rtl433_protocol_info(exe)
  if catalog:
    flags: list[str] = []
    for proto_id in sorted(catalog):
      flags.extend(["-R", str(proto_id)])
    return flags
  # Binary could not be queried — keep defaults and add known disabled ids.
  flags = []
  for proto_id in disabled:
    flags.extend(["-R", f"-{proto_id}", "-R", str(proto_id)])
  return flags


def rtl433_tpms_decoder_flags(exe: Path | None = None) -> list[str]:
  """CLI flags that enable only TPMS library decoders (faster, fewer dropped packets)."""
  ids = rtl433_tpms_protocol_ids(exe)
  flags: list[str] = []
  for proto_id in ids:
    flags.extend(["-R", str(proto_id)])
  return flags


def rtl433_decoder_enablement(exe: Path | None = None, *, tpms_only: bool = False) -> str:
  """Short log line: how many current-library decoders are being enabled."""
  catalog, disabled = _rtl433_protocol_info(exe)
  n_disabled = len(disabled)
  if tpms_only:
    tpms_ids = rtl433_tpms_protocol_ids(exe)
    return (
      f"rtl_433 {RTL_433_VERSION} library: enabling {len(tpms_ids)} TPMS decoders "
      f"(TPMS-only mode for max unique Sensor IDs)"
    )
  if catalog:
    return (
      f"rtl_433 {RTL_433_VERSION} library: enabling all {len(catalog)} decoders "
      f"({n_disabled} were disabled by default)"
    )
  return (
    f"rtl_433 {RTL_433_VERSION} library: catalog unavailable — enabling "
    f"{n_disabled} known disabled-by-default decoders"
  )


def compact_rtl433_command(cmd: list[str]) -> str:
  """Join a rtl_433 command, collapsing ``-R <id>`` runs so logs stay readable."""
  parts: list[str] = []
  r_count = 0
  i = 0
  while i < len(cmd):
    if cmd[i] == "-R" and i + 1 < len(cmd):
      r_count += 1
      i += 2
      continue
    if r_count:
      parts.append(f"-R<{r_count} decoders>")
      r_count = 0
    parts.append(cmd[i])
    i += 1
  if r_count:
    parts.append(f"-R<{r_count} decoders>")
  return " ".join(parts)


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
    if name.endswith(".exe") and not sys.platform.startswith("win"):
      continue
    candidate = dir_path / name
    if candidate.is_file():
      return candidate
  return None


def _path_rtl433() -> Path | None:
  import shutil

  for name in ("rtl_433-rtlsdr", "rtl_433"):
    found = shutil.which(name)
    if found:
      return Path(found)
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
  if sys.platform == "darwin":
    base = Path.home() / "Library" / "Application Support"
  elif sys.platform.startswith("win"):
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
  else:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
  path = base / "TPMSMonitor"
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
  # On macOS/Linux prefer Homebrew / PATH over leftover Windows AppData zips.
  if not sys.platform.startswith("win"):
    native = _path_rtl433()
    if native:
      return native

  deployed = resolve_rtl433_exe_in(get_rtl433_dir())
  if deployed:
    return deployed
  bundled = resolve_rtl433_exe_in(get_bundled_rtl433_dir())
  if bundled:
    return bundled

  native = _path_rtl433()
  if native:
    return native

  if sys.platform.startswith("win"):
    return get_rtl433_dir() / RTL_433_EXE_CANDIDATES[0]
  return Path("/opt/homebrew/bin/rtl_433")


def get_config_file() -> Path:
  return get_app_data_dir() / "settings.json"


# Frequency presets for TPMS and ISM bands
# 1 Msps already spans ~±500 kHz, so stay locked on center — hopping away from
# 433.92/315.00 drops unique TPMS IDs on dense benches.
_DEFAULT_SAMPLE_RATE = 1_000_000

FREQUENCY_PRESETS = {
  "315 MHz — US / Canada TPMS": {
    "frequencies": ["315M"],
    "description": "North American tire pressure sensors (315 MHz ISM, locked center)",
    "sample_rate": _DEFAULT_SAMPLE_RATE,
    "hop_interval": None,
  },
  "433 MHz — EU / Asia TPMS": {
    "frequencies": ["433.92M"],
    "description": "European and Asian TPMS (433.92 MHz locked — max unique IDs)",
    "sample_rate": _DEFAULT_SAMPLE_RATE,
    "hop_interval": None,
  },
  "868 MHz — EU SRD": {
    "frequencies": ["868M"],
    "description": "European short-range devices band",
    "sample_rate": _DEFAULT_SAMPLE_RATE,
    "hop_interval": None,
  },
  "345 MHz — US TPMS (alt)": {
    "frequencies": ["345M"],
    "description": "Alternate US TPMS band (locked center)",
    "sample_rate": _DEFAULT_SAMPLE_RATE,
    "hop_interval": None,
  },
  "Dual — 315 + 433 MHz": {
    "frequencies": ["315M", "433.92M"],
    "description": "Hop between US and EU TPMS bands (use only if both bands needed)",
    "sample_rate": _DEFAULT_SAMPLE_RATE,
    "hop_interval": 2,
  },
  "Custom": {
    "frequencies": ["433.92M"],
    "description": "User-defined center frequency",
    "sample_rate": _DEFAULT_SAMPLE_RATE,
    "hop_interval": None,
    "custom": True,
  },
}

DEFAULT_PRESET = "433 MHz — EU / Asia TPMS"

# Pressure thresholds for visual alerts (PSI)
PRESSURE_LOW_PSI = 28.0
PRESSURE_WARN_PSI = 32.0
