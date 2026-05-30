# Dynamic device registration + per-device isolation

Date: 2026-05-30

## Problem

Two iPhones running TrailCompanion against one backend can clobber each
other: stopping a route on one phone overrides the route status of the
other. Root cause: the backend launched with no `--udid` registers exactly
one device, so both clients bind to that single UDID and share one
`SessionController`. `registry.bind()` silently evicts the prior client,
hiding the collision.

Goals:
1. Stop requiring a launch-time `--udid` decision. Discover connected
   devices dynamically and let any phone connect (target: 10+ devices).
2. Associate each phone's user-editable UUID with the correct backend UDID
   at connection time.
3. Fix the two latent defects that let the bug pass silently:
   - `bind()` silently steals an already-bound UDID.
   - Step events broadcast globally to all step companions.

## Hard constraint

An iOS app cannot read its own UDID (Apple removed the API). GPS spoofing
requires the Mac to reach each phone over USB/tunneld by UDID — the phone
never knows its own UDID. So the UDID always comes from the backend's
discovery of physically-connected devices; the phone only *claims* which
discovered device is "me".

## Design

### 1. Dynamic device discovery
- `device/discovery.py`: `discover_connected()` enumerates iOS devices via
  `pymobiledevice3.usbmux.list_devices()` + lockdown `DeviceName`, and
  Android via the existing `list_android_devices()`. Returns
  `[(udid, name, type)]`.
- `DeviceRegistry.sync(discovered)`: reconciles the live set — add new
  devices, preserve existing UUID↔UDID bindings for devices still present,
  drop devices (and their stale binding) that disconnected.
- `/api/devices` runs discovery on-demand before returning the list, so a
  phone plugged in after launch appears as soon as the app refreshes.

### 2. Startup (main.py)
- Default mode (no `--udid`): require tunneld reachable, run one initial
  discovery (zero devices allowed — never fail on "no device"), register
  whatever is connected.
- `--udid` becomes an optional allow-list *filter*, not the only way to
  register. `--mirror`, `--android`, `--dev-no-device` unchanged.

### 3. Phone → device association
- Existing `SettingsScreen` device picker + `/api/bind`, now fed the live
  device list. User taps their iPhone once; app binds its UUID↔UDID.

### 4. Fix #1 — bind() rejects collisions
- `registry.bind()` raises `DeviceAlreadyBoundError` (HTTP 409) when a
  *different* client tries to claim a UDID already bound to another client.
  Same-client re-bind to the same UDID stays idempotent (handles
  reconnects; the app persists its UUID in UserDefaults).
- No forced takeover: a phone that wipes its UUID waits for the old binding
  to age out on disconnect (via `sync()`).

### 5. Fix #2 — per-device step scoping
- `StepClient.swift` hello sends `client_id` (BackendConfig.clientId)
  instead of empty `udid`.
- `ws_steps.py` resolves `client_id → udid` via the registry at hello and
  stores it on the `StepClient`. `StepFanout.send(payload, udid)` delivers
  only to companions whose UDID matches.
- `SessionController` learns its own `udid` (passed by `SessionManager`);
  `_emit_steps` sends with its UDID. `StatusSnapshot.step_companions` is
  filtered to this device's companions.

## Testing
- Registry: `sync()` reconciliation; `bind()` collision rejection +
  idempotent same-client re-bind.
- Discovery: mock usbmux/adb; assert list shape and type tagging.
- `/api/devices`: triggers discovery and returns the fresh list.
- Step scoping: fanout delivers only to matching-UDID companions; controller
  emits with its UDID; status snapshot filtered.
- iOS: `StepClient` hello includes `client_id`; existing header/URL tests
  stay green.

## Out of scope
- Forced bind takeover / device hand-off UX.
- `--mirror` redesign (kept as legacy single-session fan-out).
