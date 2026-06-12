# Running trail-simulator on Windows

The backend and web UI are pure Python and run on Windows unchanged. The GPS
injection has two device paths:

- **iPhone (primary)** — via `pymobiledevice3`'s RemoteXPC tunnel. The tunnel is
  the tricky part on Windows; its reliability is what the [reliability
  gate](#reliability-gate) below measures.
- **Android (fallback)** — via `adb` against a **rooted Android 12+** phone. No
  app on the phone. `adb` is fully cross-platform, so this path is the most
  reliable on Windows.

The web UI/UX is identical to macOS — devices appear in the same device list.

## Common prerequisites

1. **Python 3.11+** on PATH (`python --version`).
2. Clone the repo, then create the venv and install deps:
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

Use this if the native path fails the reliability gate. It runs the Linux stack
under Windows and passes the iPhone USB into WSL.

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

> Note: USB passthrough adds its own failure surface (re-attach needed after
> unplug/sleep). This is what the gate measures vs the native path.

## Path C — Android on Windows (fallback, most reliable)

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

## Reliability gate

Run this on real hardware to decide which iPhone path (if any) to recommend on
Windows. Run it for **native** and **WSL**, on `--port 8080`.

### Procedure
1. Start the tunnel + backend for the path under test (A or B above).
2. Start a session in the UI (any short route, ≤ 20 km/h) so injection runs at
   ~1 Hz continuously.
3. Let it run **≥ 15 minutes** without touching the tunnel window.
4. Midway, **unplug the USB cable, wait ~5 s, replug** (native), or
   `usbipd detach`/`attach` (WSL). Confirm the session auto-recovers without
   restarting the backend.
5. Read the periodic `location.set reliability: N/M ok (X%)` lines from the
   backend log (emitted ~once a minute).

### Pass criteria (all must hold)
- ≥ 15 min continuous injection with **no stall**.
- **0** manual `tunneld` restarts during the run.
- `set()` success rate **≥ 99%** (from the reliability log line).
- Recovered from the one USB reconnect without a backend restart.

### Outcome
- **PASS (native and/or WSL):** document the passing path(s) as supported; mark
  the more reliable one as recommended.
- **FAIL (both):** recommend **Path C (Android)**; keep the iPhone paths as
  "experimental" with the measured caveats.

### Results (fill in)

| Path | Date | Minutes | set() success % | USB reconnect recovered | Verdict |
|------|------|---------|-----------------|--------------------------|---------|
| A — native iPhone | | | | | |
| B — WSL iPhone | | | | | |

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
