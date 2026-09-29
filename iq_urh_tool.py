"""IQ → URH → Excel: helpers + embeddable suite tab (+ standalone window).

Flow
----
1. Choose a captured IQ file (.cu8 / .complex16u / .complex / .wav).
2. Prepare a URH-friendly copy (.complex16u when the source is .cu8).
3. Launch Universal Radio Hacker for visual demodulation.
4. Replay IQ through rtl_433 and write suite-format SDR Excel.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
for path in (ROOT, ROOT / "sdr_ui"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

import customtkinter as ctk

from config import (
    APP_NAME,
    APP_VERSION,
    compact_rtl433_command,
    get_rtl433_exe,
    rtl433_decoder_enablement,
    rtl433_full_decoder_flags,
)
from rtl433_runner import TelemetryReading, parse_rtl433_json
from session_export import export_session_excel
from themes import (
    COLOR_BG,
    COLOR_BG_CARD,
    COLOR_BORDER,
    COLOR_BTN_EXPORT,
    COLOR_BTN_EXPORT_HOVER,
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

IQ_EXTENSIONS = {".cu8", ".complex16u", ".complex16s", ".complex", ".complex32u", ".complex32s", ".wav"}
# Ahmad / bench guidance: 1024k is enough for IQ replay; carrier 432.92 MHz FSK.
DEFAULT_SAMPLE_RATE = 1_024_000
DEFAULT_FREQ_MHZ = 432.92
REPLAY_SAMPLE_RATES = (1_024_000, 1_000_000, 500_000, 250_000)
AUTO_RATE_MAX_BYTES = 80 * 1024 * 1024  # 80 MB


def find_urh() -> Optional[Path]:
    """Locate Universal Radio Hacker executable or launcher script."""
    for name in ("urh", "urh.exe", "urh.cmd", "urh.bat"):
        found = shutil.which(name)
        if found:
            return Path(found)

    candidates: list[Path] = []
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    prog = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    prog86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    home = Path.home()
    for base in (local, prog, prog86, home / "AppData" / "Local", home / "AppData" / "Roaming"):
        if not base:
            continue
        candidates.extend(
            [
                base / "Programs" / "Universal Radio Hacker" / "urh.exe",
                base / "urh" / "urh.exe",
                base / "Python" / "Scripts" / "urh.exe",
            ]
        )
    venv_scripts = ROOT / ".venv" / "Scripts"
    candidates.extend([venv_scripts / "urh.exe", venv_scripts / "urh"])

    for path in candidates:
        if path.is_file():
            return path
    return None


def prepare_for_urh(source: Path, work_dir: Path) -> Path:
    """Copy IQ into a URH-friendly name (.cu8 → .complex16u).

    Multi‑GB captures are not copied — URH gets the original path (cu8 is accepted).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    size = source.stat().st_size if source.is_file() else 0
    if size > AUTO_RATE_MAX_BYTES:
        return source

    suffix = source.suffix.lower()
    if suffix == ".cu8":
        dest = work_dir / f"{source.stem}.complex16u"
    elif suffix in IQ_EXTENSIONS:
        dest = work_dir / source.name
    else:
        dest = work_dir / f"{source.stem}.complex16u"

    if dest.resolve() != source.resolve():
        shutil.copy2(source, dest)
    return dest


def open_in_urh(iq_for_urh: Path, urh_path: Optional[Path] = None) -> None:
    urh = urh_path or find_urh()
    if urh is None:
        raise FileNotFoundError(
            "Universal Radio Hacker (urh) was not found on PATH.\n\n"
            "Install it (pip install urh) or add urh.exe to PATH, then retry."
        )
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    try:
        subprocess.Popen(
            [str(urh), str(iq_for_urh)],
            cwd=str(iq_for_urh.parent),
            creationflags=creationflags if sys.platform == "win32" else 0,
            close_fds=True,
        )
    except OSError:
        subprocess.Popen(
            [str(urh)],
            creationflags=creationflags if sys.platform == "win32" else 0,
            close_fds=True,
        )
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(iq_for_urh)], check=False)


