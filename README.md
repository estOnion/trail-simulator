# Trail Simulator

**Mac-controlled iPhone GPS route simulator.** Click two points on a map, pick a walking speed, and watch a tethered (or LAN-connected) iPhone follow the route in real time.

No jailbreak, no sideloading, no modifications to the iPhone — built on the same public developer-disk interface ([`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3)) that Xcode's "Simulate Location" feature uses.

## Features

- Click-to-route planning over OpenStreetMap + Leaflet
- Realistic pedestrian pacing — ≤ 20 km/h speed cap, ≤ 5 m per-tick jump cap
- 7-day cooldown table for long-distance repositions, persisted in SQLite across restarts
- **Home base station** mode — install once with `sudo`, then drive the iPhone from a Safari bookmark on the phone. No terminal, no cable, no sudo prompts after install.
- **UI preview** mode for tinkering with the map and controls without an iPhone attached
- FastAPI + WebSocket backend, vanilla JS + Leaflet frontend

## How it works

The Mac runs a local FastAPI server and `pymobiledevice3`'s `tunneld`. Tunneld creates a kernel `utun` interface and speaks RemoteXPC to the iPhone over USB or LAN; the app streams `CLLocation` updates through DVT at ~1 Hz. A browser on the iPhone (or anything on the same Wi-Fi) drives the session over HTTP. Cooldown state persists in a local SQLite DB so anti-teleport gates survive restarts.

## Requirements

- macOS 13+ (Ventura or later; Sequoia tested)
- Python 3.11+
- iPhone with Developer Mode enabled (Settings → Privacy & Security → Developer Mode)
- iPhone trusted ("Trust This Computer") and tethered via USB
- `sudo` available (needed for `tunneld` on iOS 17+)

## Setup

```bash
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Two run modes are supported:

- **[Home base station (recommended)](#home-base-station-recommended)** — install once with `sudo`, then `tunneld` runs as a LaunchDaemon at boot. Day-to-day use is just opening the Safari bookmark on the iPhone. No terminals, no cable, no sudo prompts after install.
- **[Dev / two-terminal mode](#dev--two-terminal-mode)** — no install, but every session needs `sudo` for `tunneld`. Use this while hacking on the code.

## Dev / two-terminal mode

**Terminal 1 — tunneld (needs sudo, keep it open):**
```bash
sudo "$PWD/.venv/bin/pymobiledevice3" remote tunneld
```

> `pymobiledevice3` lives inside the venv, and `sudo` resets `PATH`, so use the full venv path above (run from the project root). If you installed `pymobiledevice3` globally you can just run `sudo pymobiledevice3 remote tunneld`.

**Terminal 2 — the app:**
```bash
source .venv/bin/activate
python -m trail_simulator
```

Opens the UI at http://127.0.0.1:8787 — click an origin and destination on the map, pick a speed (≤ 20 km/h), press **Walk**.

Press `Ctrl-C` in Terminal 2 to stop; `.clear()` is sent to the iPhone so the spoof releases cleanly. Stop tunneld in Terminal 1 when you're done.

Optional pre-flight: `./scripts/bootstrap.sh` runs sanity checks (Python version, `pymobiledevice3` importable, Developer Mode hints). Not required.

### UI preview without an iPhone

```bash
python -m trail_simulator --dev-no-device
```

This skips all device calls and uses a stub — useful for trying out the map and controls.

## Home base station (recommended)

Turn a dedicated Mac (mini, iMac, or a docked laptop) into an always-on Trail
Simulator base station. Once set up, the day-to-day flow is: open the Safari
bookmark on the iPhone → pick pins → Walk. No terminal, no cable, no sudo
prompts.

Two launchd jobs are installed:

- `com.trail-simulator.tunneld` — **LaunchDaemon** (root, needs `utun`),
  auto-starts at boot before any user logs in. Logs to
  `/var/log/trail-simulator/tunneld.log`.
- `com.trail-simulator.app` — **LaunchAgent** (your user), starts at login.
  Logs to `./.trail-simulator-app.log` in the project root.

**Why sudo at install.** `pymobiledevice3` creates a kernel `utun` interface for
RemoteXPC to reach the iPhone — every tunnel variant in the library is marked
`@sudo_required`, so there is no non-root path on iOS 17+. The LaunchDaemon
setup means you pay that cost once at install; afterwards tunneld runs as root
via launchd and your day-to-day `python -m trail_simulator` (or the Safari
bookmark) runs as your normal user without any prompts.

### One-time setup

On the iPhone (USB-tethered for this step):

1. **Developer Mode ON** — Settings → Privacy & Security → Developer Mode →
   toggle → reboot → confirm with passcode. Required on iOS 17+; no way around
   it.
2. Plug into the Mac, accept **Trust This Computer**, enter passcode.
3. Finder → iPhone sidebar → **General** tab → check **"Show this iPhone when
   on Wi-Fi"**. This is what lets tunneld reach the device over LAN after the
   cable is removed.

On the Mac:

4. Clone the repo, create the venv, install requirements (same as the dev
   install above).
5. (Optional but bookmarkable) give the Mac a memorable hostname:
   ```bash
   sudo scutil --set LocalHostName trail-mac
   ```
   You can now reach it at `http://trail-mac.local:8787`.
6. Enable **Automatic login** (System Settings → Users & Groups) so the
   LaunchAgent comes up after reboot without human intervention.
7. Prevent automatic sleep on power:
   ```bash
   sudo pmset -a sleep 0
   ```
   A sleeping Mac means no GPS updates mid-walk.
8. Install both services:
   ```bash
   sudo ./scripts/install.sh
   ```
   The installer is idempotent — re-run it any time you pull new code.
9. First launch of tunneld will trigger the macOS **Local Network** permission
   prompt (attributed to `python`). Approve it once.

On the iPhone (no cable needed from here on):

10. Open Safari → `http://trail-mac.local:8787` → bookmark / Add to Home
    Screen.

### Uninstall

```bash
sudo ./scripts/uninstall.sh
```

Removes both plists and boots out both services. Logs and `trail-simulator.db`
are left in place.

### Known gotchas

- **iPhone Wi-Fi deep-sleep.** When the phone is idle with screen off, iOS
  aggressively sleeps its Wi-Fi radio and tunneld will see the device drop.
  DVT will reconnect via backoff but you'll see a multi-second gap in
  commanded GPS. Keep the phone on a charger, or leave USB plugged in — the
  cable stays an option even though it's no longer required.
- **Reboot + nobody home.** LaunchAgent only starts after user login. Auto-
  login solves this but puts the Mac's disk at risk if stolen. Accept the
  trade-off on a home-only Mac, or flip the app to LaunchDaemon (not default
  — web server would then run as root).
- **Local Network permission can be revoked.** macOS periodically re-prompts.
  If tunneld silently stops seeing the iPhone, check System Settings →
  Privacy & Security → Local Network.
- **LAN-only, no auth.** The UI binds to `0.0.0.0` — anyone on your Wi-Fi can
  drive the iPhone's fake GPS. Acceptable on a trusted home network. For
  remote access, install Tailscale on both devices; no code change needed.
- **Bonjour quirk.** If `.local` resolution fails, fall back to the Mac's LAN
  IP (installer prints both at the end).

## Safety gates

Three independent gates reject unsafe tick commands before they reach the device:

1. **Speed cap** — rejects anything implying > 20 km/h between two ticks.
2. **Per-tick jump cap** — rejects jumps > 5 m per tick (CoreLocation smoothing).
3. **Cooldown table** — distance-based cooldown; blocks a long-distance reposition until the settle timer elapses.

Cooldown state persists in `trail-simulator.db` (SQLite) across restarts.

## Known limits

- `CLLocation.course` is NaN when injected via DVT (apps reading heading will see this).
- `horizontalAccuracy` is not settable; some strict anti-cheat could flag it.
- USB re-enumerate causes a brief gap; auto-reconnect is best-effort.
- No step-count / HealthKit spoofing (out of scope; would require jailbreak).

## Disclaimer

Trail Simulator is a developer tool for testing location-aware apps under controlled GPS conditions. You are responsible for compliance with the Terms of Service of any third-party app or service you point it at. The built-in speed cap, jump cap, and cooldown table model realistic pedestrian movement — they are safety primitives, not a license to use the tool against services that prohibit location simulation. The authors accept no liability for account actions, bans, or other consequences of use.

No part of this tool requires a jailbreak or modifies the iPhone. All GPS injection uses the same public `pymobiledevice3` DVT path that Xcode's "Simulate Location" feature uses.

## License

MIT — see [`LICENSE`](./LICENSE).
