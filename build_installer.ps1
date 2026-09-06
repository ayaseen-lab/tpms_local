# Build TPMS Suite Windows installer (PyInstaller onedir + Inno Setup).
# Usage:  powershell -ExecutionPolicy Bypass -File .\build_installer.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    $venv = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python was not found. Install Python 3.11+ and retry."
}

$Python = Find-Python
Write-Host "Python: $Python"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment…"
    & $Python -m venv .venv
}
$Python = (Resolve-Path ".venv\Scripts\python.exe").Path

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller pillow

Write-Host "Fetching vendor binaries (rtl_433, Zadig)…"
& $Python installer\fetch_vendor.py
& $Python installer\generate_icon.py

$rtl = @("rtl_433-rtlsdr.exe", "rtl_433.exe") | ForEach-Object {
    $p = Join-Path "sdr_ui\vendor\rtl_433" $_
    if (Test-Path $p) { Get-Item $p }
} | Select-Object -First 1
if (-not $rtl) { throw "rtl_433 was not bundled. fetch_vendor.py failed." }
if (-not (Test-Path "sdr_ui\vendor\zadig.exe")) { throw "zadig.exe was not bundled." }
Write-Host "Bundled decoder: $($rtl.FullName)"

Write-Host "Building onedir app (no UPX)…"
& $Python -m PyInstaller --noconfirm --clean TPMS_Suite.spec

$appExe = "dist\TPMS_Suite\TPMS_Suite.exe"
if (-not (Test-Path $appExe)) { throw "PyInstaller did not produce $appExe" }

$internalRtl = Get-ChildItem "dist\TPMS_Suite" -Recurse -Include "rtl_433-rtlsdr.exe","rtl_433.exe" -File | Select-Object -First 1
$internalZadig = Get-ChildItem "dist\TPMS_Suite" -Recurse -Filter "zadig.exe" -File | Select-Object -First 1
if (-not $internalRtl) { throw "rtl_433 missing from dist bundle." }
if (-not $internalZadig) { throw "Zadig missing from dist bundle." }
Write-Host "Packaged rtl_433: $($internalRtl.FullName)"
Write-Host "Packaged Zadig:   $($internalZadig.FullName)"

function Find-ISCC {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $paths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$iscc = Find-ISCC
if (-not $iscc) {
    Write-Host "Inno Setup 6 not found. Installing via winget…"
    winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
    $iscc = Find-ISCC
}
if (-not $iscc) { throw "Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 and re-run." }

Write-Host "Compiling installer with $iscc"
& $iscc "installer\tpms_suite.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }

$setup = Get-ChildItem "dist_installer\TPMS_Suite_Setup_*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ""
Write-Host "Installer: $($setup.FullName)"
Write-Host "Unsigned builds can still show SmartScreen until you Authenticode-sign with a code-signing certificate."
