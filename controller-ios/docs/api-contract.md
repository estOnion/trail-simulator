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
  "cooldown_remaining_s": 0.0,
  "steps_sent": 0,
  "step_companions": [
    {"label":"...","udid":"..."|null,"connected_at_iso":"...","last_heartbeat_iso":"...","total_acked":0}
  ],
  "following_leader": "..."|null
}
```

`cooldown_remaining_s` counts down against wall-clock while a start is blocked,
and reads 0 once it expires or a start overrides it.

Source: `trail_simulator/api/rest.py`, `ws.py`, `ws_steps.py`, `geocode.py`.