def _extra_protocol_flags() -> list[str]:
    return rtl433_full_decoder_flags(get_rtl433_exe())


def infer_sample_rate_hz(iq_path: Path, fallback: int = DEFAULT_SAMPLE_RATE) -> int:
    """Prefer 1024k; honor nearby URH_IMPORT_NOTES.txt when present."""
    notes = iq_path.parent / "URH_IMPORT_NOTES.txt"
    if notes.is_file():
        text = notes.read_text(encoding="utf-8", errors="replace").lower()
        if "1024000" in text or "1024k" in text or "1.024" in text:
            return 1_024_000
        if "1000000" in text or "1e6" in text or "1 msps" in text:
            return 1_000_000
        if "500000" in text or "500k" in text:
            return 500_000
    return int(fallback)


def infer_freq_mhz(iq_path: Path, fallback: float = DEFAULT_FREQ_MHZ) -> float:
    """Prefer 432.92 MHz FSK carrier; honor nearby notes when present."""
    notes = iq_path.parent / "URH_IMPORT_NOTES.txt"
    if notes.is_file():
        text = notes.read_text(encoding="utf-8", errors="replace").lower()
        if "432.92" in text or "432920000" in text:
            return 432.92
        if "433.92" in text or "433920000" in text:
            return 433.92
    return float(fallback)


def decode_iq_with_rtl433(
    iq_path: Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    freq_mhz: float = DEFAULT_FREQ_MHZ,
    auto_sample_rate: bool = True,
    on_progress: Optional[Callable[[str], None]] = None,
) -> tuple[list[TelemetryReading], str, int]:
    """Replay IQ through rtl_433 — same settings that produced ~430 session packets.

    Streams JSON to disk (multi‑GB captures). Returns (readings, log, sample_rate_used).
    """
    binary = get_rtl433_exe()
    if not binary.is_file():
        raise FileNotFoundError(f"rtl_433 not found at {binary}. Run build_installer / fetch_vendor first.")

    size = iq_path.stat().st_size if iq_path.is_file() else 0
    preferred = infer_sample_rate_hz(iq_path, sample_rate)
    rates: list[int] = [int(preferred)]
    if auto_sample_rate and size <= AUTO_RATE_MAX_BYTES:
        for rate in REPLAY_SAMPLE_RATES:
            if rate not in rates:
                rates.append(rate)
    elif auto_sample_rate and size > AUTO_RATE_MAX_BYTES and on_progress:
        on_progress(
            f"Large IQ ({size / (1024**3):.1f} GB) — one pass at {preferred} Hz "
            "(500k on this file only yields a few packets)."
        )

    freq_arg = f"{freq_mhz:g}M"
    best_readings: list[TelemetryReading] = []
    best_log = ""
    best_rate = rates[0]
    work = ROOT / "results" / "urh_work"
    work.mkdir(parents=True, exist_ok=True)

    for rate in rates:
        samples = max(1, size // 2)
        est_s = samples / max(rate, 1)
        timeout_s = max(900, int(est_s * 2) + 120)

        jsonl = work / f"replay_{iq_path.stem}_{rate}.jsonl"
        log_path = work / f"replay_{iq_path.stem}_{rate}.log"
        jsonl.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)

        cmd = [
            str(binary),
            "-r",
            str(iq_path),
            "-s",
            str(rate),
            "-f",
            freq_arg,
            "-F",
            "json",
            "-C",
            "customary",
            "-M",
            "time:iso",
            "-M",
            "level",
            "-M",
            "protocol",
            "-Y",
            "autolevel",
            "-Y",
            "minmax",
        ]
        cmd.extend(_extra_protocol_flags())
        if on_progress:
            on_progress(rtl433_decoder_enablement(binary))
            on_progress(f"rtl_433 replay @ {rate} Hz (timeout {timeout_s}s)…")
            on_progress(compact_rtl433_command(cmd))

        env = os.environ.copy()
        env["PATH"] = str(binary.parent) + os.pathsep + env.get("PATH", "")
        with jsonl.open("w", encoding="utf-8", errors="replace") as out_f, log_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as err_f:
            err_f.write("CMD: " + " ".join(cmd) + "\n")
            err_f.flush()
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=out_f,
                    stderr=err_f,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                    cwd=str(binary.parent),
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                err_f.write(f"\nexit={proc.returncode}\n")
            except subprocess.TimeoutExpired:
                err_f.write(f"\nTIMEOUT after {timeout_s}s\n")
                if on_progress:
                    on_progress(f"Timed out at {rate} Hz — keeping partial JSON.")

        readings: list[TelemetryReading] = []
        for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            reading = parse_rtl433_json(line)
            if reading is not None:
                readings.append(reading)
        log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        summary = f"Tried -s {rate}: {len(readings)} packet(s)\n"
        log = summary + log_tail
        if on_progress:
            on_progress(summary.strip())
        if len(readings) > len(best_readings):
            best_readings = readings
            best_log = log
            best_rate = rate
        elif not best_log:
            best_log = log
            best_rate = rate
        if len(readings) >= 50:
            break

    return best_readings, best_log.strip(), best_rate


