# Backend HTTP + WebSocket Contract

## API Contract (audited from backend on 2026-05-18)

All REST under `/api`; WebSocket at root. Base URL is `http://<host>:<port>` (default `http://127.0.0.1:8787`; LAN deployments use Mac's IP).

| Method | Path | Request | Success | Failure |
|---|---|---|---|---|
| GET | `/api/status` | — | `StatusSnapshot` (200) | — |
| POST | `/api/session` | `{start_lat, start_lon, destinations:[{lat,lon}], speed_kmh, loop?:bool, skip_cooldown?:bool}` | `{ok:true, reason:string}` (200) | 409 `{detail:string}` (already running) · 429 `{detail:{cooldown:true, required_wait_s, jump_km, reason}}` |
| POST | `/api/retarget` | `{destinations:[{lat,lon}], loop?:bool|null}` | `{ok:true}` | 409 · 502 `{detail:string}` |
| POST | `/api/speed` | `{speed_kmh}` (0 < x ≤ 20) | `{ok:true}` | 502 |
| POST | `/api/pause` | — | `{ok:true}` | — |
| POST | `/api/resume` | — | `{ok:true}` | — |
| POST | `/api/stop` | — | `{ok:true}` | — |
| GET | `/api/search?q=&limit=` (limit clamped 1..20) | — | `{results:[{display_name, lat, lon, type}]}` | 502 |

WebSocket `/ws/live`:
- Server pushes `StatusSnapshot` JSON on every state change; sends initial snapshot on accept.
- Max 64-deep server queue per client; oldest dropped on overflow. Client should expect latest-wins.

`StatusSnapshot` JSON shape:
```json
{
  "state": "idle|starting|running|paused|stopping|reconnecting|error",
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
  ]
}
```

Source: trail_simulator/api/rest.py, ws.py, geocode.py — audited 2026-05-18.
