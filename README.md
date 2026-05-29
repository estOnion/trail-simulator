# Trail Simulator

**Mac-controlled iPhone GPS route simulator.** Click two points on a map, pick a walking speed, and watch a tethered (or LAN-connected) iPhone follow the route in real time.

No jailbreak, no sideloading, no modifications to the iPhone — built on the same public developer-disk interface ([`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3)) that Xcode's "Simulate Location" feature uses.

## Features

- Click-to-route planning over OpenStreetMap + Leaflet
- **Address search** — type a place name to jump the map (Nominatim)
- Realistic pedestrian pacing — ≤ 20 km/h speed cap, ≤ 5 m per-tick jump cap
- 7-day cooldown table for long-distance repositions, persisted in SQLite across restarts
- **Multi-device mirror mode** — drive several iPhones in lockstep with `--udid` repeated
- **Wi-Fi-only operation** — once paired and `wifi-connections on`, no cable needed
- **Home base station** mode — install once with `sudo`, then drive the iPhone from a Safari bookmark on the phone. No terminal, no cable, no sudo prompts after install.
- **Step counter** (built into TrailController) — the Health tab in the TrailController iOS app writes step count + walking distance into HealthKit in sync with the simulated route
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

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
uv run trail-simulator        # equivalent to `python -m trail_simulator`
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

### Multi-device mirror mode

Drive two or more iPhones in lockstep — same route, same pace, same GPS tick — by
repeating `--udid`:

```bash
python -m trail_simulator \
  --udid 00008150-001964DA3C02401C \
  --udid 00008150-001A029A0CE2401C \
  --host 0.0.0.0 --port 8080
```

Each device gets its own `LocationSimulation` session under the hood; per-device
failures are logged but do not abort the shared session — each inner client
reconnects on the next tick via its own backoff.

### Wi-Fi-only operation (no cable)

Once an iPhone has been paired over USB at least once, you can run cable-free:

```bash
# one-time, with the cable still attached:
python3 -m pymobiledevice3 lockdown wifi-connections on
```

Unplug. As long as the phone is on the same LAN as the Mac and `tunneld` is
running, preflight will discover it over Bonjour/RemoteXPC. Discovery can take
several seconds on the first attempt after `tunneld` starts — trail-simulator
polls for up to ~8 s before reporting "device not found".

### Address search

Type a place name (e.g. `"Yoyogi Park, Tokyo"`) into the search box and hit
Enter to jump the map. Powered by OSM Nominatim — please respect their fair-use
policy (no high-volume autosuggest, identifying User-Agent already set).

### Connect TrailController (iOS app) to the backend

TrailController is sideloaded onto the same iPhone whose GPS the backend is
spoofing. It controls the route from a native UI and (via the Health tab)
writes steps to HealthKit. To reach the backend it needs the Mac's LAN address
— `127.0.0.1` won't work from the phone.

1. Start the backend bound to the LAN, on **port 8080**:
   ```bash
   uv run trail-simulator --host 0.0.0.0 --port 8080
   ```
   > **Port 8080, not 8787.** pymobiledevice3's RSD tunnel listens on
   > `127.0.0.1:8787` *on the iPhone itself*. If the backend also runs on
   > 8787, the phone's outbound LAN request gets intercepted by its own
   > tunnel and GPS spoofing silently fails. Any free port other than 8787
   > works; 8080 is the convention used here.

2. Find the Mac's LAN IP (not the router gateway):
   ```bash
   ipconfig getifaddr en0       # Wi-Fi
   # or ipconfig getifaddr en1  # Ethernet
   ```

3. On the iPhone, open TrailController → **Settings** tab → set
   `http://<mac-LAN-IP>:8080` → **Test connection** → **Save**. The Map tab's
   state pill should turn green once `/ws/live` connects.

4. (Optional) First launch will prompt for **Local Network** and (if you
   plan to use the Health tab) **HealthKit** permission. Grant both.

If the connection fails, confirm:
- iPhone and Mac are on the same Wi-Fi subnet.
- macOS firewall isn't blocking Python (System Settings → Network → Firewall).
- The backend is actually bound to `0.0.0.0` (you'll see it in the
  trail-simulator startup log).

### Step counter (built into TrailController)

For apps that read step count or walking distance from HealthKit, use the
**Health tab** in the TrailController iOS app (`controller-ios/`). While
trail-simulator runs a route, the backend streams per-tick step deltas (derived
from distance ÷ configured stride) over WebSocket to TrailController, which
writes `HKQuantityTypeIdentifier.stepCount` and `.distanceWalkingRunning`
samples directly to HealthKit on the same phone.

See [`controller-ios/README.md`](./controller-ios/README.md) for sideload
instructions. Stride length and the feature toggle live in
`trail_simulator/config.py` (`stride_length_m`, `step_companion_enabled`).

> **Scope note.** HealthKit writes cover most apps that read step data via the
> public `HKHealthStore` API. Apps that consult `CMPedometer` live (motion
> coprocessor) will not see these writes — that path is out of scope for this
> project.

## Connecting multiple iPhones to one backend

TrailController supports running an independent session on each iPhone connected to the same Mac and the same backend. Each iPhone gets its own spoofed GPS track without interfering with the others.

**How it works**

- The backend builds a registry mapping each `--udid` to that iPhone's DeviceName (Settings → General → About → Name) at startup.
- Each TrailController iPhone sends `UIDevice.current.name` in the `X-Device-Name` HTTP header and the `?device=` WebSocket query on every request.
- The backend routes the request to the matching session — one `SessionController` per UDID.

**Setup**

1. Make sure every iPhone has a **unique** name in Settings → General → About → Name. The backend will refuse to start if two iPhones share a name.
2. Plug each iPhone into the Mac via USB (or use Wi-Fi pairing once they're paired). Tap "Trust".
3. Run `sudo pymobiledevice3 remote tunneld` and keep it running.
4. Start the backend with one `--udid` flag per iPhone:

   ```bash
   python -m trail_simulator --port 8080 \
     --udid 00008140-001A2B3C4D5E6F70 \
     --udid 00008130-005ABCDE12345678
   ```

   On startup you'll see `[devices] parallel session mode for 2 devices: Jack iPhone, Spare iPhone`.

5. On **each iPhone**, install TrailController and point Settings → Backend at `http://<your-mac-LAN-ip>:8080`. No further configuration is needed — the app auto-binds by DeviceName.

**Verify**

```bash
curl http://127.0.0.1:8080/api/devices
# {"devices":[{"udid":"00008140-...","name":"Jack iPhone"}, ...]}

curl -H "X-Device-Name: Jack iPhone" http://127.0.0.1:8080/api/status
# {"state":"idle", ...}
```

**Falling back to mirror mode**

If you want one session that fans out to multiple iPhones (the original behaviour — useful for keeping a spare phone in sync with the primary), add `--mirror`:

```bash
python -m trail_simulator --port 8080 --mirror \
  --udid 00008140-... --udid 00008130-...
```

In mirror mode only the primary iPhone's DeviceName is registered; all spoofed devices follow that one session.

**Troubleshooting**

- *"No backend device registered for name 'X'"*: the iPhone's name isn't in the backend's startup list. Confirm with `curl /api/devices` and rename the iPhone or re-launch the backend with the right `--udid`.
- *"Multiple devices registered; send X-Device-Name header"*: someone hit a backend endpoint without the header while two or more devices are registered. The web frontend always falls back to the first device; this only affects custom tooling.
- Two iPhones with the same name: the backend will exit on startup. Rename one in Settings → General → About → Name.

## Per-iPhone UUID identity & following a leader

Each TrailController iPhone carries a **UUID** (Settings → Identity). It defaults
to the device name and can be edited to any unique string. The app sends it as
`X-Client-Id` on every request; the backend binds the UUID to the connected
device and routes that iPhone's session by it, so two phones never share a
session. (The `X-Device-Name` path above remains as a fallback for the web
frontend and single-device setups.)

- **Uniqueness:** on Save the app calls `POST /api/bind`; if another device
  already holds that UUID the backend returns `409` and the change is rejected.
- **Single device:** the UUID auto-binds — no device picking needed.
- **Multiple devices:** pick this iPhone in Settings → Device, then save the UUID.

**Following a leader** (Map → Follow button):

- *Watch on map only* — your map shows the leader's live position; your phone is
  untouched.
- *Mirror onto this phone (GPS)* — your phone's spoofed GPS tracks the leader's
  route (`POST /api/follow`). Tap **Stop** to end (`POST /api/unfollow`).

```bash
curl -H "X-Client-Id: my-uuid" http://127.0.0.1:8080/api/status
curl http://127.0.0.1:8080/api/clients   # active leaders to follow
```

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
- Step counts reach HealthKit only when the TrailController iOS app is sideloaded and its Health tab is enabled; apps that read live `CMPedometer` (motion coprocessor) data will not see the writes.

## Disclaimer

Trail Simulator is a developer tool for testing location-aware apps under controlled GPS conditions. You are responsible for compliance with the Terms of Service of any third-party app or service you point it at. The built-in speed cap, jump cap, and cooldown table model realistic pedestrian movement — they are safety primitives, not a license to use the tool against services that prohibit location simulation. The authors accept no liability for account actions, bans, or other consequences of use.

No part of this tool requires a jailbreak or modifies the iPhone. All GPS injection uses the same public `pymobiledevice3` DVT path that Xcode's "Simulate Location" feature uses.

## License

MIT — see [`LICENSE`](./LICENSE).
