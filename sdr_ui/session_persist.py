"""Serialize / restore SDR live session so restarts keep unique IDs."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rtl433_runner import TelemetryReading

try:
  from tpms_bench.paths import results_dir
except Exception:  # pragma: no cover
  def results_dir() -> Path:
    folder = Path(__file__).resolve().parents[1] / "results"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


SESSION_FILE_NAME = "sdr_session_live.json"
_write_lock = threading.Lock()


def session_path() -> Path:
  return results_dir() / SESSION_FILE_NAME


def _iso(ts: Optional[datetime]) -> Optional[str]:
  if ts is None:
    return None
  try:
    return ts.isoformat(timespec="seconds")
  except Exception:
    return str(ts)


def _parse_ts(value: Any) -> datetime:
  if isinstance(value, datetime):
    return value
  text = str(value or "").strip()
  if not text:
    return datetime.now()
  try:
    return datetime.fromisoformat(text)
  except Exception:
    return datetime.now()


def reading_to_dict(reading: TelemetryReading) -> Dict[str, Any]:
  return {
    "sensor_id": reading.sensor_id,
    "model": reading.model,
    "sensor_type": reading.sensor_type,
    "pressure_psi": reading.pressure_psi,
    "pressure_hpa": reading.pressure_hpa,
    "temperature_c": reading.temperature_c,
    "battery_ok": reading.battery_ok,
    "battery_voltage_v": reading.battery_voltage_v,
    "rssi_db": reading.rssi_db,
    "status": reading.status,
    "raw": reading.raw if isinstance(reading.raw, dict) else {},
    "timestamp": _iso(reading.timestamp),
    "frequency_mhz": reading.frequency_mhz,
    "acquire_seconds": reading.acquire_seconds,
    "decoder": reading.decoder,
    "protocol_id": reading.protocol_id,
  }


def reading_from_dict(data: Dict[str, Any]) -> TelemetryReading:
  return TelemetryReading(
    sensor_id=str(data.get("sensor_id") or ""),
    model=str(data.get("model") or ""),
    sensor_type=str(data.get("sensor_type") or ""),
    pressure_psi=data.get("pressure_psi"),
    pressure_hpa=data.get("pressure_hpa"),
    temperature_c=data.get("temperature_c"),
    battery_ok=data.get("battery_ok"),
    battery_voltage_v=data.get("battery_voltage_v"),
    rssi_db=data.get("rssi_db"),
    status=data.get("status"),
    raw=data.get("raw") if isinstance(data.get("raw"), dict) else {},
    timestamp=_parse_ts(data.get("timestamp")),
    frequency_mhz=data.get("frequency_mhz"),
    acquire_seconds=data.get("acquire_seconds"),
    decoder=str(data.get("decoder") or ""),
    protocol_id=data.get("protocol_id"),
  )


def save_session(
  *,
  sensors: Dict[str, TelemetryReading],
  sensor_reads: Dict[str, int],
  sensor_first_seen: Dict[str, datetime],
  total_readings: int,
  session_start: Optional[datetime],
  path: Optional[Path] = None,
) -> Path:
  """Atomically write the live SDR session snapshot."""
  dest = path or session_path()
  payload = {
    "version": 1,
    "saved_at": _iso(datetime.now()),
    "total_readings": int(total_readings),
    "session_start": _iso(session_start),
    "sensors": {
      sid: {
        "reading": reading_to_dict(reading),
        "reads": int(sensor_reads.get(sid, 1)),
        "first_seen": _iso(sensor_first_seen.get(sid) or reading.timestamp),
      }
      for sid, reading in sensors.items()
    },
  }
  text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
  dest.parent.mkdir(parents=True, exist_ok=True)
  tmp = dest.with_suffix(".tmp")
  with _write_lock:
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)
  return dest


def load_session(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
  src = path or session_path()
  if not src.is_file():
    return None
  try:
    data = json.loads(src.read_text(encoding="utf-8"))
  except Exception:
    return None
  if not isinstance(data, dict):
    return None
  sensors_raw = data.get("sensors")
  if not isinstance(sensors_raw, dict) or not sensors_raw:
    return None

  sensors: Dict[str, TelemetryReading] = {}
  sensor_reads: Dict[str, int] = {}
  sensor_first_seen: Dict[str, datetime] = {}
  for sid, entry in sensors_raw.items():
    if not isinstance(entry, dict):
      continue
    reading_data = entry.get("reading") if isinstance(entry.get("reading"), dict) else entry
    try:
      reading = reading_from_dict(reading_data)
    except Exception:
      continue
    key = (reading.sensor_id or str(sid)).strip()
    if not key:
      continue
    sensors[key] = reading
    sensor_reads[key] = max(1, int(entry.get("reads") or 1))
    sensor_first_seen[key] = _parse_ts(entry.get("first_seen") or reading.timestamp)

  if not sensors:
    return None

  return {
    "total_readings": int(data.get("total_readings") or len(sensors)),
    "session_start": _parse_ts(data.get("session_start")) if data.get("session_start") else None,
    "sensors": sensors,
    "sensor_reads": sensor_reads,
    "sensor_first_seen": sensor_first_seen,
  }


def clear_session_file(path: Optional[Path] = None) -> None:
  src = path or session_path()
  try:
    if src.is_file():
      src.unlink()
  except Exception:
    pass
