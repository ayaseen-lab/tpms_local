# TPMS Suite

Combined desktop app with **SDR Receiver** (RTL-SDR / rtl_433) and **TPMS Board** (Hamaton USB-TTL bench) in one window.

Switching tabs only changes the view. SDR listening and board tests keep running in the background.

## Windows (client laptop)

**Quick start (source checkout):**
1. Install Python 3.11+ (add to PATH)
2. Double-click `Setup_Windows.bat` once (venv + deps + rtl_433/Zadig)
3. Next times: double-click `TPMS_Suite.exe` or `Start TPMS Suite.bat`

**Packaged installer (full .exe app):** on a Windows PC run `Build_Windows_Installer.bat`, or download the CI artifact from the `windows-installer` GitHub Action. That produces `dist_installer\TPMS_Suite_Setup_4.0.0.exe`.

Board USB RX works without J-Link / JTAG. Plug the Hamaton USB board + RTL-SDR and start.

## Run from source (macOS / Linux / Windows)

```powershell
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## IQ → URH → Excel

Use the **IQ / URH** tab in the suite (or run standalone):

```powershell
.venv\Scripts\python.exe iq_urh_tool.py
```

1. Browse to an IQ file (e.g. `results/iq/*.cu8`)
2. **Open in URH** — copies `.cu8` to `.complex16u` and launches Universal Radio Hacker (`pip install urh` if needed)
3. **Decode → Excel** — replays with the suite rtl_433 decoder set and writes an SDR-format Excel report

**Do both** opens URH and exports Excel in one step.

## What you get

- **IQ / URH** — open IQ captures in Universal Radio Hacker and export decoded Excel
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
- **Windows client (typical):** the board replies on USB-TTL RX. J-Link / JTAG is **not** required — if USB RX works, the suite uses that path automatically.
- **Lab fallback:** when USB-TTL is TX-only, replies are read from board SRAM via SEGGER J-Link SWD (optional). Set `FYRQOM_FORCE_JTAG_RX=1` only to force that path.

## Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

That script downloads official **rtl_433** (MSVC x64 25.12) and **Zadig 2.9**, builds a folder-based (not one-file) app, then compiles `dist_installer\TPMS_Suite_Setup_4.0.0.exe`.

Or double-click `Build_Windows_Installer.bat`.

SEGGER J-Link is **not** bundled (separate vendor license). It is only needed as a lab fallback when the board does not reply on USB-TTL RX. Windows client machines with working USB RX do not need J-Link.

Unsigned installers can still show SmartScreen (“Windows protected your PC”). A paid Authenticode code-signing certificate is what removes that warning; the build is set up so you can sign with `signtool` once you have a cert. Do not disable Defender to hide the warning.
