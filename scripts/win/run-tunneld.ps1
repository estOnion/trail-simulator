# scripts/win/run-tunneld.ps1
# Runs pymobiledevice3's RemoteXPC tunnel ("tunneld"), which iOS 17+ DVT
# location simulation requires. The tunnel needs Administrator (WinTun driver +
# raw networking). This script self-elevates if not already admin.
#
# Leave the elevated window open for the whole session. Then run the backend
# in a normal window with scripts\win\run-app.ps1.

$ErrorActionPreference = "Stop"

# Re-launch elevated if not running as Administrator.
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Not elevated — relaunching as Administrator..."
    Start-Process -FilePath "powershell.exe" -Verb RunAs `
        -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
    exit
}

# Resolve project root (this script lives in scripts\win\).
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pmd = Join-Path $root ".venv\Scripts\pymobiledevice3.exe"

if (-not (Test-Path $pmd)) {
    Write-Error "pymobiledevice3 not found at $pmd.`nCreate the venv and install deps first:`n  python -m venv .venv`n  .\.venv\Scripts\Activate.ps1`n  pip install -r requirements.txt"
    exit 1
}

Write-Host "Starting tunneld (keep this window open)..."
& $pmd remote tunneld
