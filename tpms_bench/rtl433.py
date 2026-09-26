"""Launch rtl_433, capture IQ, wait for a JSON packet."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SdrPacket:
    protocol: str | None
    sensor_id: str | None
    pressure: float | None
    temperature: float | None
    battery: str | None
    raw_json: dict = field(default_factory=dict)


@dataclass
class SdrCaptureResult:
    available: bool
    packets: list[SdrPacket]
    iq_path: str | None
    error: str | None = None


def rtl_433_path() -> str | None:
    """Prefer the RTL-SDR build; never pick a file-only rtl_433.exe over it."""
    try:
        from config import get_rtl433_exe

        bundled = get_rtl433_exe()
        if bundled.is_file():
            return str(bundled)
    except Exception:
        pass

    # Source tree / known vendor locations (when config is not on sys.path).
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[1] / "sdr_ui" / "vendor" / "rtl_433" / "rtl_433-rtlsdr.exe",
        here.parents[1] / "sdr_ui" / "vendor" / "rtl_433" / "rtl_433.exe",
        here.parents[1] / "vendor" / "rtl_433" / "rtl_433-rtlsdr.exe",
        here.parents[1] / "vendor" / "rtl_433" / "rtl_433.exe",
    ):
        if candidate.is_file():
            return str(candidate)

    for name in ("rtl_433-rtlsdr", "rtl_433-rtlsdr.exe", "rtl_433", "rtl_433.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def parse_freq_hz(value: object, default_hz: int = 433_920_000) -> int:
    """Parse Excel/UI frequency text into Hz for rtl_433 -f."""
    if value is None:
        return default_hz
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        if num >= 1_000_000:
            return int(num)
        if num > 100:  # MHz
            return int(round(num * 1_000_000))
        return default_hz
    text = str(value).strip().lower().replace(",", ".")
    if not text or text in {"na", "n/a", "none", "-", "—"}:
        return default_hz
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ghz|mhz|khz|hz)?", text)
    if not match:
        return default_hz
    num = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit == "ghz":
        return int(round(num * 1_000_000_000))
    if unit == "khz":
        return int(round(num * 1_000))
    if unit == "hz":
        return int(round(num))
    if unit == "mhz" or num < 10_000:
        return int(round(num * 1_000_000))
    return int(round(num))


def sdr_present() -> bool:
    if shutil.which("rtl_test"):
        probe = subprocess.run(
            ["rtl_test", "-t"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        text = (probe.stdout or "") + (probe.stderr or "")
        if "No supported devices found" in text or probe.returncode != 0:
            return False
        return True
    # rtl_433 itself fails fast when no dongle is present.
    binary = rtl_433_path()
    if not binary:
        return False
    probe = subprocess.run(
        [binary, "-T", "1"],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    text = (probe.stdout or "") + (probe.stderr or "")
    if "No input drivers" in text and "RTL-SDR" not in text:
        return False
    if "No supported devices found" in text or "usb_claim_interface error" in text:
        return False
    return probe.returncode == 0 or "Tuned to" in text or "Using device" in text


def parse_json_lines(text: str) -> list[SdrPacket]:
    packets: list[SdrPacket] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        sensor_id = data.get("id") or data.get("ID") or data.get("sensor_id") or data.get("id_str")
        if sensor_id is not None:
            raw = str(sensor_id).replace(" ", "")
            if raw.lower().startswith("0x"):
                raw = raw[2:]
            if raw.isdigit():
                try:
                    sensor_id = f"{int(raw) & 0xFFFFFFFF:08X}"
                except ValueError:
                    sensor_id = raw.upper()
            else:
                try:
                    sensor_id = f"{int(raw, 16) & 0xFFFFFFFF:08X}"
                except ValueError:
                    sensor_id = raw.upper()
        model = data.get("model") or data.get("type")
        proto_raw = data.get("protocol")
        protocol_id = None
        if proto_raw is not None and proto_raw != "":
            try:
                protocol_id = int(proto_raw)
            except (TypeError, ValueError):
                protocol_id = None
        try:
            from config import format_rtl433_decoder

            protocol = format_rtl433_decoder(protocol_id, str(model) if model else None)
        except Exception:
            if protocol_id is not None and model:
                protocol = f"[{protocol_id}] {model}"
            else:
                protocol = model
        packets.append(
            SdrPacket(
                protocol=protocol,
                sensor_id=sensor_id,
                pressure=data.get("pressure_kPa") or data.get("pressure_BAR") or data.get("pressure"),
                temperature=data.get("temperature_C") or data.get("temperature"),
                battery=str(data["battery_ok"]) if "battery_ok" in data else data.get("battery"),
                raw_json=data,
            )
        )
    return packets


def _extra_protocol_flags() -> list[str]:
    """Enable every decoder in the current rtl_433 library (including disabled-by-default)."""
    binary = rtl_433_path()
    exe = Path(binary) if binary else None
    try:
        from config import rtl433_full_decoder_flags

        return rtl433_full_decoder_flags(exe)
    except Exception:
        try:
            from sdr_ui.config import rtl433_full_decoder_flags

            return rtl433_full_decoder_flags(exe)
        except Exception:
            ids = (
                6, 7, 13, 14, 24, 37, 48, 61, 62, 64, 72, 86, 101, 106, 107, 117, 118, 123,
                129, 150, 162, 169, 198, 200, 216, 233, 242, 245, 248, 260, 270,
            )
            flags: list[str] = []
            for proto_id in ids:
                flags.extend(["-R", f"-{proto_id}", "-R", str(proto_id)])
            return flags


def capture_command(
    iq_path: Path,
    frequency_hz: int = 433920000,
    duration_s: float = 15.0,
    *,
    sample_rate: int = 1_000_000,
) -> list[str] | None:
    binary = rtl_433_path()
    if not binary:
        return None
    iq_path.parent.mkdir(parents=True, exist_ok=True)
    rate = max(250_000, int(sample_rate))
    cmd = [
        binary,
        "-f",
        str(frequency_hz),
        "-T",
        str(int(duration_s)),
        "-F",
        "json",
        "-s",
        str(rate),
        # Match the SDR Receiver tab — auto gain is too low for a bench sensor.
        "-g",
        "40",
        "-Y",
        "autolevel",
        "-Y",
        "minmax",
        "-Y",
        "magest",
        "-M",
        "level",
        "-M",
        "protocol",
        "-w",
        str(iq_path),
    ]
    cmd.extend(_extra_protocol_flags())
    return cmd


def free_dongle() -> None:
    """Kill an rtl_433 left behind by a previous run so the dongle is claimable."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "rtl_433.exe"],
                capture_output=True,
                timeout=8,
                check=False,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "rtl_433"],
                capture_output=True,
                timeout=8,
                check=False,
            )
    except Exception:
        pass


