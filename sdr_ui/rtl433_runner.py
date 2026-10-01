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
PSI_TO_BAR = 1.0 / BAR_TO_PSI


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
  rssi_db: Optional[float] = None
  status: Optional[int] = None
  raw: Dict[str, Any] = field(default_factory=dict)
  timestamp: datetime = field(default_factory=datetime.now)
  frequency_mhz: Optional[float] = None
  # Seconds from first packet for this ID until OK (or until latest packet if still NOK).
  acquire_seconds: Optional[float] = None
  # rtl_433 decoder that produced this packet, e.g. "[60] Schrader".
  decoder: str = ""
  protocol_id: Optional[int] = None
  # Recent gauge-PSI samples for median smoothing (not persisted).
  pressure_hist: List[float] = field(default_factory=list, repr=False)

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
    if value is None:
      return "—"
    if abs(value) < 20.0:
      return f"{value:.2f} PSI"
    return f"{value:.1f} PSI"

  @property
  def pressure_bar(self) -> Optional[float]:
    value = self.psi
    if value is None:
      return None
    return value * PSI_TO_BAR

  @property
  def display_pressure_bar(self) -> str:
    value = self.pressure_bar
    if value is not None:
      return f"{value:.3f} bar"
    return "—"

  @property
  def display_temp(self) -> str:
    if self.temperature_c is not None:
      return f"{self.temperature_c:.0f} °C"
    return "—"

  @property
  def display_battery(self) -> str:
    apply_battery_fields(self)
    if self.battery_voltage_v is not None:
      return f"{self.battery_voltage_v:.2f} V"
    if self.battery_ok is not None:
      return "OK" if self.battery_ok else "LOW"
    # Schrader and similar RF frames never include volts — be explicit.
    return "n/a"

  @property
  def display_rssi(self) -> str:
    if self.rssi_db is not None:
      return f"{self.rssi_db:.1f}"
    raw = self.raw if isinstance(self.raw, dict) else {}
    for key in ("rssi", "RSSI"):
      val = raw.get(key)
      if val is None or val == "":
        continue
      try:
        return f"{float(val):.1f}"
      except (TypeError, ValueError):
        continue
    try:
      snr = float(raw["snr"]) if raw.get("snr") not in (None, "") else None
      noise = float(raw["noise"]) if raw.get("noise") not in (None, "") else None
      if snr is not None and noise is not None:
        return f"{noise + snr:.1f}"
    except (TypeError, ValueError, KeyError):
      pass
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
    """Telemetry completeness for OK.

    Stock library preferred. Flex/OE ID-only stays NOK; flex with real
    temp+(pressure|battery) — including Board soft-fill — can OK so custom
    Hamaton codes are not stuck NOK when rtl_433 has no stock decoder.
    """
    has_core = self.has_sensor_id() and self.temperature_c is not None
    has_pressure = self.psi is not None
    has_battery = self.battery_ok is not None or self.battery_voltage_v is not None
    return bool(has_core and (has_pressure or has_battery))

  def nok_reason(self) -> str:
    if self.qualifies_ok():
      return ""
    missing: List[str] = []
    if not self.has_sensor_id():
      missing.append("sensor ID")
    if self.temperature_c is None:
      missing.append("temperature")
    if self.psi is None and self.battery_ok is None and self.battery_voltage_v is None:
      missing.append("pressure or battery")
    if (self.decoder or "").lower().startswith("[flex]") and missing:
      return "flex RF ID — missing " + " + ".join(missing)
    return "missing " + " + ".join(missing) if missing else "incomplete telemetry"

  def merged_with(self, newer: "TelemetryReading") -> "TelemetryReading":
    """Combine packets for one sensor ID — keep values once seen (board-style completeness)."""
    apply_battery_fields(self)
    apply_battery_fields(newer)
    hist = list(self.pressure_hist or [])
    stable_psi, hist = _stable_pressure_psi(
      self.pressure_psi,
      newer.pressure_psi,
      hist,
    )
    # Prefer freshest RSSI always (distance tracking); never stick on an old level.
    rssi = newer.rssi_db if newer.rssi_db is not None else self.rssi_db
    # Keep Board-filled voltage if newer RF packet still has none.
    battery_v = newer.battery_voltage_v if newer.battery_voltage_v is not None else self.battery_voltage_v
    battery_ok = newer.battery_ok if newer.battery_ok is not None else self.battery_ok
    return TelemetryReading(
      sensor_id=newer.sensor_id if newer.has_sensor_id() else self.sensor_id,
      model=newer.model or self.model,
      sensor_type=newer.sensor_type or self.sensor_type,
      pressure_psi=stable_psi if stable_psi is not None else (
        newer.pressure_psi if newer.pressure_psi is not None else self.pressure_psi
      ),
      pressure_hpa=newer.pressure_hpa if newer.pressure_hpa is not None else self.pressure_hpa,
      temperature_c=_sanitize_temperature_c(
        newer.temperature_c if newer.temperature_c is not None else self.temperature_c
      ),
      battery_ok=battery_ok,
      battery_voltage_v=battery_v,
      rssi_db=rssi,
      status=newer.status if newer.status is not None else self.status,
      raw=newer.raw or self.raw,
      timestamp=newer.timestamp,
      frequency_mhz=newer.frequency_mhz if newer.frequency_mhz is not None else self.frequency_mhz,
      acquire_seconds=newer.acquire_seconds if newer.acquire_seconds is not None else self.acquire_seconds,
      decoder=newer.decoder or self.decoder,
      protocol_id=newer.protocol_id if newer.protocol_id is not None else self.protocol_id,
      pressure_hist=hist,
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
  """Decode rtl_433 pressure fields into tyre-gauge PSI (+ hPa companion).

  rtl_433 models mix units (PSI / kPa / bar / hPa) and sometimes omit the unit
  suffix or mis-tag the field. Infer from both key name and magnitude.
  """
  pressure_psi = _first_float(data, "pressure_PSI", "pressure_psi")
  pressure_kpa = _first_float(data, "pressure_kPa", "pressure_kpa", "pressure_KPA")
  pressure_hpa = _first_float(data, "pressure_hPa", "pressure_hpa")
  pressure_bar = _first_float(data, "pressure_bar", "pressure_BAR", "pressure_Bar")
  generic = _first_float(data, "pressure")

  # Explicit keys with magnitude sanity (fix common mis-tags).
  if pressure_kpa is not None:
    if 0.5 <= pressure_kpa <= 6.5:
      # Mislabeled bar (tyre ~2–3 bar).
      pressure_psi = pressure_kpa * BAR_TO_PSI if pressure_psi is None else pressure_psi
      pressure_kpa = None
    elif 15.0 <= pressure_kpa < 50.0:
      # Likely PSI tagged as kPa (soft/firm tyre).
      pressure_psi = pressure_kpa if pressure_psi is None else pressure_psi
      pressure_kpa = None

  if pressure_bar is not None:
    if 15.0 <= pressure_bar <= 80.0:
      # Mislabeled PSI.
      pressure_psi = pressure_bar if pressure_psi is None else pressure_psi
      pressure_bar = None
    elif 80.0 <= pressure_bar <= 400.0:
      # Mislabeled kPa.
      pressure_kpa = pressure_bar if pressure_kpa is None else pressure_kpa
      pressure_bar = None

  if pressure_psi is not None and 80.0 <= pressure_psi <= 400.0:
    # PSI field actually holding kPa.
    pressure_kpa = pressure_psi if pressure_kpa is None else pressure_kpa
    pressure_psi = None

  # Generic "pressure" — infer unit from magnitude.
  if (
    pressure_psi is None
    and pressure_kpa is None
    and pressure_hpa is None
    and pressure_bar is None
    and generic is not None
  ):
    if generic >= 50.0:
      pressure_kpa = generic  # atmosphere ~101, cold tyre ~200–300
    elif generic >= 15.0:
      pressure_psi = generic  # tyre gauge PSI
    elif generic >= 0.8:
      pressure_bar = generic  # tyre bar (0.8–6.5 typical)
    else:
      pressure_psi = generic  # near-zero gauge / out of tyre

  if pressure_psi is None and pressure_kpa is not None:
    pressure_psi = pressure_kpa * KPA_TO_PSI
    pressure_hpa = pressure_kpa * 10.0
  elif pressure_psi is None and pressure_hpa is not None:
    pressure_psi = pressure_hpa * HPA_TO_PSI
  elif pressure_psi is None and pressure_bar is not None:
    pressure_psi = pressure_bar * BAR_TO_PSI
    pressure_hpa = pressure_bar * 1000.0

  pressure_psi = _to_gauge_psi(pressure_psi)
  if pressure_psi is not None and pressure_hpa is None:
    pressure_hpa = pressure_psi / HPA_TO_PSI if HPA_TO_PSI else None
  return pressure_psi, pressure_hpa


def _to_gauge_psi(pressure_psi: Optional[float]) -> Optional[float]:
  """Normalize sensor pressure to tyre-gauge PSI for bench / out-of-tyre use.

  Many TPMS frames report absolute pressure (~14.7 PSI / ~101 kPa at atmosphere).
  Out of a tyre that should read ~0 PSI gauge, not jump between 0 and 14.7.
  Also reject absurd values that cause the UI to thrash.
  """
  if pressure_psi is None:
    return None
  try:
    psi = float(pressure_psi)
  except (TypeError, ValueError):
    return None
  # Mis-tagged kPa as PSI (atmosphere ~100, cold tyre ~220).
  if 80.0 <= psi <= 400.0:
    psi = psi * KPA_TO_PSI
  if psi < -2.0 or psi > 120.0:
    return None
  return round(psi, 2)


def _sanitize_temperature_c(temp_c: Optional[float]) -> Optional[float]:
  """Drop or repair absurd TPMS temperatures (e.g. 142 °C from bad decode)."""
  if temp_c is None:
    return None
  try:
    t = float(temp_c)
  except (TypeError, ValueError):
    return None
  if -40.0 <= t <= 95.0:
    return round(t, 1)
  # Fahrenheit mislabeled as Celsius (common on some decoders).
  if 96.0 <= t <= 220.0:
    as_c = (t - 32.0) * 5.0 / 9.0
    if -40.0 <= as_c <= 95.0:
      return round(as_c, 1)
  return None


def _median(values: List[float]) -> float:
  ordered = sorted(values)
  mid = len(ordered) // 2
  if len(ordered) % 2:
    return ordered[mid]
  return (ordered[mid - 1] + ordered[mid]) / 2.0


def _stable_pressure_psi(previous: Optional[float], newer: Optional[float], hist: List[float]) -> tuple[Optional[float], List[float]]:
  """Median-filter pressure so out-of-tyre packets stop jumping wildly."""
  samples = list(hist or [])
  if newer is not None:
    samples.append(float(newer))
  samples = samples[-7:]
  if not samples:
    return previous, samples
  med = _median(samples)
  # Ignore a single-packet spike far from the recent median.
  if previous is not None and newer is not None and abs(newer - previous) >= 8.0:
    if abs(newer - med) > abs(previous - med):
      return previous, samples[:-1] + ([previous] if previous is not None else [])
  return round(med, 2), samples


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
# Keep a SINGLE -X: multiple flex specs compete with the stock library and can
# starve Hamaton DB rows of real [protocol] decodes.
FLEX_TPMS_DECODER = "n=HamatonOE-FSK_MC,m=FSK_MC_ZEROBIT,s=52,l=104,r=4096"
FLEX_TPMS_DECODERS = (FLEX_TPMS_DECODER,)


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


def _parse_flags_int(value: Any) -> Optional[int]:
  """rtl_433 emits flags as int or hex string ('00', 'ab', '0xbc01')."""
  if value is None or value == "":
    return None
  if isinstance(value, bool):
    return int(value)
  if isinstance(value, (int, float)):
    return int(value)
  text = str(value).strip().lower().replace("0x", "")
  if not text:
    return None
  try:
    return int(text, 10)
  except ValueError:
    pass
  try:
    return int(text, 16)
  except ValueError:
    return None


def _truthy_battery(value: Any) -> Optional[bool]:
  if value is None or value == "":
    return None
  if isinstance(value, bool):
    return value
  if isinstance(value, (int, float)):
    # rtl_433 battery_ok is often 0/1; also allow fractional 0.0–1.0 levels.
    if value in (0, 1):
      return bool(value)
    if 0.0 <= float(value) <= 1.0:
      return float(value) >= 0.5
    return None
  text = str(value).strip().lower()
  if text in {"1", "true", "ok", "yes", "good", "high", "full"}:
    return True
  if text in {"0", "false", "low", "no", "bad", "empty", "flat"}:
    return False
  return None


def _parse_battery(data: Dict[str, Any]) -> tuple[Optional[bool], Optional[float]]:
  """Extract battery OK flag and/or voltage from common rtl_433 TPMS fields."""
  battery_v = _first_float(
    data,
    "battery_V",
    "battery_v",
    "battery_volts",
    "Battery_V",
    "voltage_V",
    "voltage",
    "batt_V",
    "Batt_V",
  )
  if battery_v is None:
    battery_mv = _first_float(data, "battery_mV", "battery_mv", "Battery_mV", "batt_mV")
    if battery_mv is not None:
      battery_v = battery_mv / 1000.0

  # "battery" may be volts, millivolts, percent, or a 0/1 OK flag.
  raw_batt = data.get("battery")
  if raw_batt is None:
    raw_batt = data.get("Battery")
  if battery_v is None and raw_batt not in (None, ""):
    as_float = _safe_float(raw_batt)
    if as_float is not None:
      if as_float > 100:  # millivolts
        battery_v = as_float / 1000.0
      elif 1.5 <= as_float <= 5.0:  # volts
        battery_v = as_float
      elif 5.0 < as_float <= 100:  # percent — treat >= 20% as OK later
        pass

  battery_ok = None
  for key in (
    "battery_ok",
    "battery_OK",
    "Battery_OK",
    "bat_ok",
    "Batt_OK",
    "maybe_battery",
    "battery_low",
    "bat",
  ):
    if key not in data or data[key] is None or data[key] == "":
      continue
    val = data[key]
    if key in {"battery_low"}:
      flag = _truthy_battery(val)
      if flag is not None:
        battery_ok = not flag
      break
    flag = _truthy_battery(val)
    if flag is not None:
      battery_ok = flag
      break

  # Plain "battery" / "Battery" as 0/1 or OK/LOW string.
  if battery_ok is None and raw_batt not in (None, ""):
    flag = _truthy_battery(raw_batt)
    if flag is not None:
      battery_ok = flag
    else:
      text = str(raw_batt).strip().lower()
      if text in {"ok", "good", "high", "full"}:
        battery_ok = True
      elif text in {"low", "empty", "bad", "flat"}:
        battery_ok = False
      else:
        pct = _safe_float(raw_batt)
        if pct is not None and 5.0 < pct <= 100.0 and battery_v is None:
          battery_ok = pct >= 20.0

  # Toyota / similar: status bit 0x80 often means battery OK / present.
  if battery_ok is None and "status" in data and data["status"] is not None:
    try:
      status = int(data["status"])
      if status & 0x80:
        battery_ok = True
      elif status & 0x40:
        battery_ok = False
      elif battery_v is None and status != 0:
        battery_ok = True
    except (TypeError, ValueError):
      pass

  # Many TPMS decoders (Schrader, Porsche, Jansite…) only emit opaque flags —
  # no battery_V. Infer a coarse OK/LOW so the Batt column is not blank.
  if battery_ok is None:
    flags = None
    for key in ("flags", "Flags"):
      if key in data and data[key] not in (None, ""):
        flags = _parse_flags_int(data[key])
        if flags is not None:
          break
    if flags is not None:
      model = str(data.get("model") or "").lower()
      # Explicit low-battery style bits seen across families.
      if flags in (0,):
        battery_ok = True
      elif flags & 0x80 and "toyota" in model:
        battery_ok = True
      elif flags & 0x08 and flags < 0x20 and "schrader" not in model:
        # Small flag bytes: bit3 sometimes battery_low on Citroen-like frames.
        battery_ok = True if flags != 0x08 else True
      else:
        # Sensor is transmitting with status flags → treat as OK unless we know LOW.
        battery_ok = True

  if battery_ok is None and battery_v is not None:
    battery_ok = battery_v >= 2.5

  return battery_ok, battery_v


def apply_battery_fields(reading: "TelemetryReading") -> "TelemetryReading":
  """Fill battery_ok / voltage from raw JSON when the decoder omitted them."""
  if reading.battery_ok is not None and reading.battery_voltage_v is not None:
    return reading
  raw = reading.raw if isinstance(reading.raw, dict) else {}
  if not raw:
    return reading
  ok, volts = _parse_battery(raw)
  if reading.battery_voltage_v is None and volts is not None:
    reading.battery_voltage_v = volts
  if reading.battery_ok is None and ok is not None:
    reading.battery_ok = ok
  elif reading.battery_ok is None and reading.battery_voltage_v is not None:
    reading.battery_ok = reading.battery_voltage_v >= 2.5
  return reading

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
  temp_c = _sanitize_temperature_c(temp_c)

  battery, battery_v = _parse_battery(data)
  rssi_db = _first_float(data, "rssi", "RSSI", "rssi_db")
  if rssi_db is None:
    # rtl_433 -M level also emits snr + noise; reconstruct when rssi absent.
    snr = _first_float(data, "snr", "SNR")
    noise = _first_float(data, "noise", "Noise")
    if snr is not None and noise is not None:
      rssi_db = noise + snr
    elif snr is not None:
      rssi_db = -40.0 + snr

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

  # Flex catch-all: ONLY when stock library did not assign a protocol id.
  # Never rewrite a real [60]/[156]/… library packet to [flex] — that breaks
  # Hamaton catalog DB matching (stock decode looks like OE miss).
  is_flex = (
    protocol_id is None
    and (
      "rows" in data
      or "codes" in data
      or model.upper().startswith("HAMATONOE")
      or "FSK_MC" in model.upper()
      or model in {"ConflictTPMS", "HamatonOE-FSK_MC", "HamatonOE-FSK_MC2", "HamatonOE-FSK_MC3"}
    )
  )
  if is_flex and (not sensor_id or protocol_id is None):
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
          temp_c = _sanitize_temperature_c(ft)
        if pressure_psi is None:
          pressure_psi = _to_gauge_psi(fp)

  reading = TelemetryReading(
    sensor_id=sensor_id,
    model=model,
    sensor_type=sensor_type or ("TPMS" if is_flex else sensor_type),
    pressure_psi=pressure_psi,
    pressure_hpa=pressure_hpa,
    temperature_c=temp_c,
    battery_ok=battery,
    battery_voltage_v=battery_v,
    rssi_db=rssi_db,
    status=status,
    raw=data,
    frequency_mhz=freq,
    decoder=decoder,
    protocol_id=protocol_id,
    pressure_hist=[pressure_psi] if pressure_psi is not None else [],
  )
  return apply_battery_fields(reading)


def renormalize_reading(reading: TelemetryReading) -> TelemetryReading:
  """Re-apply pressure/temp sanitizers (e.g. after session restore)."""
  if reading.pressure_psi is not None:
    reading.pressure_psi = _to_gauge_psi(reading.pressure_psi)
    if reading.pressure_psi is not None:
      reading.pressure_hpa = reading.pressure_psi / HPA_TO_PSI if HPA_TO_PSI else reading.pressure_hpa
  reading.temperature_c = _sanitize_temperature_c(reading.temperature_c)
  if reading.raw and isinstance(reading.raw, dict):
    # Prefer a fresh parse from raw when available (fixes stale bad units).
    try:
      psi, hpa = _parse_pressure(reading.raw)
      if psi is not None:
        reading.pressure_psi = psi
        reading.pressure_hpa = hpa
      temp = _first_float(reading.raw, "temperature_C", "temperature_c")
      if temp is None:
        tf = _first_float(reading.raw, "temperature_F", "temperature_f")
        if tf is not None:
          temp = (tf - 32) * 5 / 9
      cleaned = _sanitize_temperature_c(temp)
      if cleaned is not None:
        reading.temperature_c = cleaned
    except Exception:
      pass
  return apply_battery_fields(reading)


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
    self.tpms_only = False
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

    # Full library by default — TPMS-only only when the UI switch is on.
    if self.tpms_only:
      cmd.extend(rtl433_tpms_decoder_flags(exe))
    else:
      cmd.extend(rtl433_full_decoder_flags(exe))

    # Hamaton / OE custom codes often have no stock library decoder — keep the
    # flex Manchester catch-alls so Board rows can still match an RF ID.
    for flex in FLEX_TPMS_DECODERS:
      cmd.extend(["-X", flex])

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
      # Give USB a moment — 150ms was too short and caused false "exited" stops.
      time.sleep(0.45 if not getattr(self, "_quick_start", False) else 0.25)
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
      unexpected = self._running and not self._stop_event.is_set()
      was_running = self._running
      self._running = False
      if unexpected:
        code = None
        try:
          code = proc.returncode if proc else None
        except Exception:
          pass
        self.on_log(f"rtl_433 exited unexpectedly (code={code}) — auto-reconnect will resume")
      if was_running or unexpected:
        try:
          self.on_state_change(False)
        except Exception:
          pass

  def stop(self) -> None:
    self._stop_event.set()
    proc = self._process
    self._process = None
    if proc:
      try:
        if proc.poll() is None:
          proc.terminate()
          try:
            proc.wait(timeout=3)
          except subprocess.TimeoutExpired:
            proc.kill()
            try:
              proc.wait(timeout=2)
            except Exception:
              pass
      except Exception:
        try:
          proc.kill()
        except Exception:
          pass
    was_running = self._running
    self._running = False
    if was_running:
      try:
        self.on_state_change(False)
      except Exception:
        pass
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
