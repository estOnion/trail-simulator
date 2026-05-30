# Android Device Support (single backend, mixed device types) — Design

**Date:** 2026-05-30
**Branch:** main (work to be branched per finishing-a-development-branch)
**Status:** Approved for planning

## Problem

The backend can only inject GPS into iPhones (pymobiledevice3 over tunneld).
Users also want to spoof a **physical Android phone** from the *same* backend,
controlled from the existing web frontend (and, transitively, the iOS app's
device list). Today there is no Android device adapter, no Android discovery,
and the web frontend has no way to choose *which* physical device it drives —
it silently relies on there being exactly one device.

## Goals

1. **Android GPS injection:** drive a rooted, **Android 12+ (API 31+)** physical
   phone over USB/ADB using the built-in `cmd location` test-provider shell
   commands — **no companion app installed on the phone**.
2. **Single backend, mixed device types:** one backend process drives iPhones
   *and* Android phones simultaneously. iOS UDIDs and Android ADB serials are
   both opaque session keys in the existing `SessionManager` / `DeviceRegistry`.
3. **Device selection in the web frontend:** a device picker so the user chooses
   which physical device (iPhone or Android) the web UI controls, sent on every
   request. Required because a mixed setup always has 2+ devices, which makes the
   current device-less web requests ambiguous (HTTP 400).

## Non-Goals

- **Non-rooted Android** or **Android ≤ 11.** Those need an on-phone artifact
  (appops + a pushed `app_process` server or a companion APK). Explicitly
  deferred; the adapter interface is designed so that path can slot in later
  without touching the session core.
- **Android in `--mirror` mode.** Legacy iOS fan-out (`MultiLocationClient`)
  stays iOS-only in v1.
- **Guaranteeing Google Play Services *fused* location is fooled.** Root improves
  this, but it is device/app-specific and can only be confirmed by on-device
  testing (see "Residual Risk").
- **Per-device cooldown isolation.** The shared `Store.last_fix` is already
  global across controllers (a pre-existing multi-iPhone trait); this work does
  not change it.

---

## Architecture Overview

The backend already isolates the physical device behind a three-method contract.
`SessionController` only ever calls `await device.open()`, `await device.set(lat,
lon)`, and `await device.clear()`, and treats `DeviceUnavailable` as the failure
signal. `SessionManager` builds devices through a `device_factory: Callable[[id]
-> <device>]` keyed by an opaque string. Routing (`_resolve` in `api/rest.py`)
maps a request to a controller by client-id → device-name → single-device
default, all device-type agnostic.

Adding Android is therefore an **adapter swap plus discovery**, not a change to
sessions, routing, or the WebSocket:

```
            (unchanged)                       (new / changed)
  request → _resolve → SessionManager → SessionController → LocationInjector
                                                              ├─ LocationClient        (iOS, existing)
                                                              └─ AndroidLocationClient (new, adb)
```

The only component that must know "iOS vs Android" is the **factory** in
`main.py`, which knows each key's type from the CLI flag it came from
(`--udid` vs `--android`).

---

## Component Design

### Backend

#### `LocationInjector` protocol (new) — `device/injector.py`

Extract the contract `SessionController` already depends on into an explicit
`typing.Protocol` so iOS and Android adapters are interchangeable:

```python
class LocationInjector(Protocol):
    async def open(self) -> None: ...
    async def set(self, lat: float, lon: float) -> None: ...
    async def clear(self) -> None: ...
    async def reachable(self) -> bool: ...
```

- `reachable()` is **new** and exists to decouple auto-resume from iOS-only
  `tunneld_reachable` (see below).
- `DeviceUnavailable` (already in `device/location.py`) moves to / is re-exported
  from a shared location so both adapters raise the same type. Keep the import
  path `device.location.DeviceUnavailable` working (re-export) to avoid churn.

`LocationClient` (iOS) gains `async def reachable(self)` returning
`tunneld_reachable()`. No other iOS behavior changes. `_StubLocation` (dev mode)
inherits it.

#### `AndroidLocationClient` (new) — `device/android_location.py`

Implements `LocationInjector` by shelling out to `adb` for one ADB serial. All
commands run as root (`adb -s <serial> shell su -c '<cmd>'`) to avoid mock-app
appop configuration; the exact privilege escalation is encapsulated here.

- `open()`:
  ```
  cmd location providers add-test-provider gps \
    --requiresNetwork false --requiresSatellite false --requiresCell false \
    --hasMonetaryCost false --supportsAltitude true --supportsSpeed true \
    --supportsBearing true --powerRequirement 1
  cmd location providers enable-test-provider gps
  ```
  Idempotent: if the provider already exists, treat the "already added" stderr as
  success. Raise `DeviceUnavailable` if `adb` is missing or the serial is offline.