def start_capture(
    iq_path: Path,
    frequency_hz: int = 433920000,
    duration_s: float = 15.0,
) -> subprocess.Popen | SdrCaptureResult:
    cmd = capture_command(iq_path, frequency_hz, duration_s, sample_rate=1_000_000)
    if not cmd:
        return SdrCaptureResult(False, [], None, "rtl_433 not installed")
    free_dongle()
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        return SdrCaptureResult(False, [], None, f"could not start rtl_433: {error}")


def finish_capture(
    proc: subprocess.Popen | SdrCaptureResult,
    iq_path: Path,
    extra_wait_s: float = 5.0,
) -> SdrCaptureResult:
    if isinstance(proc, SdrCaptureResult):
        return proc
    try:
        stdout, stderr = proc.communicate(timeout=extra_wait_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        extra = "rtl_433 timed out"
    else:
        extra = None
    combined = (stdout or "") + "\n" + (stderr or "")
    if "No supported devices found" in combined:
        _discard_iq(iq_path)
        return SdrCaptureResult(False, [], None, "no SDR receiver found")
    packets = parse_json_lines(stdout or "")
    iq: str | None = None
    if iq_path.exists() and iq_path.stat().st_size > 0:
        if packets:
            # Already decoded live — drop IQ to save disk.
            _discard_iq(iq_path)
            iq = None
        else:
            iq = str(iq_path)
    else:
        _discard_iq(iq_path)
    error = extra
    if error is None and not packets:
        if iq:
            error = f"no decode in rtl_433 JSON — IQ kept for replay: {iq}"
        else:
            error = "no decode; IQ file empty or missing"
    return SdrCaptureResult(True, packets, iq, error)


def _discard_iq(iq_path: Path) -> None:
    try:
        if iq_path.exists():
            iq_path.unlink()
    except OSError:
        pass


def capture(
    iq_path: Path,
    frequency_hz: int = 433920000,
    duration_s: float = 15.0,
) -> SdrCaptureResult:
    proc = start_capture(iq_path, frequency_hz, duration_s)
    return finish_capture(proc, iq_path, extra_wait_s=duration_s + 10)
