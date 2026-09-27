#!/usr/bin/env bash
# Rebuild the Windows PE launcher from macOS/Linux.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/windows/launcher"
GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o "$ROOT/TPMS_Suite.exe" .
cp "$ROOT/TPMS_Suite.exe" "$ROOT/windows/TPMS_Suite.exe"
file "$ROOT/TPMS_Suite.exe"
echo "Wrote $ROOT/TPMS_Suite.exe"
