# UUID Identity & Follow-a-Leader — Design

**Date:** 2026-05-29
**Branch:** feature/merge-ios-apps
**Status:** Approved for planning

## Problem

Two iPhones running TrailController against the same backend cannot run
independent routes in parallel. When the second phone starts a route it
clobbers the first. Root cause: routing identity is `UIDevice.current.name`,
which iOS 16+ reports as a generic `"iPhone"` for every device, so both apps
send the same `X-Device-Name` and resolve to the same backend session.

## Goals

1. **Bug fix — parallel sessions:** each iPhone runs its own backend session;
   starting a route on one phone never affects another.
2. **Feature 1 — UUID identity:** each iPhone carries a user-controllable
   identifier ("UUID") that the backend uses to identify it. Duplicates are
   rejected at registration time.
3. **Feature 2 — follow a leader:** an iPhone can follow another iPhone's route
   by that leader's UUID, choosing per-follow between watching on the map only
   or mirroring the leader's GPS onto its own phone.

## Non-Goals

- Persisting bindings across backend restarts (registry stays in-memory, as
  today; the app re-establishes its binding on reconnect).
- Authentication / access control on who may follow whom.
- Web frontend changes (it keeps working via the DeviceName fallback path).

---

## Architecture Overview

Physical model is unchanged: the backend runs on a Mac and injects GPS into
USB-tethered iPhones, one `SessionController` per **UDID** (`SessionManager`).
The iOS app is a remote control + viewer that talks to the backend over the
LAN.

**Identity model:** a client **UUID** (string) is the primary routing identity.
The `DeviceRegistry` maps `client_id → udid` (a binding) in addition to the
existing `name → udid` map. `SessionManager` stays keyed by **UDID** — one
physical phone has one GPS and therefore one session.

Routing precedence on every request:

1. `X-Client-Id` header (REST) / `?client=` query (WS) → binding → UDID
2. else `X-Device-Name` header / `?device=` query → name → UDID  *(compat / web)*
3. else `registry.default_udid()` (only resolves when exactly one device)

---

## Component Design

### Backend

#### `DeviceRegistry` (extended)

Add a client-id binding map next to the existing name map.

- `bind(client_id: str, udid: str) -> None`
  - If `client_id` is already bound to a **different** udid → raise
    `DuplicateClientIdError` (mapped to HTTP 409). Re-binding the same
    `client_id` to the same udid is idempotent and allowed.
  - A udid may be re-bound to a new client_id (user changed their UUID); the
    old client_id is released.
- `resolve_client(client_id: str) -> str | None` — client_id → udid.
- `client_for(udid: str) -> str | None` — reverse lookup, for `/api/devices`.
- `auto_bind_single(client_id: str) -> str | None` — if exactly one device is
  registered and it has no binding (or is bound to this client_id), bind it and
  return the udid; otherwise return `None`.
- `list_clients() -> list[tuple[client_id, udid, name]]` — for `/api/clients`.

#### REST (`trail_simulator/api/rest.py`)

- `_resolve(...)` updated to accept `x_client_id` / `client` and apply the
  precedence above. When an unbound client_id arrives:
  - exactly one device → `auto_bind_single`, proceed.
  - 2+ devices → `400` "Unbound client; POST /api/bind to choose a device."
- `GET /api/devices` → add `bound_client_id` to each entry:
  `{"udid", "name", "bound_client_id"}`.
- `POST /api/bind` body `{client_id, udid}` → `registry.bind(...)`.
  - `200 {"ok": true}` on success.
  - `409 {"detail": "..."}` on duplicate client_id (different udid).
  - `404` if udid not connected.
- `GET /api/clients` → `{"clients": [{"client_id", "name", "state"}]}` for the
  follow picker. `state` comes from each bound udid's controller status.
- `POST /api/follow` body `{follower_client_id, leader_client_id}`:
  - Resolve both to controllers. `400` if equal, or if leader unknown.
  - `follower_controller.follow(leader_controller)`.
- `POST /api/unfollow` body `{follower_client_id}` →
  `follower_controller.unfollow()`.

#### `SessionController` (extended for follow)

- `follow(leader: SessionController) -> None`
  - Stop the follower's own route engine (no OSRM ticking).
  - Register a listener on `leader` that forwards each snapshot's position to
    the follower's own device: `await self._device.set(lat, lon)`.
  - Set follower status state to `following` (new `SessionState`), recording the
    leader's client_id/name for display.
