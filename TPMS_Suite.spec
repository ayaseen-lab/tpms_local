# -*- mode: python ; coding: utf-8 -*-
"""Onedir PyInstaller spec. Do not enable UPX — it triggers antivirus false positives."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
SDR_UI = ROOT / "sdr_ui"
SDK = ROOT / "hamaton-sdk-python-fix-uart-transport-timing" / "src"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SDR_UI))
sys.path.insert(0, str(SDK))

ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")
pil_datas, pil_binaries, pil_hidden = collect_all("PIL")

datas = [*ctk_datas, *pil_datas]
binaries = [*ctk_binaries, *pil_binaries]
hiddenimports = [
    *ctk_hidden,
    *pil_hidden,
    *collect_submodules("serial"),
    *collect_submodules("openpyxl"),
    *collect_submodules("reportlab"),
    *collect_submodules("hamaton"),
    *collect_submodules("tpms_bench"),
    "app",
    "config",
    "themes",
    "widgets",
    "setup_manager",
    "setup_wizard",
    "rtl433_runner",
    "session_export",
    "activity_terminal",
    "dialogs",
    "tpms_view",
    "shell",
    "comparative_report",
    "serial.tools.list_ports",
    "PIL._tkinter_finder",
]

rtl_dir = SDR_UI / "vendor" / "rtl_433"
zadig = SDR_UI / "vendor" / "zadig.exe"
if rtl_dir.is_dir():
    datas.append((str(rtl_dir), "rtl_433"))
if zadig.is_file():
    datas.append((str(zadig), "zadig"))

hamaton_pkg = SDK / "hamaton"
if hamaton_pkg.is_dir():
    datas.append((str(hamaton_pkg), "hamaton"))

icon = ROOT / "installer" / "tpms_suite.ico"
version = ROOT / "installer" / "version_info.txt"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(SDR_UI), str(SDK)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TPMS_Suite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.is_file() else None,
    version=str(version) if version.is_file() else None,
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TPMS_Suite",
)
