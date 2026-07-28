# Trail Simulator

Mac-controlled iPhone GPS route simulator. Click two points on a map, pick a
walking speed, and a tethered (or LAN-connected) iPhone follows the route in
real time.

No jailbreak and nothing installed on the phone. GPS injection goes through the
same public developer-disk interface ([`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3))
that Xcode's "Simulate Location" uses.

Running the host on Windows instead? See [docs/WINDOWS.md](docs/WINDOWS.md).

## Features

- Click-to-route planning over OpenStreetMap + Leaflet, with address search
- Speed cap (20 km/h) and per-tick jump cap (6.5 m) on every command
- Travel-time cooldown on long repositions, persisted in SQLite across restarts
- Independent parallel sessions across several iPhones, or `--mirror` to drive
  them in lockstep
- Rooted Android 12+ over `adb`, no app on the phone, mixable with iPhones
- Cable-free once the phone is paired and `wifi-connections on`
- Home base station install: launchd jobs, then drive it from a Safari bookmark
  (written but never run on real hardware)
- Step counts written to HealthKit by the TrailController iOS app
- `--dev-no-device` preview mode for working on the UI with no phone attached
- FastAPI + WebSocket backend, vanilla JS + Leaflet frontend

## How it works

The Mac runs a local FastAPI server and `pymobiledevice3`'s `tunneld`. Tunneld
creates a kernel `utun` interface and speaks RemoteXPC to the iPhone over USB or
LAN; the app streams `CLLocation` updates through DVT at ~1 Hz. A browser on the
iPhone (or anything on the same Wi-Fi) drives the session over HTTP. Cooldown
state lives in a local SQLite DB so the anti-teleport gate survives restarts.

## Requirements

- macOS 13+ (Sequoia tested)
- Python 3.11+
- iPhone with Developer Mode on (Settings → Privacy & Security → Developer Mode)
- iPhone trusted ("Trust This Computer"), tethered via USB at least once
- `sudo`, for `tunneld` on iOS 17+

## Setup

```bash
uv sync
```

Or with a plain venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

Two terminals. The first one runs tunneld as root and stays open:

```bash
sudo "$PWD/.venv/bin/pymobiledevice3" remote tunneld
```

`pymobiledevice3` lives in the venv and `sudo` resets `PATH`, so use the full
path (from the project root). A global install can just use
`sudo pymobiledevice3 remote tunneld`.

The second runs the app:

```bash
uv run trail-simulator          # or: python -m trail_simulator
```

The UI opens at http://127.0.0.1:8787. Click an origin and a destination, pick a
speed, press **Walk**. `Ctrl-C` stops it and sends `.clear()` so the spoof
releases cleanly.

This two-terminal flow is the path that's actually been used. There's also an
always-on [home base station](#home-base-station) setup that skips both
terminals, but it hasn't been tested on real hardware.

`./scripts/bootstrap.sh` runs optional sanity checks (Python version,
`pymobiledevice3` importable, Developer Mode hints).

### Without a phone

```bash
python -m trail_simulator --dev-no-device
```

Skips preflight and swaps in a stub device, so you can poke at the map and
controls.

### Without a cable

Pair over USB and accept Trust, then enable Wi-Fi visibility — Trust alone is
not enough. Either tick **Show this iPhone when on Wi-Fi** in Finder → iPhone →
General, or, while still cabled:

```bash
pymobiledevice3 lockdown wifi-connections --state on --udid <UDID>
pymobiledevice3 lockdown wifi-connections --udid <UDID>   # reads it back
```

Unplug, then confirm the phone advertises itself:

```bash
dns-sd -B _apple-mobdev2._tcp   # one Add line per Wi-Fi-visible device
```

If it's missing, unlock the phone and toggle Wi-Fi off and on — iOS only
re-announces on a network transition — and check it shares a subnet with the
Mac. The instance name is a MAC address, but iOS uses a private Wi-Fi address
per network, so it won't match `lockdown info`.

Once it appears and tunneld is running, preflight finds it over
Bonjour/RemoteXPC. The first discovery after tunneld starts can be slow;
trail-simulator polls for ~8 s before giving up.

### Address search

Type a place name into the search box and hit Enter to jump the map. Powered by
OSM Nominatim, so respect their fair-use policy (no high-volume autosuggest; the
identifying User-Agent is already set).

## Multiple devices

Every connected iPhone is discovered at startup and while the backend runs, each
with its own session. Pass `--udid` (repeatable) to restrict it to an allow-list:

```bash
python -m trail_simulator --port 8080 \
  --udid 00008140-001A2B3C4D5E6F70 \
  --udid 00008130-005ABCDE12345678
```

Requests are routed to a session by identity. TrailController sends a UUID as
`X-Client-Id` (Settings → Identity, defaults to the device name); the web
frontend falls back to `X-Device-Name`, the iPhone's name from Settings →
General → About → Name. Two devices can't register the same name or the same
UUID — a conflicting `POST /api/bind` gets a `409`, and a duplicate name is
refused at registration. An unknown identity binds itself when it matches a
connected device's name, or when only one device is connected; anything else
needs an explicit `POST /api/bind`.

```bash
curl http://127.0.0.1:8080/api/devices
curl -H "X-Device-Name: Jack iPhone" http://127.0.0.1:8080/api/status
curl http://127.0.0.1:8080/api/clients   # leaders available to follow
```

**Following a leader** (Map → Follow in TrailController): *watch on map only*
leaves your phone alone and just mirrors the leader's position onto your map;
*mirror onto this phone* spoofs your GPS along the leader's route
(`POST /api/follow`, ended by `POST /api/unfollow`).

**Mirror mode** (`--mirror`) is the older behaviour: one session fanned out to
every `--udid` device, same route and same tick. Useful for keeping a spare
phone in sync. Only the primary's DeviceName is registered, and it can't be
combined with `--android`.

```bash
python -m trail_simulator --port 8080 --mirror --udid 00008140-... --udid 00008130-...
```

Per-device failures are logged but don't abort the shared session; each inner
client reconnects on its own backoff.

**When a device won't bind:** `No backend device registered for name 'X'` means
the phone's name isn't in the registry — check `/api/devices` and rename the
phone or relaunch with the right `--udid`. `Multiple devices registered; send
X-Device-Name header` means a request arrived without an identity header while
more than one device is registered, which only affects custom tooling. A `403`
on `/ws/live` is an identity that couldn't auto-bind — usually a client id
overridden in Settings → Identity so it no longer matches its device name.

## Rooted Android

The backend can drive a rooted Android 12+ (API 31+) phone instead of, or
alongside, iPhones in the same process. It uses Android's built-in `cmd
location` test-provider commands over `adb`, so nothing is installed on the
phone.

This one is experimental. It's validated against a stubbed `adb` in tests, but
real-device behaviour varies — apps reading Google Play Services *fused*
location may ignore the test provider even with root. Check it against your
target app before relying on it.

You need root, `adb` on `PATH`, USB debugging enabled with the Mac authorized,
and `adb root` available. Confirm the phone shows up as `device` (not
`unauthorized` or `offline`) in `adb devices`, then:

```bash
python -m trail_simulator --android RZ8N1234ABC --port 8080
```

You should see `[android] RZ8N1234ABC ready (API 33, Pixel 7)`. Targeting
Android only means tunneld isn't needed at all. Pick the phone in the **Device**
dropdown, plan a route, press **Walk**; **Stop** / **Reset to real GPS** removes
the test provider and hands the phone back its real location.

Combine `--android` with `--udid` to run both kinds at once — each gets an
independent session, and both show up in the Device picker tagged `ios` or
`android`.

Under the hood, per session and as root via `su -c`: `providers
add-test-provider gps` + `enable-test-provider gps` on start,
`set-test-provider-location gps --location <lat>,<lon>` every tick,
`remove-test-provider gps` on reset. Auto-reconnect polls `adb get-state`.

Two failures worth naming: `not online via adb` means the serial isn't in `adb
devices` as `device` (replug, re-accept the prompt, or bounce the adb server),
and `is API N; need Android 12+` means the phone predates
`set-test-provider-location` and would need an on-phone helper, which isn't
implemented.

## TrailController (iOS app)

TrailController is sideloaded onto the same iPhone whose GPS is being spoofed.
It replaces the browser with a native UI and writes step counts to HealthKit.
See [`controller-ios/README.md`](./controller-ios/README.md) for sideload
instructions.

To reach the backend it needs the Mac's LAN address, not `127.0.0.1`:

```bash
uv run trail-simulator --host 0.0.0.0 --port 8080
ipconfig getifaddr en0       # Wi-Fi; en1 for Ethernet
```

Use **port 8080, not 8787.** pymobiledevice3's RSD tunnel listens on
`127.0.0.1:8787` *on the iPhone itself*, so a backend on 8787 gets the phone's
own outbound request intercepted by its own tunnel, and spoofing silently
fails. Any other free port works.

On the iPhone: TrailController → **Settings** → `http://<mac-LAN-IP>:8080` →
**Test connection** → **Save**. The Map tab's state pill turns green once
`/ws/live` connects. First launch asks for Local Network permission, plus
HealthKit if you want the Health tab.

If it won't connect, check that both are on the same Wi-Fi subnet, that the
macOS firewall isn't blocking Python (System Settings → Network → Firewall), and
that the startup log really shows a bind to `0.0.0.0`.

### Step counter

While a route is running, the backend streams per-tick step deltas (distance ÷
configured stride) over WebSocket to TrailController, which writes
`stepCount` and `distanceWalkingRunning` samples into HealthKit on the same
phone. Stride length and the feature toggle are in `trail_simulator/config.py`
(`stride_length_m`, `step_companion_enabled`).

This covers apps that read step data through the public `HKHealthStore` API.
Apps that poll `CMPedometer` live talk to the motion coprocessor and won't see
these writes. That path is out of scope.

## Home base station

**Untested on real hardware.** The install scripts and launchd jobs are written
and the flow below is what they're meant to do, but none of it has been run on
an actual always-on Mac with a real iPhone. Expect to debug it. In particular,
the installer serves on port 8787, which is the port the
[TrailController section](#trailcontroller-ios-app) warns against for a
physical iPhone — whether that collision applies to a LAN hostname in Safari or
only to the phone's loopback is exactly the kind of thing this needs testing to
settle.

The idea: turn a dedicated Mac into an always-on base station, so day-to-day use
is opening the Safari bookmark on the iPhone, picking pins, and pressing Walk.
No terminal, no cable, no sudo prompts.

Two launchd jobs get installed:

- `com.trail-simulator.tunneld` — LaunchDaemon, runs as root (it needs `utun`)
  and starts at boot before anyone logs in. Logs to
  `/var/log/trail-simulator/tunneld.log`.
- `com.trail-simulator.app` — LaunchAgent, runs as you, starts at login. Logs to
  `./.trail-simulator-app.log`.

The sudo is unavoidable at install time: every tunnel variant in
`pymobiledevice3` is marked `@sudo_required` because it creates a kernel `utun`
interface. Installing tunneld as a LaunchDaemon means you pay that once, and
day-to-day use runs as your normal user.

Setup, on a USB-tethered iPhone:

1. Developer Mode on, reboot, confirm with passcode.
2. Plug in, accept Trust This Computer.
3. Finder → iPhone → General → check **Show this iPhone when on Wi-Fi**. This is
   what lets tunneld reach it after the cable comes out.

Then on the Mac:

4. Clone, create the venv, install (as above).
5. Optionally give it a memorable hostname so the bookmark is nicer:
   `sudo scutil --set LocalHostName trail-mac` → `http://trail-mac.local:8787`.
6. Turn on automatic login, so the LaunchAgent comes back after a reboot without
   a human present.
7. `sudo pmset -a sleep 0` — a sleeping Mac means no GPS updates mid-walk.
8. `sudo ./scripts/install.sh`. It's idempotent; re-run it after pulling.
9. Approve the Local Network prompt on tunneld's first launch (it's attributed
   to `python`).

Finally, on the iPhone: Safari → `http://trail-mac.local:8787` → bookmark or Add
to Home Screen.

`sudo ./scripts/uninstall.sh` removes both plists and boots the services out.
Logs and `trail-simulator.db` stay put.

### Gotchas

- **Wi-Fi deep sleep.** Idle with the screen off, iOS sleeps the Wi-Fi radio and
  tunneld sees the device drop. DVT reconnects on backoff, but expect a
  multi-second gap in commanded GPS. Keep the phone charging, or leave the cable
  in.
- **Reboot with nobody home.** The LaunchAgent only starts after login. Auto-
  login fixes that at the cost of leaving the disk unlocked; fine on a home-only
  Mac. The alternative is running the app as a LaunchDaemon too, which puts the
  web server under root.
- **Local Network permission gets revoked.** macOS re-prompts periodically. If
  tunneld quietly stops seeing the phone, check System Settings → Privacy &
  Security → Local Network.
- **No auth.** Bound to `0.0.0.0`, anyone on your Wi-Fi can drive the phone's
  fake GPS. Fine on a trusted network. For remote access, put Tailscale on both
  ends; no code change needed.
- **Bonjour.** If `.local` won't resolve, use the LAN IP — the installer prints
  both.

## Safety gates

Three independent gates reject unsafe commands before they reach the device:

1. **Speed cap** — anything implying more than 20 km/h between two ticks.
2. **Per-tick jump cap** — jumps over 6.5 m per tick, which is 20 km/h at 1 Hz
   plus a little headroom for perpendicular wobble.
3. **Cooldown** — a long reposition has to wait out the time it would
   realistically take to travel that distance, assumed at 60 km/h. A 60 km jump
   costs an hour. Tunable via `cooldown_transit_kmh`.

Cooldown state persists in `trail-simulator.db` across restarts.

## Tests

```bash
uv run pytest
```

CI runs the same suite on Python 3.11 and 3.13. The iOS tests live in
`controller-ios/` and run under `xcodebuild test`.

## Known limits

- `CLLocation.course` is NaN when injected via DVT, so anything reading heading
  will see that.
- `horizontalAccuracy` isn't settable; strict anti-cheat could flag it.
- A USB re-enumerate causes a brief gap. Auto-reconnect is best-effort.
- Step counts only reach HealthKit with TrailController sideloaded and its
  Health tab on.

## Disclaimer

Trail Simulator is a developer tool for testing location-aware apps under
controlled GPS conditions. You're responsible for complying with the terms of
service of anything you point it at. The speed cap, jump cap, and cooldown model
realistic pedestrian movement — they're safety primitives, not a license to use
this against services that prohibit location simulation. No liability is
accepted for account actions or bans.

Nothing here requires a jailbreak or modifies the iPhone.

## License

MIT — see [`LICENSE`](./LICENSE).