- `unfollow() -> None` — remove the leader listener, return to `idle`.
- Guard: a controller cannot follow itself.

`SessionManager` is unchanged except it is still the lookup used by the new REST
endpoints.

### iOS

#### `BackendConfig`

- Replace/augment `deviceName` handling with a `clientId: String`.
- **Default `clientId` = `UIDevice.current.name`** when none is stored.
- If the user edits it, persist the custom value (`UserDefaults`), and use that
  thereafter instead of the device-name default.
- Keep `deviceName` for the fallback path / display.

#### `BackendClient`

- Send `X-Client-Id` header on every request (in addition to the existing
  `X-Device-Name` for compat).
- `bind(clientId:udid:)` → `POST /api/bind`; surfaces `409` as a typed
  "duplicate UUID" error.
- `fetchClients()` → `GET /api/clients`.
- `follow(leader:)` / `unfollow()` → the new endpoints.

#### `LiveStatusSubscriber`

- `start(baseURL:clientId:)` appends `?client=<uuid>`. A separate
  `start(baseURL:watching:)` variant (or a `client:` override) lets the Map
  view-only follow subscribe to a **leader's** stream.

#### Settings — "Identity" section

- UUID text field, pre-filled with the current `clientId` (device-name default
  or saved custom value), with a copy button.
- **Save validation:** on Save, call `bind(clientId:udid:)`. If it returns
  `409`, show an inline error ("That UUID is already used by another device —
  pick a different one") and **do not** apply the change. On success, persist
  and update the live `BackendClient`.
- Device picker shown only when `/api/devices` reports 2+ devices (auto-bind
  covers the single-device case).

#### Map — "Follow leader"

- Toolbar button → sheet:
  - List of active leaders from `/api/clients` (name + UUID), tap to select; a
    paste field for entering a UUID directly.
  - Toggle: **"Watch on map only"** vs **"Mirror onto this phone (GPS)."**
  - Confirm → view-only opens the leader's WS stream and renders it; GPS mode
    calls `POST /api/follow`.
  - While following: a "Stop following" affordance (calls `/api/unfollow` for
    GPS mode, or closes the leader stream for view-only).

---

## Data Flow

**Normal control (post-bind):**
`app → X-Client-Id → _resolve → binding → UDID → SessionController → GPS`

**Binding / rename:**
`Settings Save → POST /api/bind {client_id, udid} → registry.bind → 200/409`

**GPS-injected follow:**
`follower → POST /api/follow → follower.follow(leader) → leader snapshots →
follower._device.set() → follower phone GPS tracks leader`

**View-only follow:**
`follower app → WS /ws/live?client=<leaderUUID> → render on follower map`
(no backend session mutation)

---

## Error Handling

- `409` duplicate client_id on bind → app blocks Save, shows inline message.
- `400` unbound client_id with multiple devices → app prompts device pick.
- `404` follow leader unknown / `400` follow-self → app shows error, no state
  change.
- Backend registry is in-memory; on backend restart the app re-binds on next
  request (auto-bind if single device, else the saved binding is re-sent).

---

## Testing

**Backend (pytest):**
- `DeviceRegistry`: bind/resolve_client, duplicate raises, re-bind same udid,
  auto_bind_single, list_clients.
- REST: `_resolve` precedence (client_id > name > default); `POST /api/bind`
  200/409/404; `/api/devices` includes `bound_client_id`; `/api/clients`
  listing; `/api/follow` + `/api/unfollow` wiring; follow-self 400.
- `SessionController.follow/unfollow`: follower mirrors leader snapshots to its
  device; unfollow restores idle.
- Regression: existing `X-Device-Name` routing tests still pass (fallback path).

**iOS (XCTest):**
- `X-Client-Id` header present on requests.
- `BackendConfig` default = device name; custom value persists and wins.
- `LiveStatusSubscriber` builds `?client=` query correctly.

---

## Implementation Notes / Compatibility

- "Keep both": the `X-Device-Name` path and the uncommitted Settings name
  picker remain as a fallback. UUID is layered on top as the primary key.
- The default UUID equalling a generic `"iPhone"` for multiple phones is
  intentional — the duplicate-bind check forces the user to make it unique
  before a second phone can register, which is the explicit fix for the bug.
- `/ws/steps` (HealthKit step companion) is not scoped per session and is
  unchanged.
