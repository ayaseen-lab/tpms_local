"""Download official rtl_433 and Zadig binaries into sdr_ui/vendor."""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdr_ui"))

from config import (  # noqa: E402
    RTL_433_DOWNLOAD_URL,
    RTL_433_ZIP_NAME,
    ZADIG_DOWNLOAD_URL,
    ZADIG_EXE_NAME,
)


VENDOR = ROOT / "sdr_ui" / "vendor"
RTL_DIR = VENDOR / "rtl_433"
CACHE = ROOT / "installer" / "_download_cache"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"Using cached {dest.name}")
        return
    print(f"Downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


KEEP_RTL433 = {
    "rtl_433-rtlsdr.exe",
    "rtl_433.exe",
    "libusb-1.0.dll",
    "pthreadVC2.dll",
    "rtlsdr.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "README.txt",
}


def _rtl433_present() -> bool:
    return (RTL_DIR / "rtl_433-rtlsdr.exe").is_file() or (RTL_DIR / "rtl_433.exe").is_file()


def prune_rtl433() -> None:
    """Keep the RTL-SDR decoder and its DLLs. Drop SoapySDR/TLS extras."""
    if not RTL_DIR.is_dir():
        return
    for path in RTL_DIR.iterdir():
        if path.is_file() and path.name not in KEEP_RTL433:
            path.unlink()


def fetch_rtl433() -> None:
    if _rtl433_present():
        print(f"rtl_433 already present in {RTL_DIR}")
        return
    zip_path = CACHE / RTL_433_ZIP_NAME
    _download(RTL_433_DOWNLOAD_URL, zip_path)
    extract = CACHE / "rtl_433_extract"
    if extract.exists():
        shutil.rmtree(extract)
    extract.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract)

    source = extract
    children = [p for p in extract.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        source = children[0]

    if RTL_DIR.exists():
        shutil.rmtree(RTL_DIR)
    shutil.copytree(source, RTL_DIR)
    prune_rtl433()
    if not _rtl433_present():
        raise SystemExit(f"rtl_433 executable not found after extract in {RTL_DIR}")
    print(f"Installed rtl_433 into {RTL_DIR}")


def fetch_zadig() -> None:
    dest = VENDOR / ZADIG_EXE_NAME
    if dest.is_file():
        print(f"Zadig already present: {dest}")
        return
    _download(ZADIG_DOWNLOAD_URL, dest)
    print(f"Installed Zadig into {dest}")


def summarize() -> None:
    exe = next((RTL_DIR / n for n in ("rtl_433-rtlsdr.exe", "rtl_433.exe") if (RTL_DIR / n).is_file()), None)
    print("--- bundle check ---")
    print(f"rtl_433: {'OK  ' + str(exe) if exe else 'MISSING'}")
    print(f"zadig:   {'OK  ' + str(VENDOR / ZADIG_EXE_NAME) if (VENDOR / ZADIG_EXE_NAME).is_file() else 'MISSING'}")
    if exe:
        dlls = list(RTL_DIR.glob("*.dll"))
        print(f"rtl_433 companion DLLs: {len(dlls)}")


def main() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    fetch_rtl433()
    prune_rtl433()
    fetch_zadig()
    summarize()


if __name__ == "__main__":
    main()