def readings_from_telemetry_csv(csv_path: Path) -> list[TelemetryReading]:
    """Load prior rtl_433 CSV (telemetry.csv style) into suite readings."""
    import csv

    readings: list[TelemetryReading] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            def fget(*keys: str) -> Optional[float]:
                for key in keys:
                    val = row.get(key)
                    if val not in (None, ""):
                        try:
                            return float(val)
                        except (TypeError, ValueError):
                            return None
                return None

            batt = row.get("battery_ok")
            battery_ok = None
            if batt not in (None, ""):
                battery_ok = str(batt).strip().lower() in {"1", "true", "ok", "yes"}
            ts = row.get("time") or row.get("Time")
            try:
                timestamp = datetime.fromisoformat(str(ts).replace("Z", "")) if ts else datetime.now()
            except ValueError:
                timestamp = datetime.now()
            sid = str(row.get("id") or row.get("ID") or "").strip()
            model = str(row.get("protocol") or row.get("model") or "Unknown")
            proto_raw = row.get("protocol_id") or row.get("Protocol")
            protocol_id = None
            if proto_raw not in (None, ""):
                try:
                    protocol_id = int(float(str(proto_raw)))
                except (TypeError, ValueError):
                    protocol_id = None
            decoder = str(row.get("decoder") or row.get("Decoder") or "").strip()
            if not decoder:
                decoder = f"[{protocol_id}] {model}" if protocol_id is not None else model
            readings.append(
                TelemetryReading(
                    sensor_id=sid or "unknown",
                    model=model,
                    sensor_type="TPMS",
                    pressure_psi=fget("pressure_PSI", "pressure_psi"),
                    temperature_c=fget("temperature_C", "temperature_c"),
                    battery_ok=battery_ok,
                    timestamp=timestamp,
                    frequency_mhz=fget("freq_MHz", "freq"),
                    raw=dict(row),
                    decoder=decoder,
                    protocol_id=protocol_id,
                )
            )
    return readings


def export_iq_excel(
    readings: list[TelemetryReading],
    source_iq: Path,
    dest: Path,
    *,
    sample_rate: int,
    freq_mhz: float,
    urh_path: Optional[Path],
) -> Path:
    meta = {
        "Source IQ": str(source_iq),
        "Sample rate": f"{sample_rate} Hz",
        "Center frequency": f"{freq_mhz} MHz",
        "Decode settings": "rtl_433 replay @ 1024k / 432.92 MHz FSK (full library decoder set)",
        "URH file": str(urh_path) if urh_path else "—",
        "Unique sensors": len({r.sensor_id for r in readings if r.has_sensor_id()}),
        "Packets decoded": len(readings),
        "App": f"{APP_NAME} IQ→URH {APP_VERSION}",
    }
    return export_session_excel(readings, dest, meta)


