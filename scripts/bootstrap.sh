#!/usr/bin/env bash
# Pre-flight checks for Trail Simulator.
set -euo pipefail

echo "Trail Simulator bootstrap checks"
echo "================================"

command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 1; }
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "python3: $PY_VER"
[[ "$PY_VER" =~ ^3\.(11|12|13|14|15)$ ]] || { echo "ERROR: need Python 3.11+"; exit 1; }

python3 -c 'import pymobiledevice3' 2>/dev/null || { echo "ERROR: pymobiledevice3 not installed — run: pip install -r requirements.txt"; exit 1; }
echo "pymobiledevice3: installed"

if python3 -m pymobiledevice3 usbmux list 2>/dev/null | grep -q '"ConnectionType"'; then
  echo "iPhone: detected via usbmux"
else
  echo "WARN: no iPhone detected via usbmux — plug it in and accept the trust prompt"
fi

echo
echo "Reminders:"
echo "  1. iPhone → Settings → Privacy & Security → Developer Mode must be ON"
echo "  2. Run the app with: python -m trail_simulator (will sudo-prompt for tunneld on iOS 17+)"
