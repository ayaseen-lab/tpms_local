"""rtl_433 subprocess management and JSON telemetry parsing."""

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import (
  FREQUENCY_PRESETS,
  compact_rtl433_command,
  format_rtl433_decoder,
  get_rtl433_dir,
  get_rtl433_exe,
  rtl433_decoder_enablement,
  rtl433_full_decoder_flags,
  rtl433_tpms_decoder_flags,
  rtl433_tpms_protocol_ids,
)

try:
  from tpms_bench.paths import results_dir
except Exception:  # pragma: no cover
  def results_dir():
    folder = Path(__file__).resolve().parents[1] / "results"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "iq").mkdir(parents=True, exist_ok=True)
    return folder

KPA_TO_PSI = 0.1450377377
HPA_TO_PSI = 0.01450377377
BAR_TO_PSI = 14.503773773


@dataclass
class TelemetryReading:
  sensor_id: str
  model: str
  sensor_type: str
  pressure_psi: Optional[float] = None
  pressure_hpa: Optional[float] = None
  temperature_c: Optional[float] = None
  battery_ok: Optional[bool] = None
  battery_voltage_v: Optional[float] = None
  status: Optional[int] = None
  raw: Dict[str, Any] = field(default_factory=dict)
  timestamp: datetime = field(default_factory=datetime.now)
  frequency_mhz: Optional[float] = None
  # Seconds from first packet for this ID until OK (or until latest packet if still NOK).
  acquire_seconds: Optional[float] = None
  # rtl_433 decoder that produced this packet, e.g. "[60] Schrader".
  decoder: str = ""
  protocol_id: Optional[int] = None

  @property
  def psi(self) -> Optional[float]:
    if self.pressure_psi is not None:
      return self.pressure_psi
    if self.pressure_hpa is not None:
      return self.pressure_hpa * HPA_TO_PSI
    return None

  @property
  def display_pressure(self) -> str:
    value = self.psi
    if value is not None:
      return f"{value:.1f} PSI"
    return "—"

  @property
  def display_temp(self) -> str:
    if self.temperature_c is not None:
      return f"{self.temperature_c:.0f} °C"
    return "—"

  @property
  def display_battery(self) -> str:
    if self.battery_voltage_v is not None:
      return f"{self.battery_voltage_v:.2f} V"
    if self.battery_ok is not None:
      return "OK" if self.battery_ok else "LOW"
    return "—"

  # Cache TPMS protocol ids so per-packet checks stay cheap under high RF load.
  _TPMS_PROTOCOL_IDS: Optional[set[int]] = None

  @classmethod
  def _tpms_ids(cls) -> set[int]:
    if cls._TPMS_PROTOCOL_IDS is None:
      try:
        cls._TPMS_PROTOCOL_IDS = set(rtl433_tpms_protocol_ids())
      except Exception:
        cls._TPMS_PROTOCOL_IDS = set()
    return cls._TPMS_PROTOCOL_IDS

  @property
  def is_tpms(self) -> bool:
    """Tire TPMS only — do not treat weather/oil/etc. as TPMS just because they report pressure."""
    t = (self.sensor_type or "").strip().upper()
    m = (self.model or "").strip().upper()
    if t == "TPMS":
      return True
    if "TPMS" in m:
      return True
    if self.protocol_id is not None:
      try:
        return int(self.protocol_id) in self._tpms_ids()
      except Exception:
        pass
    return False

  def has_sensor_id(self) -> bool:
    sid = (self.sensor_id or "").strip()
    if not sid:
      return False
    return sid.lower() not in {"none", "unknown", "n/a", "na", "—", "-"}

  def qualifies_ok(self) -> bool:
    """Actual rtl_433 library telemetry only — never guess from flex bits."""
    if (self.decoder or "").lower().startswith("[flex]"):
      return False
    has_core = self.has_sensor_id() and self.temperature_c is not None
    has_pressure = self.psi is not None
    has_battery = self.battery_ok is not None or self.battery_voltage_v is not None
    return bool(has_core and (has_pressure or has_battery))

  def nok_reason(self) -> str:
    if self.qualifies_ok():
      return ""
    if (self.decoder or "").lower().startswith("[flex]"):
      return "flex ID only — no actual temp/pressure from rtl_433 library"
    missing: List[str] = []
    if not self.has_sensor_id():
      missing.append("sensor ID")
    if self.temperature_c is None:
      missing.append("temperature")
    if self.psi is None and self.battery_ok is None and self.battery_voltage_v is None:
      missing.append("pressure or battery")
    return "missing " + " + ".join(missing) if missing else "incomplete telemetry"

  def merged_with(self, newer: "TelemetryReading") -> "TelemetryReading":
    """Combine packets for one sensor ID — keep values once seen (board-style completeness)."""
    return TelemetryReading(
      sensor_id=newer.sensor_id if newer.has_sensor_id() else self.sensor_id,
      model=newer.model or self.model,
      sensor_type=newer.sensor_type or self.sensor_type,
      pressure_psi=newer.pressure_psi if newer.pressure_psi is not None else self.pressure_psi,
      pressure_hpa=newer.pressure_hpa if newer.pressure_hpa is not None else self.pressure_hpa,
      temperature_c=newer.temperature_c if newer.temperature_c is not None else self.temperature_c,
      battery_ok=newer.battery_ok if newer.battery_ok is not None else self.battery_ok,
      battery_voltage_v=newer.battery_voltage_v if newer.battery_voltage_v is not None else self.battery_voltage_v,
      status=newer.status if newer.status is not None else self.status,
      raw=newer.raw or self.raw,
      timestamp=newer.timestamp,
      frequency_mhz=newer.frequency_mhz if newer.frequency_mhz is not None else self.frequency_mhz,
      acquire_seconds=newer.acquire_seconds if newer.acquire_seconds is not None else self.acquire_seconds,
      decoder=newer.decoder or self.decoder,
      protocol_id=newer.protocol_id if newer.protocol_id is not None else self.protocol_id,
    )

  @property
  def display_decoder(self) -> str:
    label = (self.decoder or "").strip()
    # Placeholders must stay as-is — never rewrite them to a bare model like "TPMS".
    low = label.lower()
    if low.startswith("rtl_433 · waiting") or low.startswith("board rf"):
      return label
    if self.protocol_id is not None:
      enriched = format_rtl433_decoder(self.protocol_id, self.model)
      if enriched and enriched != "—":
        return enriched
    if label and label not in {"—", "-", "TPMS", "tpms"}:
      if "[" in label:
        return label
      enriched = format_rtl433_decoder(self.protocol_id, self.model or label)
      if enriched and enriched != "—" and enriched.upper() != "TPMS":
        return enriched
      return label
    if self.protocol_id is not None:
      return format_rtl433_decoder(self.protocol_id, self.model)
    return "rtl_433 · waiting for decode"