class IqUrhView(ctk.CTkFrame):
    """Suite tab: upload IQ → open URH → decode → Excel."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=COLOR_BG, **kwargs)
        self._iq_path: Optional[Path] = None
        self._urh_prepared: Optional[Path] = None
        self._busy = False
        self._build()

    def _toplevel(self):
        return self.winfo_toplevel()

    def _build(self) -> None:
        banner = ctk.CTkFrame(self, fg_color=COLOR_HEADER_BG, corner_radius=8, height=72)
        banner.pack(fill="x", padx=4, pady=(4, 12))
        banner.pack_propagate(False)
        ctk.CTkLabel(
            banner,
            text="IQ → UNIVERSAL RADIO HACKER → EXCEL",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_HEADER_TEXT,
        ).pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(
            banner,
            text="Open a capture in URH (FSK @ 432.92 MHz), demodulate visually, export decoded TPMS Excel",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_HEADER_SUB,
        ).pack(anchor="w", padx=16, pady=(2, 10))

        card = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, border_width=1, border_color=COLOR_BORDER, corner_radius=10)
        card.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=16)

        ctk.CTkLabel(
            body, text="1. Select IQ capture", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_TEXT
        ).pack(anchor="w")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(6, 10))
        self.file_label = ctk.CTkLabel(
            row, text="No file selected", anchor="w", font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_DIM
        )
        self.file_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row,
            text="Browse…",
            width=110,
            height=32,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER,
            command=self._browse,
        ).pack(side="right")

        opts = ctk.CTkFrame(body, fg_color="transparent")
        opts.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(opts, text="Sample rate (Hz)", text_color=COLOR_TEXT_DIM).grid(row=0, column=0, sticky="w")
        self.rate_entry = ctk.CTkEntry(opts, width=140)
        self.rate_entry.insert(0, str(DEFAULT_SAMPLE_RATE))
        self.rate_entry.grid(row=1, column=0, padx=(0, 16), sticky="w")
        ctk.CTkLabel(opts, text="Center freq (MHz)", text_color=COLOR_TEXT_DIM).grid(row=0, column=1, sticky="w")
        self.freq_entry = ctk.CTkEntry(opts, width=140)
        self.freq_entry.insert(0, str(DEFAULT_FREQ_MHZ))
        self.freq_entry.grid(row=1, column=1, sticky="w")
        self.auto_rate = ctk.CTkSwitch(opts, text="Auto-try sample rates", text_color=COLOR_TEXT)
        self.auto_rate.select()
        self.auto_rate.grid(row=1, column=2, padx=(16, 0), sticky="w")
        ctk.CTkLabel(
            body,
            text="Defaults: 1024000 Hz sample rate, 432.92 MHz FSK carrier. "
            "Wrong rate (e.g. 500000) on session IQ yields almost no packets. Large files take several minutes. "
            "Or use CSV → Excel for an existing telemetry.csv.",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM,
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            body, text="2. Actions", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_TEXT
        ).pack(anchor="w", pady=(4, 6))
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x")
        ctk.CTkButton(
            actions,
            text="Open in URH",
            width=140,
            height=36,
            fg_color=COLOR_BTN_PRIMARY,
            hover_color=COLOR_BTN_PRIMARY_HOVER,
            command=self._open_urh,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Decode → Excel",
            width=140,
            height=36,
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            command=self._decode_excel,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="CSV → Excel",
            width=120,
            height=36,
            fg_color=COLOR_BTN_EXPORT,
            hover_color=COLOR_BTN_EXPORT_HOVER,
            command=self._import_csv_excel,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Do both",
            width=100,
            height=36,
            fg_color=COLOR_BTN_PRIMARY,
            hover_color=COLOR_BTN_PRIMARY_HOVER,
            command=self._do_both,
        ).pack(side="left")

        ctk.CTkLabel(body, text="Log", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_TEXT).pack(
            anchor="w", pady=(14, 4)
        )
        self.log = ctk.CTkTextbox(body, height=220, font=ctk.CTkFont(family="Consolas", size=11))
        self.log.pack(fill="both", expand=True)
        self._log(f"URH: {find_urh() or 'not found on PATH — install with: pip install urh'}")
        try:
            rtl = get_rtl433_exe()
            self._log(f"rtl_433: {rtl if rtl.is_file() else 'missing'}")
        except Exception as exc:
            self._log(f"rtl_433: {exc}")

    def shutdown(self) -> None:
        """No background processes to stop."""

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {message}\n")
        self.log.see("end")

    def _browse(self) -> None:
        iq_dir = ROOT / "results" / "iq"
        iq_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.askopenfilename(
            parent=self._toplevel(),
            title="Select IQ capture",
            initialdir=str(iq_dir),
            filetypes=[
                ("IQ / URH signals", "*.cu8;*.complex16u;*.complex16s;*.complex;*.wav"),
                ("rtl_433 IQ (.cu8)", "*.cu8"),
                ("URH unsigned 8-bit (.complex16u)", "*.complex16u"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._iq_path = Path(path)
        self._urh_prepared = None
        self.file_label.configure(text=str(self._iq_path), text_color=COLOR_TEXT)
        inferred = infer_sample_rate_hz(self._iq_path, DEFAULT_SAMPLE_RATE)
        inferred_freq = infer_freq_mhz(self._iq_path, DEFAULT_FREQ_MHZ)
        self.rate_entry.delete(0, "end")
        self.rate_entry.insert(0, str(inferred))
        self.freq_entry.delete(0, "end")
        self.freq_entry.insert(0, str(inferred_freq))
        mb = self._iq_path.stat().st_size / (1024 * 1024)
        self._log(
            f"Selected: {self._iq_path} ({mb:.0f} MB) — "
            f"{inferred} Hz, {inferred_freq} MHz FSK"
        )

    def _settings(self) -> tuple[int, float]:
        try:
            rate = int(float(self.rate_entry.get().strip().replace(",", "")))
        except ValueError as exc:
            raise ValueError("Sample rate must be a number (e.g. 1024000).") from exc
        try:
            freq = float(self.freq_entry.get().strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Frequency must be MHz (e.g. 432.92).") from exc
        if rate < 250_000:
            raise ValueError("Sample rate should be at least 250000 Hz for these captures.")
        return rate, freq

    def _ensure_file(self) -> Path:
        if not self._iq_path or not self._iq_path.is_file():
            raise FileNotFoundError("Choose an IQ file first.")
        return self._iq_path

    def _prepare(self) -> Path:
        source = self._ensure_file()
        work = ROOT / "results" / "urh_work"
        prepared = prepare_for_urh(source, work)
        self._urh_prepared = prepared
        self._log(f"URH-ready copy: {prepared}")
        return prepared

    def _open_urh(self) -> None:
        try:
            prepared = self._prepare()
            open_in_urh(prepared)
            self._log("Launched Universal Radio Hacker.")
            messagebox.showinfo(
                APP_NAME,
                "Universal Radio Hacker should open with the signal.\n\n"
                "In URH: set sample rate 1024000 and center 432.92 MHz (FSK), then demodulate.\n"
                "Use Decode → Excel here for suite-format TPMS export.",
                parent=self._toplevel(),
            )
        except Exception as exc:
            self._log(f"ERROR: {exc}")
            messagebox.showerror(APP_NAME, str(exc), parent=self._toplevel())

    def _decode_excel(self) -> None:
        if self._busy:
            return
        try:
            source = self._ensure_file()
            rate, freq = self._settings()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self._toplevel())
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"IQ_Decode_{source.stem}_{stamp}.xlsx"
        dest = filedialog.asksaveasfilename(
            parent=self._toplevel(),
            title="Save Excel report",
            initialdir=str(ROOT / "results"),
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not dest:
            return

        self._busy = True
        size_gb = source.stat().st_size / (1024**3)
        self._log(f"Decoding {source.name} ({size_gb:.2f} GB) @ {rate} Hz, {freq} MHz…")
        if size_gb > 1:
            self._log("Large file — expect several minutes. Do not close the app.")

        def worker() -> None:
            error: Optional[Exception] = None
            saved: Optional[Path] = None
            count = 0
            used_rate = rate
            try:
                prepared = self._prepare()
                auto = self.auto_rate.get() == 1

                def progress(msg: str) -> None:
                    self.after(0, lambda m=msg: self._log(m))

                readings, log, used_rate = decode_iq_with_rtl433(
                    source,
                    sample_rate=rate,
                    freq_mhz=freq,
                    auto_sample_rate=auto,
                    on_progress=progress,
                )
                count = len(readings)
                self.after(0, lambda r=used_rate, c=count: self._log(f"Best replay: {c} packet(s) at {r} Hz"))
                tail = "\n".join(log.splitlines()[-16:])
                if tail.strip():
                    self.after(0, lambda t=tail: self._log(t))
                saved = export_iq_excel(
                    readings,
                    source,
                    Path(dest),
                    sample_rate=used_rate,
                    freq_mhz=freq,
                    urh_path=prepared,
                )
            except Exception as exc:  # noqa: BLE001
                error = exc

            def done() -> None:
                self._busy = False
                if error:
                    self._log(f"ERROR: {error}")
                    messagebox.showerror(APP_NAME, str(error), parent=self._toplevel())
                    return
                self._log(f"Excel saved ({count} packets): {saved}")
                messagebox.showinfo(
                    APP_NAME,
                    f"Saved Excel with {count} decoded packet(s) at {used_rate} Hz:\n{saved}",
                    parent=self._toplevel(),
                )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _import_csv_excel(self) -> None:
        """Convert prior telemetry.csv (430-row style) into suite Excel format."""
        initial = ROOT / "results" / "iq" / "session"
        if not initial.is_dir():
            initial = ROOT / "results"
        path = filedialog.askopenfilename(
            parent=self._toplevel(),
            title="Select telemetry CSV",
            initialdir=str(initial),
            filetypes=[("Telemetry CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        csv_path = Path(path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = filedialog.asksaveasfilename(
            parent=self._toplevel(),
            title="Save Excel report",
            initialdir=str(csv_path.parent),
            initialfile=f"{csv_path.stem}_{stamp}.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not dest:
            return
        try:
            readings = readings_from_telemetry_csv(csv_path)
            if not readings:
                raise ValueError("No rows found in CSV.")
            iq_guess = csv_path.parent / "sdr_session_20260906_183932.cu8"
            source = iq_guess if iq_guess.is_file() else csv_path
            saved = export_iq_excel(
                readings,
                source,
                Path(dest),
                sample_rate=1_024_000,
                freq_mhz=DEFAULT_FREQ_MHZ,
                urh_path=None,
            )
            self._log(f"CSV → Excel: {len(readings)} packets → {saved}")
            messagebox.showinfo(
                APP_NAME,
                f"Saved Excel with {len(readings)} packet(s) from CSV:\n{saved}",
                parent=self._toplevel(),
            )
        except Exception as exc:
            self._log(f"ERROR: {exc}")
            messagebox.showerror(APP_NAME, str(exc), parent=self._toplevel())

    def _do_both(self) -> None:
        self._open_urh()
        self._decode_excel()


class IqUrhApp(ctk.CTk):
    """Standalone window wrapping IqUrhView."""

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        self.title(f"IQ → URH → Excel  ·  {APP_NAME}")
        self.geometry("900x640")
        self.minsize(720, 520)
        self.configure(fg_color=COLOR_BG)
        IqUrhView(self).pack(fill="both", expand=True, padx=8, pady=8)


def main() -> None:
    IqUrhApp().mainloop()


if __name__ == "__main__":
    main()
