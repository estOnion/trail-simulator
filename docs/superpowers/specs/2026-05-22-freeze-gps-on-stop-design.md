# Freeze GPS at last spoofed location on stop/finish

**Date:** 2026-05-22
**Status:** Approved

## Problem

When a simulation ends — the user clicks Stop, or the route reaches its last
destination — the trail-simulator currently releases the phone back to **real
GPS**. The desired behavior: keep the phone **frozen at the last spoofed
location** and continue reporting it, until a new trail begins. The user must
also have an explicit way to return to real GPS when they want it.

## Root cause / logic review

`SessionController._run`'s `finally` block always calls `device.clear()`
(`trail_simulator/session/controller.py:487`). `LocationClient.clear()`
(`trail_simulator/device/location.py:75`) bundles **two distinct jobs**:

1. `loc.clear()` — tells iOS DtSimulateLocation to **stop simulating**, so the
   phone reverts to **real GPS**.
2. `__aexit__` on the DVT / LocationSimulation contexts — **tears down the
   session**.

Key fact about the iOS service: the simulated location persists **only while the
DVT session stays open**. Closing the session reverts the phone to real GPS.
There is no need for a re-send loop — `set()` is sticky and the phone passively
holds the last point as long as the session is open.

Therefore "keep GPS at the last spoofed location" = **keep the DVT session open
and do not call `loc.clear()`** on a normal stop/finish.

## Design

Split the two responsibilities currently bundled in `clear()` into two
observable behaviors:

- **Freeze** — stop ticking, but keep the DVT session open holding the last
  `set()` point. Triggered by user Stop and by reaching the last destination.
- **Release** — full `device.clear()` (revert to real GPS + tear down session).
  Triggered by an explicit Reset action and by server shutdown.

### Backend changes

1. **`_run` finally (`session/controller.py`)** — call `device.clear()` **only
   when `self._state == SessionState.error`**. On a normal stop / last-destination
   completion (state settles to `idle`), skip the clear → **freeze**: the DVT
   session stays open holding the last fix.

2. **`LocationClient.open()` idempotency (`device/location.py`)** — guard so that
   the *next* trail's `open()` is a no-op when the session is already connected
   (`self._loc is not None`). Without this, a second `start()` builds a fresh DVT
   session and leaks/overwrites the held one. `MultiLocationClient` inherits this
   automatically because each inner `LocationClient` self-guards.

3. **New `controller.reset_device()` + `POST /api/reset`** — under
   `_lifecycle_lock`, allowed only when state is `idle` or `error`; calls
   `device.clear()`, sets `_current = None` and `_current_leg_target = None`,
   broadcasts. Raises `RuntimeError` (→ HTTP 409) if a session is active — the
   UI must stop first. `last_fix` is intentionally left untouched (matches
   today's behavior; the app never knew the real GPS position).

4. **Shutdown (`main.py` lifespan)** — after `controller.stop()`, also call
   `controller.reset_device()` so quitting the server returns the phone to real
   GPS. This preserves today's net shutdown behavior.

### Web frontend (`frontend/static`)

- Add a **"Reset to real GPS"** button, enabled only when `state == idle` and a
  spoofed position is currently held (status `current_lat`/`current_lon`
  present). On click: `POST /api/reset`, then re-sync from `/api/status`.

### iOS controller (`controller-ios/ControllerApp`)

- `BackendClient.reset()` → `POST /api/reset` (mirrors existing `stop()`).
- `SessionStore.reset()` → calls client, clears breadcrumb/pin state.
- `SessionControls` — **Reset** button shown when idle/frozen.

## Edge cases reviewed

- **Cooldown on next trail** — still computed from the held `last_fix`;
  unchanged. After a Reset, `last_fix` is stale vs. real GPS, but the app never
  knew real GPS — pre-existing limitation, not a regression.
- **Device-error / auto-resume** — the error path still clears + tears down, so
  reconnect/auto-resume works as before.
- **Multi-device mirror** — idempotent `open()` per inner client; freeze applies
  to all devices.
- **`--dev-no-device` stub** — `clear()` is a harmless no-op log; freeze simply
  means it is not called.

## Testing

Using a fake recording device (records `open`/`set`/`clear` calls):

- After user `stop()` → `clear()` **not** called; state `idle`; session still
  open (a subsequent `start()` does **not** call `open()` again).
- After reaching the last destination → same: no `clear()`, frozen.
- Error path (device/route error) → `clear()` **is** called.
- `reset_device()` when idle → calls `clear()`, nulls `_current`; when active →
  raises (409).
- Existing test suite continues to pass.