def _safe_float(val: Any) -> Optional[float]:
  if val is None or val == "":
    return None
  try:
    return float(val)
  except (TypeError, ValueError):
    return None


def _first_float(data: Dict[str, Any], *keys: str) -> Optional[float]:
  for key in keys:
    if key in data and data[key] is not None and data[key] != "":
      val = _safe_float(data[key])
      if val is not None:
        return val
  return None


def _parse_pressure(data: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
  pressure_psi = _first_float(data, "pressure_PSI", "pressure_psi")
  pressure_kpa = _first_float(data, "pressure_kPa", "pressure_kpa", "pressure_KPA")
  pressure_hpa = _first_float(data, "pressure_hPa", "pressure_hpa")
  pressure_bar = _first_float(data, "pressure_bar", "pressure_BAR", "pressure_Bar")

  if pressure_psi is None and pressure_kpa is not None:
    pressure_psi = pressure_kpa * KPA_TO_PSI
    pressure_hpa = pressure_kpa * 10.0
  elif pressure_psi is None and pressure_hpa is not None:
    pressure_psi = pressure_hpa * HPA_TO_PSI
  elif pressure_psi is None and pressure_bar is not None:
    pressure_psi = pressure_bar * BAR_TO_PSI
    pressure_hpa = pressure_bar * 1000.0

  return pressure_psi, pressure_hpa


def _normalize_sensor_id(value: Any) -> str:
  """Canonical 8-digit hex Sensor ID so SDR matches Board OEID formatting."""
  if value is None:
    return ""
  if isinstance(value, bool):
    return ""
  if isinstance(value, int):
    if value < 0:
      # Signed rtl_433 ids still encode a 32-bit OE-style value.
      return f"{value & 0xFFFFFFFF:08X}"
    return f"{value & 0xFFFFFFFF:08X}"
  text = str(value).strip().replace(" ", "")
  if not text:
    return ""
  lower = text.lower()
  if lower in {"none", "unknown", "n/a", "na", "—", "-"}:
    return ""
  if lower.startswith("0x"):
    text = text[2:]
  if text.isdigit():
    try:
      return f"{int(text) & 0xFFFFFFFF:08X}"
    except ValueError:
      return text.upper()
  try:
    return f"{int(text, 16) & 0xFFFFFFFF:08X}"
  except ValueError:
    return text.upper()


# Flex catch-all for OE/Hamaton bursts the stock rtl_433 TPMS library misses
# (strong FSK ~52/104 µs Manchester — confirmed via IQ analyzer on conflict rows).
FLEX_TPMS_DECODER = "n=HamatonOE-FSK_MC,m=FSK_MC_ZEROBIT,s=52,l=104,r=4096"


def _flex_hex_blob(data: Dict[str, Any]) -> str:
  """Concatenate hex bit rows / codes from an rtl_433 flex JSON packet."""
  parts: list[str] = []
  for row in data.get("rows") or []:
    if isinstance(row, dict) and row.get("data"):
      parts.append(str(row["data"]).replace(" ", ""))
  for code in data.get("codes") or []:
    text = str(code)
    # "{104}000002d8c411ba…" → strip {len} prefix
    if "}" in text:
      text = text.split("}", 1)[-1]
    parts.append(text.replace(" ", ""))
  if data.get("data"):
    parts.append(str(data["data"]).replace(" ", ""))
  return "".join(parts).lower()


def _extract_id_from_flex_hex(blob: str) -> Optional[str]:
  """Pull an 8-nibble sensor ID out of flex Manchester bits."""
  hex_only = "".join(c for c in (blob or "") if c in "0123456789abcdef")
  if len(hex_only) < 8:
    return None
  candidates: list[str] = []
  for i in range(0, len(hex_only) - 7):
    window = hex_only[i : i + 8]
    if window == "00000000" or window == "ffffffff":
      continue
    if len(set(window)) <= 2:
      continue
    candidates.append(window.upper())
  if not candidates:
    return None
  for c in candidates:
    if c.endswith("C411BA") or c.endswith("411BA"):
      return c
  return candidates[0]


def _parse_flex_telemetry(blob: str, sensor_id: str) -> tuple[Optional[float], Optional[float]]:
    """Do not invent PSI/°C from raw Manchester bits.

    Flex only reliably recovers the sensor ID for these OE frames. Guessing
    temp/pressure from trailing bytes produced nonsense (e.g. 125 °C / 14.8 PSI)
    while the Board reported ~30 °C / ~0 PSI. Leave telemetry empty until a
    stock rtl_433 library decoder supplies real fields.
    """
    return None, None


def parse_rtl433_json(line: str) -> Optional[TelemetryReading]:
  line = line.strip()
  if not line or not line.startswith("{"):
    return None
  try:
    data = json.loads(line)
  except json.JSONDecodeError:
    return None

  model = str(data.get("model", "Unknown"))
  sensor_type = str(data.get("type", ""))

  sid = data.get("id")
  if sid is None:
    sid = data.get("ID") or data.get("sensor_id") or data.get("id_str")
  sensor_id = _normalize_sensor_id(sid)
  if not sensor_id and sid is not None:
    # Fall back to raw string when value is not a numeric ID.
    sensor_id = str(sid).strip()

  pressure_psi, pressure_hpa = _parse_pressure(data)
  temp_c = _first_float(data, "temperature_C", "temperature_c")
  if temp_c is None:
    temp_f = _first_float(data, "temperature_F", "temperature_f")
    if temp_f is not None:
      temp_c = (temp_f - 32) * 5 / 9

  battery = data.get("battery_ok")
  if battery is not None:
    battery = bool(battery)
  battery_v = _first_float(data, "battery_V", "battery_v")
  if battery_v is None:
    battery_mv = _first_float(data, "battery_mV", "battery_mv")
    if battery_mv is not None:
      battery_v = battery_mv / 1000.0

  status = data.get("status")
  if status is not None:
    try:
      status = int(status)
    except (TypeError, ValueError):
      status = None

  freq = _safe_float(data.get("freq") or data.get("frequency"))
  if freq and freq > 1e6:
    freq = freq / 1e6

  protocol_id: Optional[int] = None
  proto_raw = data.get("protocol")
  if proto_raw is not None and proto_raw != "":
    try:
      protocol_id = int(proto_raw)
    except (TypeError, ValueError):
      protocol_id = None
  decoder = format_rtl433_decoder(protocol_id, model)

  # Flex catch-all: stock library missed the burst, but Manchester bits carry the OE ID.
  is_flex = (
    "rows" in data
    or "codes" in data
    or model.upper().startswith("HAMATONOE")
    or "FSK_MC" in model.upper()
    or model in {"ConflictTPMS", "HamatonOE-FSK_MC"}
  )
  if is_flex and (not sensor_id or not protocol_id):
    blob = _flex_hex_blob(data)
    flex_id = _extract_id_from_flex_hex(blob)
    if flex_id:
      sensor_id = sensor_id or flex_id
      if not sensor_type:
        sensor_type = "TPMS"
      decoder = "[flex] Hamaton/OE FSK_MC TPMS"
      if temp_c is None or pressure_psi is None:
        ft, fp = _parse_flex_telemetry(blob, sensor_id)
        if temp_c is None:
          temp_c = ft
        if pressure_psi is None:
          pressure_psi = fp

  return TelemetryReading(
    sensor_id=sensor_id,
    model=model,
    sensor_type=sensor_type or ("TPMS" if is_flex else sensor_type),
    pressure_psi=pressure_psi,
    pressure_hpa=pressure_hpa,
    temperature_c=temp_c,
    battery_ok=battery,
    battery_voltage_v=battery_v,
    status=status,
    raw=data,
    frequency_mhz=freq,
    decoder=decoder,
    protocol_id=protocol_id,
  )


class Rtl433Runner:
  def __init__(
    self,
    on_reading: Callable[[TelemetryReading], None],
    on_log: Callable[[str], None],
    on_state_change: Callable[[bool], None],
  ):
    self.on_reading = on_reading
    self.on_log = on_log
    self.on_state_change = on_state_change
    self._process: Optional[subprocess.Popen] = None
    self._thread: Optional[threading.Thread] = None
    self._stop_event = threading.Event()
    self._running = False
    self.tpms_only = True
    self.iq_path: Optional[str] = None
    self._tpms_decode_count = 0
    self._skip_log_count = 0
    self._raw_log_count = 0

  @property
  def is_running(self) -> bool:
    return self._running

  def build_command(
    self,
    preset_name: str,
    custom_freq_mhz: Optional[float] = None,
    gain: str = "auto",
    ppm: int = 0,
    device_index: int = 0,
    units: str = "customary",
    iq_path: Optional[str] = None,
  ) -> List[str]:
    exe = get_rtl433_exe()
    preset = FREQUENCY_PRESETS.get(preset_name, FREQUENCY_PRESETS["433 MHz — EU / Asia TPMS"])

    cmd = [
      str(exe), "-d", str(device_index), "-F", "json",
      "-M", "time:iso", "-M", "level", "-M", "protocol",
    ]

    if units in ("si", "customary"):
      cmd.extend(["-C", units])

    freqs = list(preset["frequencies"])
    if preset.get("custom") and custom_freq_mhz:
      freqs = [f"{custom_freq_mhz}M"]

    for f in freqs:
      cmd.extend(["-f", f])

    hop = preset.get("hop_interval")
    if hop and len(freqs) > 1:
      cmd.extend(["-H", str(hop)])

    if gain and str(gain).lower() != "auto":
      cmd.extend(["-g", str(gain)])

    if ppm:
      cmd.extend(["-p", str(ppm)])

    # Same sample rate for live decode and IQ write so offline replay matches live counts.
    sample_rate = int(preset.get("sample_rate") or 1_000_000)
    cmd.extend(["-s", str(sample_rate)])

    # Autolevel only — minmax can swallow short TPMS bursts.
    cmd.extend(["-Y", "autolevel"])

    # TPMS-only mode: enable only TPMS decoders so the CPU keeps up and fewer
    # unique Sensor IDs are dropped. Full catalog when TPMS-only is off.
    if self.tpms_only:
      cmd.extend(rtl433_tpms_decoder_flags(exe))
    else:
      cmd.extend(rtl433_full_decoder_flags(exe))

    # No flex / guessed decoders — only stock rtl_433 library protocols.

    if iq_path:
      path = Path(iq_path)
      path.parent.mkdir(parents=True, exist_ok=True)
      cmd.extend(["-w", str(path)])

    return cmd

  def start(
    self,
    preset_name: str,
    custom_freq_mhz: Optional[float] = None,
    gain: str = "auto",
    ppm: int = 0,
    device_index: int = 0,
    units: str = "customary",
    record_iq: bool = False,
  ) -> bool:
    if self._running:
      self.stop()

    exe = get_rtl433_exe()
    if not exe.exists():
      self.on_log("ERROR: rtl_433 not found. Complete setup first.")
      return False

    iq_path = None
    self.iq_path = None
    self._tpms_decode_count = 0
    if record_iq:
      stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
      iq_file = results_dir() / "iq" / f"sdr_session_{stamp}.cu8"
      iq_path = str(iq_file)
      self.iq_path = iq_path

    cmd = self.build_command(
      preset_name, custom_freq_mhz, gain, ppm, device_index, units, iq_path=iq_path
    )
    self.on_log(rtl433_decoder_enablement(exe, tpms_only=self.tpms_only))
    self.on_log(f"Starting: {compact_rtl433_command(cmd)}")
    if not record_iq:
      self.on_log("IQ recording OFF (recommended for max unique Sensor IDs)")
    if iq_path:
      self.on_log(
        f"IQ recording ON @ full sample rate → {iq_path} "
        f"(kept after stop; replay: rtl_433-rtlsdr -r <file.cu8> -F json)"
      )

    try:
      self._stop_event.clear()
      # An rtl_433 orphaned by a previous session keeps the dongle claimed.
      try:
        from tpms_bench.rtl433 import free_dongle

        if not self._running:
          free_dongle()
          time.sleep(1.2)
      except Exception:
        pass
      workdir = exe.parent if exe.parent.is_dir() else get_rtl433_dir()
      env = os.environ.copy()
      env["PATH"] = str(workdir) + os.pathsep + env.get("PATH", "")
      launch = list(cmd)
      stdbuf = shutil.which("stdbuf")
      if stdbuf and os.name != "nt":
        launch = [stdbuf, "-oL", "-eL", *cmd]
      popen_kwargs: Dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "cwd": str(workdir),
        "env": env,
      }
      if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
      self._process = subprocess.Popen(launch, **popen_kwargs)
      # Catch immediate device-busy / crash before the UI shows RUNNING.
      time.sleep(0.15)
      if self._process.poll() is not None:
        code = self._process.returncode
        err_tail = ""
        try:
          err_tail = (self._process.stderr.read() or "").strip()
        except Exception:
          pass
        detail = err_tail.splitlines()[-1] if err_tail else f"exit code {code}"
        if "usb_open" in err_tail.lower() or code in (1, 2):
          detail = (
            f"{detail} — dongle busy or not found. Close other SDR apps "
            "(only one TPMS Suite window) and unplug/replug the RTL-SDR."
          )
        self.on_log(f"ERROR: rtl_433 exited immediately: {detail}")
        if err_tail:
          for line in err_tail.splitlines()[-8:]:
            self.on_log(line)
        self._process = None
        self._running = False
        self.on_state_change(False)
        return False

      self._running = True
      self.on_state_change(True)

      self._thread = threading.Thread(target=self._read_output, daemon=True)
      self._thread.start()

      stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
      stderr_thread.start()
      return True
    except Exception as exc:
      self.on_log(f"ERROR: Failed to start rtl_433: {exc}")
      self._running = False
      self.on_state_change(False)
      return False

  @staticmethod
  def _stderr_worth_logging(text: str) -> bool:
    """Keep real problems; drop rtl_433 banner/status that looks like 'errors' in the UI."""
    low = text.lower()
    # Always surface device / open / decode failures.
    if any(
      key in low
      for key in (
        "usb_open",
        "failed",
        "error:",
        "fatal",
        "no supported devices",
        "busy",
        "cannot open",
        "not found",
        "permission",
      )
    ):
      return True
    # Ignore normal startup chatter (includes the '-F log … errors in the console' tip).
    noise_prefixes = (
      "rtl_433 version",
      "use \"-f log\"",
      "use '-f log'",
      "found rafael",
      "exact sample rate",
      "allocating ",
      "tuned to ",
      "sampling at ",
      "detaching kernel driver",
    )
    if any(low.startswith(p) for p in noise_prefixes):
      return False
    if "messages, warnings, and errors" in low:
      return False
    if "pll not locked" in low or "pll" in low:
      return False
    # Other stderr is usually useful (tuner notes, dwindling buffers, etc.) — keep briefly.
    return True

  def _read_stderr(self) -> None:
    proc = self._process
    if not proc or not proc.stderr:
      return
    try:
      while True:
        if self._stop_event.is_set():
          break
        line = proc.stderr.readline()
        if line == "":
          if proc.poll() is not None:
            break
          continue
        text = line.strip()
        if text and self._stderr_worth_logging(text):
          # Mark real failures so the Activity Terminal paints them red.
          level_hint = text
          if any(k in text.lower() for k in ("usb_open", "failed", "error", "fatal", "cannot open")):
            if not text.upper().startswith("ERROR"):
              level_hint = f"ERROR: {text}"
          self.on_log(level_hint)
    except Exception:
      pass

  def _read_output(self) -> None:
    proc = self._process
    if not proc or not proc.stdout:
      return
    try:
      while True:
        if self._stop_event.is_set():
          break
        line = proc.stdout.readline()
        if line == "":
          if proc.poll() is not None:
            break
          continue
        stripped = line.strip()
        if not stripped:
          continue
        reading = parse_rtl433_json(line)
        if reading is None:
          self._raw_log_count += 1
          if self._raw_log_count <= 8 or self._raw_log_count % 25 == 0:
            self.on_log(f"RAW  {stripped[:160]}")
          continue
        # Show every decoded packet. TPMS-only only limits which -R decoders
        # are enabled — it must not drop a valid JSON reading.
        self._tpms_decode_count += 1
        if self._tpms_decode_count <= 3:
          self.on_log(
            f"SDR packet {self._tpms_decode_count}: "
            f"{reading.display_decoder} ID {reading.sensor_id or '—'}"
          )
        self.on_reading(reading)
    except Exception as exc:
      self.on_log(f"Read error: {exc}")
    finally:
      self._running = False
      self.on_state_change(False)

  def stop(self) -> None:
    self._stop_event.set()
    if self._process:
      try:
        self._process.terminate()
        self._process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        self._process.kill()
      except Exception:
        pass
      self._process = None
    self._running = False
    self.on_state_change(False)
    self._finalize_iq_file()

  def _finalize_iq_file(self) -> None:
    """Keep non-empty IQ after stop so IQ/URH replay can match the live session."""
    if not self.iq_path:
      return
    try:
      path = Path(self.iq_path)
      if not path.exists():
        self.on_log(f"IQ file was not created: {path}")
        return
      size = path.stat().st_size
      if size <= 0:
        path.unlink(missing_ok=True)
        self.on_log(f"IQ discarded (empty): {path.name}")
        self.iq_path = None
        return
      mb = size / (1024 * 1024)
      self.on_log(
        f"IQ kept ({mb:.1f} MB, {self._tpms_decode_count} live TPMS packet(s)): {path} — "
        f"open on IQ / URH tab or: rtl_433-rtlsdr -r \"{path.name}\" -F json"
      )
    except Exception as exc:
      self.on_log(f"IQ status check failed: {exc}")
    self.on_log("Stopped listening.")
