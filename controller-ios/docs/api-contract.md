# Backend HTTP + WebSocket Contract

All REST lives under `/api`, WebSockets at the root. Base URL is
`http://<host>:<port>`. On a physical iPhone use the Mac's LAN IP and **port
8080** — the app's baked-in `http://127.0.0.1:8787` only works in the Simulator,
and 8787 collides with the phone's own RSD tunnel.

## Addressing a session

The backend runs one session per device, so most endpoints need to know which
one you mean. Resolution order:

1. `X-Client-Id` header (or `?client=` on WebSockets) — the UUID from Settings →
   Identity. Preferred. Auto-binds when only one device is connected.
2. `X-Device-Name` header (or `?device=`) — the iPhone's name. Fallback for the
   web frontend.
3. Neither: allowed only when a single device is registered.

Failures are `404` when the name or UUID isn't registered, and `409` with
`Multiple devices registered; send X-Device-Name header.` when the request is
ambiguous.

## Error bodies

Every failed REST request under `/api/`, whatever its status, answers JSON
`{detail, incident}`. `detail` is a string, except the cooldown `429` (an object)
and request-validation `422` (a list). `incident` is `{id, code, remedy}` for the
incident the backend recorded for that answer (`remedy` is null for code
`unexpected`), or null if recording failed or the path is an incident endpoint.
An unmapped failure answers `500` with `detail` "unexpected server error:
<type>: <message>" and an `unexpected` incident. A `/ws/live` refusal still
gives its cause only in the close reason, but it is recorded and visible at
`/observatory`.

## Session control

| Method | Path | Request | Success | Failure |
|---|---|---|---|---|
| GET | `/api/status` | — | `StatusSnapshot` | — |
| POST | `/api/session` | `{start_lat, start_lon, destinations:[{lat,lon}], speed_kmh, loop?, skip_cooldown?}` | `{ok:true, reason}` | 409 already running · 429 `{detail:{cooldown:true, required_wait_s, jump_km, reason}}` |
| POST | `/api/retarget` | `{destinations:[{lat,lon}], loop?}` | `{ok:true}` | 409 · 502 |
| POST | `/api/speed` | `{speed_kmh}` (0 < x ≤ 20) | `{ok:true}` | 502 |
| POST | `/api/pause` | — | `{ok:true}` | — |
| POST | `/api/resume` | — | `{ok:true}` | — |
| POST | `/api/stop` | — | `{ok:true}` | — |
| POST | `/api/reset` | — | `{ok:true}` | 409 |
| GET | `/api/search?q=&limit=` | limit clamped 1..20 | `{results:[{display_name, lat, lon, type}]}` | 502 |

`/api/reset` releases the device back to real GPS and clears the stored last fix,
so the next start isn't measured against a stale spoof position.

## Devices, identity, following

| Method | Path | Request | Success | Failure |
|---|---|---|---|---|
| GET | `/api/devices` | — | `{devices:[{udid, name, bound_client_id, type}]}` | — |
| GET | `/api/clients` | — | `{clients:[{client_id, name, state}]}` | — |
| POST | `/api/bind` | `{client_id, udid}` | `{ok:true}` | 404 unknown udid · 409 UUID taken / device already bound |
| POST | `/api/rebind` | `{client_id, udid}` | `{ok:true}` | 404 |
| POST | `/api/follow` | `{follower_client_id, leader_client_id}` | `{ok:true}` | 404 unknown client · 400 self-follow |
| POST | `/api/unfollow` | `{client_id}` | `{ok:true}` | 404 |

`type` is `ios` or `android`. `/api/rebind` force-reassigns a device, evicting
the previous binding — it's an operator escape hatch, not something the phone
app calls.

## Incidents

| Method | Path | Request | Success | Failure |
|---|---|---|---|---|
| POST | `/api/incidents` | `{sent_at, reports:[{report_id, code, message, started_at, ended_at, attempts, app_build, os_version}]}` (ISO 8601 with offset, `report_id` a UUID, at most 200) | `{accepted:[{report_id, id}], duplicates:[report_id]}` | 422 malformed, over 200, or a code that is not a client-failure code |
| GET | `/api/incidents` | filters `kind`, `code` (comma-separated, `device.*` matches a prefix), `client`, `device`, `session`, `since`, `until`, `q`, `limit` (default 100, max 500), `before` | `{incidents:[{id, kind, code, remedy, source, message, first_seen, last_seen, count, client_id, device_name, session_id}], next_before}` | 422 |
| GET | `/api/incidents/{id}` | — | the full record; client failures add `host_during_outage` (`up`, `down`, `partly`) | 404 |
| GET | `/api/incidents/summary` | the list filters except `limit`/`before` | `{codes:[{code, remedy, incidents, occurrences, last_seen}]}` | 422 |
| GET | `/api/incident-codes` | — | `{codes:[{code, kinds, remedy}]}` | — |

Client failure codes: `client.unreachable`, `client.live_dropped`,
`client.timeout`, `client.undecodable`. Reports are idempotent by `report_id`, compared as a UUID value, so letter case never makes a stored report look new; each ID is echoed in `accepted` and `duplicates` exactly as the client sent it;
the backend corrects the report's times for the difference between `sent_at` and
its own clock. The reporting endpoint takes `X-Client-Id` when sent but never
refuses a report for lack of a device. The other incident endpoints ignore the
addressing headers. The human-readable view is at `/observatory`.

## WebSockets

`/ws/live?client=<uuid>` (or `?device=<name>`) pushes a `StatusSnapshot` on
every state change, plus one immediately on accept. The server queue is 64 deep
per client and drops oldest on overflow, so treat it as latest-wins. An
unresolvable client closes with 1008.

`/ws/steps` carries step deltas to a companion writer. The client opens with
`{"type":"hello", "client_id":..., "device_label":..., "udid":...}`; without it
within the hello timeout the connection still registers under a generated label.

## StatusSnapshot

```json
{
  "state": "idle|starting|running|paused|stopping|reconnecting|error|following",
  "session_id": 0|null,
  "current_lat": 0.0|null,
  "current_lon": 0.0|null,
  "target_lat": 0.0|null,
  "target_lon": 0.0|null,
  "speed_kmh": 0.0,
  "progress_m": 0.0,
  "total_m": 0.0,
  "last_error": "..."|null,
  "last_incident": {"id":0,"code":"...","remedy":"..."|null}|null,
  "cooldown_remaining_s": 0.0,
  "steps_sent": 0,
  "step_companions": [
    {"label":"...","udid":"..."|null,"connected_at_iso":"...","last_heartbeat_iso":"...","total_acked":0}
  ],
  "following_leader": "..."|null
}
```

`last_incident` references the incident behind `last_error` (null when
`last_error` is null or the incident could not be recorded). The Controller app
reads it (`id` integer, `code`, and `remedy`, which may be null) to show the
remedy in the state pill's error alert and to offer "Try again" for
`route.service_down`. A missing or null `last_incident` is treated as none, so
the app still works against a backend that predates the observatory.

`cooldown_remaining_s` counts down against wall-clock while a start is blocked,
and reads 0 once it expires or a start overrides it.

Source: `trail_simulator/api/rest.py`, `ws.py`, `ws_steps.py`, `geocode.py`, `observatory/router.py`.