- `set(lat, lon)`:
  ```
  cmd location providers set-test-provider-location gps \
    --location <lat>,<lon> --accuracy 5
  ```
  Wrapped in `asyncio.wait_for(..., timeout=SETTINGS.device_set_timeout_s)` to
  match the iOS stall→reconnect behavior. On `CalledProcessError`/timeout, raise
  `DeviceUnavailable`.
- `clear()`:
  ```
  cmd location providers remove-test-provider gps
  ```
  Returns the phone to real GPS — the Android analog of iOS DVT clear. Best-effort
  (swallow errors, like iOS `clear()`).
- `reachable()`: `adb -s <serial> get-state` → `True` when output is `device`.

**Freeze semantics:** on normal stop the controller does *not* call `clear()`
(it keeps the last point frozen). For Android this means the test provider stays
registered holding the last `set` location; `reset_device`/error calls `clear()`
to release. Behavioral note: while frozen (no further `set` calls), apps with
*active* update subscriptions stop receiving new fixes but `getLastKnownLocation`
returns the held point — close enough to iOS freeze for our use.

All `adb` invocation goes through one private `async _adb(*args)` helper
(`asyncio.create_subprocess_exec`, captured output, non-zero → typed error) so
the command surface is testable by stubbing that single seam.

#### `DeviceRegistry` (extended) — `device/registry.py`

Add an optional per-key **device type** so `/api/devices` can label entries and
the frontend can badge them. Keep the existing name↔key and client↔key maps
exactly as-is (keys remain opaque strings; Android serials register the same way
UDIDs do).

- `register(udid, name, device_type="ios")` — new defaulted param; existing iOS
  callers unchanged. Stores `self._type_by_id[udid] = device_type`.
- `type_for(udid) -> str` — returns `"ios"` / `"android"` (default `"ios"` for
  any key registered before the field existed).

#### Android discovery — `device/android.py` (new)

- `list_android_devices() -> list[tuple[serial, model_name]]`:
  `adb devices` for online serials, then
  `adb -s <serial> shell getprop ro.product.model` for a human name
  (e.g. `"Pixel 7"`). Skip `unauthorized`/`offline` serials.
- `android_sdk_int(serial) -> int`: `getprop ro.build.version.sdk`. Used by
  preflight to enforce API ≥ 31.

#### `SessionManager` (type-only change) — `session/manager.py`

`DeviceFactory` becomes `Callable[[str], LocationInjector]`. No logic change —
`_StubLocation` and `MultiLocationClient` already satisfy the protocol
structurally (they expose `open/set/clear`; add `reachable()` to
`MultiLocationClient` returning `True`/aggregate so it stays conformant).

#### `SessionController` auto-resume decoupling — `session/controller.py`

`_auto_resume()` currently does `from ..device.tunneld import tunneld_reachable`
and polls it. Replace that poll with `await self._device.reachable()` so the
reconnect loop is device-agnostic (iOS polls tunneld, Android polls `adb
get-state`). No other controller change; the `device:`-prefixed error contract is
preserved by both adapters.

#### `main.py` wiring

- New CLI flag `--android SERIAL` (append, repeatable), parallel to `--udid`.
- **Preflight** for each `--android` serial: `adb` on PATH, serial state
  `device`, `android_sdk_int >= 31` (else fail with a clear message), and a root
  check (`adb -s <serial> shell su -c id` → warn, not fail, if root is absent —
  injection may still work via appops on some devices).
- Build the registry: register `--udid` keys as `"ios"`, `--android` serials as
  `"android"` (name from `ro.product.model`).
- Build the factory closure over the two key sets:
  ```python
  android = set(args.android)
  def _factory(key: str) -> LocationInjector:
      return AndroidLocationClient(key) if key in android else LocationClient(udid=key)
  ```
- `--mirror` remains iOS-only; reject combining `--mirror` with `--android` with
  a clear error.
- `--dev-no-device` unchanged (stub).

#### REST — `api/rest.py`

Single additive change: `GET /api/devices` entries gain `"type"`:
`{"udid", "name", "bound_client_id", "type"}` where `type = registry.type_for(u)`.
Routing/`_resolve` is unchanged — Android phones are addressed by name exactly
like iPhones.

### Frontend (web) — `frontend/static/`

Today `app.js` sends no device identifier and relies on the single-device
default. A mixed setup has ≥2 devices, so every request would 400
("Multiple devices registered; send X-Device-Name header."). Add a minimal
picker:

