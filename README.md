# TPMS Suite

Combined desktop app with **SDR Receiver** (RTL-SDR / rtl_433) and **TPMS Board** (Hamaton USB-TTL bench) in one window.

Switching tabs only changes the view. SDR listening and board tests keep running in the background.

## Run from source

```powershell
cd D:\Xynovix\Combined_App
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## What you get

- **SDR Receiver** — live rtl_433 telemetry, sensor cards, history, driver setup
- **TPMS Board** — Excel opcode database plus optional custom CODE A / B / C fields
- **Start Both** — start Board + SDR together (Board skips live IQ so SDR owns the dongle)
- **Comparative Analysis** — header **Compare Excel** / **Compare PDF**: every Board session row vs SDR OK/NOK, plus SDR-only IDs (Vehicle / Protocol column)
- Live Board columns for SDR compare result and reason; header badges show both statuses
- Exports are labeled so files are not mixed up:
  - `SDR_Receiver_Report_*.xlsx` / `.pdf` — RTL-SDR telemetry (not board)
  - `TPMS_Board_Report_*.xlsx` / `.pdf` — Hamaton board validation (not SDR)
  - `Comparative_Analysis_Report_*.xlsx` / `.pdf` — Board vs SDR OK/NOK for the current session

## Custom opcodes

On the TPMS Board tab you can:

1. Upload the Hamaton Excel database (CODE A / B / C columns), and/or
2. Type your own CODE A, CODE B, and CODE C (hex) in the custom opcode fields

A manual triple is tested in addition to Excel rows. If no Excel file is selected, the custom codes run on their own.

## Hardware

- SDR tab: RTL-SDR dongle (WinUSB via Zadig). Bundled rtl_433 is under `sdr_ui/vendor/rtl_433`.
- Board tab: USB-TTL adapter on the Hamaton board. Select the COM port, then Start Test.

## Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

That script downloads official **rtl_433** (MSVC x64 25.12) and **Zadig 2.9**, builds a folder-based (not one-file) app, then compiles `dist_installer\TPMS_Suite_Setup_1.1.0.exe`.

SEGGER J-Link is **not** bundled (separate vendor license). Install J-Link on the PC if you need SRAM capture on the board tab.

Unsigned installers can still show SmartScreen (“Windows protected your PC”). A paid Authenticode code-signing certificate is what removes that warning; the build is set up so you can sign with `signtool` once you have a cert. Do not disable Defender to hide the warning.
