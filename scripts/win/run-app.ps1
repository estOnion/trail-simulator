# scripts/win/run-app.ps1
# Runs the trail-simulator backend from the project venv on port 8080
# (avoids the 8787/RSD tunnel collision). Extra args pass through, e.g.:
#   .\scripts\win\run-app.ps1 --android <serial>
#   .\scripts\win\run-app.ps1 --udid <UDID>
#   .\scripts\win\run-app.ps1 --dev-no-device

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Error "venv python not found at $py.`nSet it up first:`n  python -m venv .venv`n  .\.venv\Scripts\Activate.ps1`n  pip install -r requirements.txt"
    exit 1
}

& $py -m trail_simulator --port 8080 @args