- **`index.html`:** a `<select id="device-select">` in the panel header,
  plus an iOS/Android label per option.
- **`app.js`:**
  - On load and after WS reconnect, `GET /api/devices`; populate the dropdown as
    `"<name> · <type>"`. Persist the chosen device name in `localStorage`;
    default to the first device if none stored or the stored one is gone.
  - A single `selectedDevice()` accessor. Send it on **every** REST call as the
    `X-Device-Name` header (wrap the existing `fetch` calls in a small
    `api(path, opts)` helper that injects the header), and append
    `?device=<name>` to the `/ws/live` WebSocket URL.
  - Changing the dropdown re-opens the WS against the newly selected device and
    refreshes status from `GET /api/status`.

This reuses the existing legacy device-name routing path; no new backend route is
needed. The iOS app already has its own device selection and is unaffected.

---

## Data Flow

**Android control (web frontend):**
```
web select(name) → X-Device-Name → _resolve → registry → serial
  → SessionManager → SessionController → AndroidLocationClient
  → adb shell cmd location set-test-provider-location → Android GPS
```

**Mixed backend startup:**
```
main --udid AAA --android RZ8N... 
  → registry.register(AAA, "...", "ios"), register(RZ8N..., "Pixel 7", "android")
  → factory dispatches per key
```

**Android reconnect:** `set()` fails → `DeviceUnavailable` → controller enters
`reconnecting` → `_auto_resume` polls `AndroidLocationClient.reachable()`
(`adb get-state`) → resumes from last fix when the phone is back.

---

## Error Handling

- **`adb` missing / serial offline / not API 31+** → preflight fails fast with an
  actionable message; the device is never registered.
- **`set()` non-zero exit or timeout** → `DeviceUnavailable("device: ...")` →
  same `error`/auto-resume path the iOS adapter uses.
- **Mixed-device web request with no selection** → backend already returns 400;
  the new picker prevents it by always sending a device.
- **Root unavailable at runtime** (lost after preflight) → surfaced as a
  `device:`-prefixed error in status, mirroring the iOS tunneld message style.

---

## Residual Risk

Apps reading **Google Play Services fused** location may ignore the `gps` test
provider on some devices/Android builds. Root mitigates but does not guarantee
this. It is validated only by the final on-device step (control a real target app
on the actual phone). If it fails, the deferred fallback (appops mock-app + a
pushed `app_process` server) implements the same `LocationInjector` interface and
drops in behind `AndroidLocationClient` without touching steps for the protocol,
registry, factory, controller, or frontend.

---

## Testing

**Backend (pytest), `adb` stubbed at the `_adb` / subprocess seam:**
- `AndroidLocationClient`: `open` issues add+enable; `set` formats
  `--location <lat>,<lon>`; `clear` removes the provider; non-zero exit and
  timeout raise `DeviceUnavailable`; `reachable()` maps `get-state` output.
- `device/android.py` discovery: parses `adb devices`, reads model name, skips
  offline/unauthorized; `android_sdk_int` parses the prop.
- `DeviceRegistry`: `register(..., device_type=...)` and `type_for` default to
  `"ios"`; existing name/client/udid tests still pass.
- `SessionController._auto_resume` polls `device.reachable()` (inject a fake
  injector); iOS path still resolves via the same hook.
- `_resolve`/routing: existing tests unchanged; add one asserting `/api/devices`
  includes `type` for a mixed registry.
- `main.py` factory dispatch: a serial in `--android` yields an
  `AndroidLocationClient`; a udid yields a `LocationClient`.

**Frontend:** manual — with one iPhone + one Android registered, the dropdown
lists both with type labels, selecting each routes Walk/Stop to the right phone,
and the WS reflects the selected device.

**End-to-end (manual, on the real rooted phone):** add provider → Walk → confirm
the phone's location moves along the route in a maps app → Stop (freeze) → Reset
(real GPS returns). This is where the fused-location risk is settled.

---

## Implementation Notes / Compatibility

- Keys stay opaque strings end-to-end; iOS UDIDs and Android serials never
  collide and need no namespacing.
- `device.location.DeviceUnavailable` import path is preserved via re-export so
  no existing imports break.
- The protocol extraction is a pure refactor — iOS behavior and all current iOS
  tests must remain green as the first task.
- `tick_hz` is `1.0`; one `adb shell` per tick (~50–150 ms) is comfortably within
  budget. A persistent `adb shell` pipe is a future optimization only if
  `tick_hz` is raised, and fits behind the same adapter.
