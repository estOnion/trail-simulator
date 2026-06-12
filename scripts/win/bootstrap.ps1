# scripts/win/bootstrap.ps1
# Best-effort Windows preflight (mirrors scripts/bootstrap.sh). Warnings only —
# nothing here is fatal. See docs/WINDOWS.md for the full setup.

$ErrorActionPreference = "Continue"
Write-Host "== trail-simulator Windows preflight =="

# Python 3.11+
try {
    $pv = (python --version) 2>&1
    Write-Host "python: $pv"
} catch {
    Write-Warning "python not found on PATH (need 3.11+)"
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# venv pymobiledevice3 (iPhone path)
$pmd = Join-Path $root ".venv\Scripts\pymobiledevice3.exe"
if (Test-Path $pmd) {
    Write-Host "pymobiledevice3: $pmd"
} else {
    Write-Warning "pymobiledevice3 not in .venv — run: pip install -r requirements.txt"
}

# adb (Android path)
$adb = Get-Command adb -ErrorAction SilentlyContinue
if ($adb) {
    Write-Host "adb: $($adb.Source)"
} else {
    Write-Warning "adb not on PATH — needed only for the Android path (install Android Platform-Tools)"
}

# Apple usbmux service (iPhone path). Service name varies by install
# (iTunes vs the 'Apple Devices' app); check both known names.
$svc = Get-Service -Name "Apple Mobile Device Service" -ErrorAction SilentlyContinue
if (-not $svc) {
    $svc = Get-Service -Name "AppleMobileDeviceService" -ErrorAction SilentlyContinue
}
if ($svc) {
    Write-Host "Apple Mobile Device Service: $($svc.Status)"
} else {
    Write-Warning "Apple Mobile Device Service not found — install the 'Apple Devices' app (or iTunes) for iPhone/usbmux support"
}

Write-Host "Done. See docs\WINDOWS.md for full setup and the reliability test."
