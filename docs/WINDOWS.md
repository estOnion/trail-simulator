# Running trail-simulator on Windows

The backend and web UI are pure Python and run on Windows unchanged. The GPS
injection has two device paths:

- **iPhone** — via `pymobiledevice3`'s RemoteXPC tunnel. The tunnel is the tricky
  part on Windows; see [which path to use](#which-path-to-use) below.
- **Android** — via `adb` against a **rooted Android 12+** phone, nothing
  installed on the phone. `adb` is fully cross-platform, so this is the most
  reliable path on Windows.

The web UI/UX is identical to macOS — devices appear in the same device list.

## Common prerequisites

1. **Python 3.11+** on PATH (`python --version`).
2. Clone the repo, then install deps with [uv](https://github.com/astral-sh/uv):
   ```powershell
   uv sync
   ```
   Or with a plain venv:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   If `Activate.ps1` is blocked: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
3. Run the preflight to sanity-check your setup:
   ```powershell
   .\scripts\win\bootstrap.ps1
   ```

## Path A — iPhone on native Windows (PowerShell)

### Extra dependencies
- **Apple Mobile Device Support (usbmux):** install the **Apple Devices** app
  from the Microsoft Store (or iTunes). Without it Windows can't enumerate the
  iPhone over USB.
- iPhone with **Developer Mode** on (Settings → Privacy & Security → Developer
  Mode) and **trusted** ("Trust This Computer").
- Administrator rights (the tunnel needs them).

### Run (two windows)
1. **Tunnel (elevated — keep open):**
   ```powershell
   .\scripts\win\run-tunneld.ps1
   ```
   It self-elevates to Administrator. Leave the window running.
2. **Backend (normal window):**
   ```powershell
   .\scripts\win\run-app.ps1
   ```
   This serves the UI at http://127.0.0.1:8080/ on **port 8080** (8787 collides
   with the RSD tunnel and makes GPS injection silently fail).

Plug in (or trust) one iPhone, open the UI, pick a route, press **Walk**.
For a specific device, pass `--udid <UDID>`. For Wi-Fi-only, pair once over USB
then enable `pymobiledevice3 lockdown wifi-connections on` (see main README).

## Path B — iPhone via WSL2 + usbipd-win

Worth trying if the native path won't hold a stable tunnel. It runs the Linux
stack under Windows and passes the iPhone USB through into WSL.

### Extra dependencies
- **WSL2** with a Linux distro (`wsl --install`).
- **usbipd-win** on Windows (`winget install usbipd`).
- Inside WSL: Python 3.11+, the repo cloned, venv + `pip install -r requirements.txt`,
  and `usbmuxd`/`libimobiledevice` packages (`sudo apt install usbmuxd`).

### Run
1. **Attach the iPhone into WSL (admin PowerShell on Windows):**
   ```powershell
   usbipd list                      # find the iPhone's BUSID
   usbipd bind --busid <BUSID>
   usbipd attach --wsl --busid <BUSID>
   ```
2. **Inside WSL (two shells):**
   ```bash
   sudo .venv/bin/pymobiledevice3 remote tunneld   # shell 1, keep open
   source .venv/bin/activate && python -m trail_simulator --port 8080  # shell 2
   ```
Open http://127.0.0.1:8080/ from Windows (WSL forwards localhost).

USB passthrough adds its own failure surface — you need to re-attach after an
unplug or a sleep.

## Path C — Android on Windows (most reliable)

### Extra dependencies
- **Android Platform-Tools** (`adb`) on PATH.
- A **rooted Android 12+ (API 31+)** phone with USB debugging on. Injection uses
  `su -c 'cmd location ...'`, so root is required. No app is installed.

### Run
1. Confirm the phone is visible: `adb devices` (state must be `device`).
2. Start the backend targeting it (no tunnel needed):
   ```powershell
   .\scripts\win\run-app.ps1 --android <serial>
   ```
Open http://127.0.0.1:8080/, pick a route, press **Walk**. iPhones and Androids
can be mixed (`--android <serial> --udid <UDID>`).

## Which path to use

Path C (Android) is the reliable one on Windows: `adb` is cross-platform and
carries none of the tunnel's baggage. Both iPhone paths are **unverified on
Windows hardware** — the RemoteXPC tunnel is the fragile part, and WSL's USB
passthrough adds its own failure surface on top. Treat A and B as experimental.

To check either path on your own hardware, soak it: start a session on
`--port 8080` and leave it injecting at ~1 Hz for 15+ minutes without touching
the tunnel window, unplugging and replugging the cable (or
`usbipd detach`/`attach`) once midway. The backend logs
`location.set reliability: N/M ok (X%)` about once a minute. What you want to
see is no stall, no manual `tunneld` restart, a success rate at or above 99%,
and recovery from the reconnect without restarting the backend.

## Troubleshooting

- **GPS won't move / tunnel stream resets:** make sure you're on `--port 8080`,
  not 8787 (RSD collision).
- **iPhone not detected (native):** install the Apple Devices app; confirm
  "Apple Mobile Device Service" is running (`bootstrap.ps1` checks this).
- **"requires Administrator":** run the tunnel via `run-tunneld.ps1` (it
  self-elevates) or launch PowerShell as Administrator.
- **WSL can't see the iPhone:** re-run `usbipd attach --wsl`; it detaches on
  unplug/sleep.
- **Android `adb` errors / mock location rejected:** the phone must be rooted
  (API 31+); injection runs as `su -c`.
