# iOS Controller App + Remote Spoofing Design

**Date:** 2026-05-18
**Status:** Draft — awaiting user review
**Author:** Claude (brainstorming session with jacklee226)

## Summary

Two prioritized goals were evaluated:

1. **(Original priority 1, rejected) Plan A — iOS-only, no Mac.** Eliminate the Mac entirely; have an iOS app inject GPS into another iPhone with no desktop host.
2. **(Original priority 2, accepted as Track 1) Plan B — Remote spoofed iPhone, Mac stays home.** Mac+tunneld remains a "home base station" controller; the spoofed iPhone roams (cellular / foreign Wi-Fi); user drives via a native iOS app from anywhere.

After feasibility analysis (see "Feasibility — Plan A" below), Plan A is rejected and the work splits into two sequential tracks:

- **Track 2 — Native iOS controller app** over the existing Mac backend (current LAN/USB topology unchanged). Ships first.
- **Track 1 — Plan B remote-spoofing capability** via Tailscale, gated by an R&D spike. Ships after Track 2 only if validation passes.

If Track 1's validation spike fails, work stops there — no fallback to a "Mac and spoofed iPhone stay together" compromise. Track 2 alone is the floor deliverable.

## Feasibility — Plan A (rejected)

Even with sideloading allowed (paid Apple Developer Program, free-account sideload via Xcode, or AltStore-class distribution), Plan A has two architectural blockers that cannot be circumvented without jailbreak:

1. **Self-spoofing is impossible.** An iOS app cannot override `CLLocation` for other apps on the same device. The sandbox enforces this at the kernel level; no third-party entitlement bypasses it.
2. **iOS-as-tunneld-host is uncertain at best for iOS 17+ targets.** The cross-device case (iPhone-A spoofs iPhone-B) requires reimplementing pymobiledevice3's host side in Swift. The load-bearing unknown is the iOS 17+ RemoteXPC tunnel, which on macOS uses a kernel `utun` interface. iOS's only kernel-tunnel primitive (`NEPacketTunnelProvider`) is designed for VPN-client patterns and may not support the IPv6 link-local peer-endpoint shape RemoteXPC expects. There is no known public-API solution as of this writing.

A serious attempt would be 3–6 months of dedicated R&D with no guarantee the iOS 17+ tunnel piece works, plus permanent fragility against any iOS update (DVT is private SPI). The cost/risk profile is incompatible with the user's appetite, so Plan A is closed.

## Track 2 — Native iOS Controller App

### Goal

Replace the web UI with a native iOS app talking to the existing FastAPI backend over HTTP + WebSocket. Backend topology unchanged. Web UI kept in parallel as fallback (not deprecated).

### Architecture

```
┌──────────────────────────┐
│  controller-ios          │  (new, sideloaded, iOS 17+, SwiftUI + MapKit)
│   ├─ MapScreen           │
│   ├─ SearchBar           │
│   ├─ SessionControls     │
│   ├─ StatusSubscriber    │
│   └─ Settings            │
└────────────┬─────────────┘
             │ HTTPS + WSS
             ▼
┌──────────────────────────┐
│  trail_simulator/api/    │  (existing FastAPI, no changes in Phase 1)
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  pymobiledevice3 +       │
│  tunneld                 │
└────────────┬─────────────┘
             │ USB or LAN (unchanged)
             ▼
┌──────────────────────────┐
│  Spoofed iPhone(s)       │
└──────────────────────────┘
```

### Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Map provider | MapKit | Native UX, free, no OSM tile-server load |
| Geocoding | Backend `/geocode` (Nominatim) | Result parity with web UI; `MKLocalSearch` is a different dataset |
| iOS target | iOS 17+ | Matches current backend's iOS-17-tunneld assumptions |
| Web UI lifecycle | Keep indefinitely as fallback | Belt-and-braces; no deprecation timeline |
| Distribution | Sideload via Xcode | Same workflow as existing `companion-ios/StepCompanion` |
| Repo location | `controller-ios/` sibling to `companion-ios/` | Mirrors established pattern |

### Feature parity (web UI → iOS)

| Web UI feature | iOS port |
|---|---|
| Click two pins on map | Two-tap with crosshair confirmation |
| Address search | `/geocode` round-trip, drop pin |
| Speed slider (≤ 20 km/h) | UISlider with same cap; cap enforced server-side as today |
| Walk / Stop / Pause | Same button states, same WS-driven state machine |
| Live position marker | `MKPointAnnotation`, animated |
| Breadcrumb trail (green) | `MKPolyline` overlay, gated on active states (`starting`/`running`/`paused`) — same fix shipped to `app.js` on May 13 |
| Multi-device step companions status | List section in app |
| UI preview mode (`--dev-no-device`) | Transparent — same backend handles this |
| Cooldown warnings / 409 errors | Native `UIAlertController` |

### HTTP + WebSocket contract (locked in Phase 1.2)

The Swift client mirrors the existing JS client's contract one-for-one. The Phase 1.2 audit produces:

- An OpenAPI sketch or hand-written contract doc for the endpoints in use
- Swift `Codable` structs for `StatusSnapshot` and any request/response bodies
- A single `BackendClient` actor in Swift that owns the URLSession + WebSocket task lifecycle

### Out of scope for Track 2

- Authentication (Phase 3 only; same-LAN deployment continues to trust the network)
- App Store distribution (sideload only, matching `companion-ios`)
- Offline mode / route caching
- Apple Watch companion
- iPad-specific layouts (works on iPad in iPhone-app mode, but no separate iPad UX)

## Track 1 — Remote Spoofed iPhone (Plan B)

### Goal

Allow the spoofed iPhone to be physically remote from the Mac. Mac stays home as an always-on base station; user roams with the spoofed iPhone on cellular or foreign Wi-Fi.

### Architecture changes from Track 2

```
                              [Tailscale mesh]
controller-ios  ◄───WSS────►  Mac + tunneld  ◄──RemoteXPC over Tailscale──►  Spoofed iPhone
   (anywhere)                  (home, fixed)                                   (anywhere)
```

Three new pieces on top of Track 2:

1. **Tailscale on Mac and spoofed iPhone.** Provides stable IPv6/IPv4 mesh addresses between two devices that are not on the same LAN.
2. **Bonjour-bypass shim in `trail_simulator/device/`.** Existing tunneld discovery uses mDNS, which Tailscale doesn't forward (no multicast). The shim hands tunneld an explicit IPv6 peer address derived from a known UDID → Tailscale-IP mapping in config.
3. **Bearer-token auth on FastAPI.** Required as soon as the backend is reachable on a non-LAN interface.

### Critical validation (Phase 2 spike — gate for everything else)

All three must pass:

1. **Tunneld over Tailscale.** Can `pymobiledevice3 remote tunneld` establish a RemoteXPC session with an iOS 17+ device when the only network path is Tailscale (no LAN, no USB, no mDNS multicast)?
2. **DDI mount over the mesh.** Does `mobile_image_mounter` succeed?
3. **Latency budget.** Does DVT `LocationSimulation` round-trip stay under ~500 ms p99 (1 Hz tick rate gives plenty of headroom)?

**If any of the three fails: Track 1 is closed. No fallback. Document the failure and move on.**

### Known risks (not blockers if validation passes)

- Spoofed-iPhone Wi-Fi/cellular deep-sleep over Tailscale causes longer tunnel re-handshake gaps than the current LAN behavior (already documented in README).
- One Network Extension slot consumed on the spoofed iPhone by the Tailscale client.
- Authentication becomes mandatory, not optional.
- Tailscale Funnel exposes the FastAPI to public internet — token auth is the only thing between strangers and the iPhone's fake GPS.

### Out of scope for Track 1

- Multi-tenant deployment (single user, single Tailscale tailnet)
- WireGuard alternatives to Tailscale (Tailscale picked for zero-config NAT traversal; users can swap manually if desired, not officially supported)
- Cloud-hosted backend (Mac stays the controller)

## Phased delivery plan

### Phase 0 — Spec & alignment (this conversation)

- Confirm architecture (this document) ← gate
- Commit spec to git
- Invoke `writing-plans` skill to produce a detailed implementation plan
- User reviews implementation plan
- Dispatch subagents

### Phase 1 — iOS controller app (Track 2)

Dispatched as parallel subagents per the `dispatching-parallel-agents` pattern, with `Senior Developer` reviewing the `Mobile App Builder`'s work at sub-task boundaries.

1. Scaffold `controller-ios/` Xcode project (SwiftUI, iOS 17+ deployment target)
2. **API contract audit.** Map every endpoint the web UI uses; produce a contract doc and Swift `Codable` models for `StatusSnapshot`, route plan request/response, and any error envelopes
3. `BackendClient` actor — URLSession HTTP + URLSessionWebSocketTask WebSocket lifecycle
4. **MapScreen** — MapKit, two-tap origin/destination, crosshair confirmation
5. **SearchBar** — wired to `/geocode`, pin drop
6. **SessionControls** — Walk / Stop / Pause; wired to `/session/*`
7. **Live position marker + breadcrumb polyline** — active-state-gated to avoid the May-13 "green line connecting old route tail" regression
8. **StepCompanion status panel** — list view of `step_companions` array from `StatusSnapshot`
9. **Settings screen** — backend URL, dev-preview toggle, optional auth token (reserved for Phase 3, hidden by default)
10. **Sideload + verify** on a physical iPhone against the live backend, exercising the golden path and the edge cases (cooldown 409, multi-device, dev-no-device mode)
11. **`controller-ios/README.md`** — sideload + verification protocol mirroring `companion-ios/README.md`

Sub-tasks that can run in parallel: 4, 5, 6, 7, 8 (after 1–3 establish the foundation).

### Phase 2 — Remote-spoofing R&D spike (Track 1)

Single focused agent. Output is a results document at `docs/superpowers/specs/2026-05-18-remote-spoofing-spike-results.md`.

1. Bench setup: install Tailscale on Mac and a test iPhone; disconnect iPhone from the Mac's LAN; verify Tailscale-only connectivity
2. Validation test 1: tunneld over Tailscale
3. Validation test 2: DDI mount over the mesh
4. Validation test 3: latency profile
5. Write findings; decide go/no-go

**Hard gate. All three must pass to proceed to Phase 3.**

### Phase 3 — Remote operation hardening (Track 1, conditional on Phase 2 passing)

1. Bonjour-bypass / explicit-IP target in `trail_simulator/device/`
2. Bearer-token auth middleware on FastAPI; auto-required when bound to non-LAN interface
3. Reconnect/backoff tuning for tunneld-over-Tailscale; metrics on gap duration
4. iOS app: "Remote Mode" toggle in Settings; token stored in Keychain
5. README: new "Remote operation" section documenting Tailscale setup

## Subagent dispatch plan

Track 2 (Phase 1) uses `dispatching-parallel-agents`. Concretely:

- **`Mobile App Builder`** — primary author for sub-tasks 1, 3–9
- **`Senior Developer`** — reviews each Mobile App Builder deliverable at a sub-task boundary before the next dependent sub-task begins; flags scope creep, bad patterns, missed parity items
- **`Explore` / `general-purpose`** — sub-task 2 (API contract audit), read-only; output feeds 3 onward
- **`Technical Writer`** — sub-task 11 (`controller-ios/README.md`)

Phase 2 (Track 1 spike) uses a single agent — likely `Backend Architect` or `general-purpose` — because the work is investigation, not parallel construction.

## Repository layout after Phase 1

```
trail-simulator/
├── trail_simulator/       # backend (Python, unchanged)
├── frontend/              # web UI (unchanged, kept in parallel)
├── companion-ios/         # StepCompanion (unchanged)
├── controller-ios/        # NEW — native iOS controller app
└── docs/
    └── superpowers/
        └── specs/
            ├── 2026-05-18-ios-controller-and-remote-spoofing-design.md  (this file)
            └── 2026-05-18-remote-spoofing-spike-results.md              (Phase 2 output)
```

## Open questions to resolve during implementation

- Exact endpoint names and shapes — locked during the Phase 1.2 audit, not assumed now
- Whether the breadcrumb polyline should be rendered as a single `MKPolyline` (re-created each tick) or an incremental `MKMultiPolyline` (more efficient for long routes) — defer to whichever profiles better on-device
- Whether `MKMapView` or the SwiftUI `Map` view is the right MapKit entry point in iOS 17 (the SwiftUI `Map` regained feature parity in iOS 17; default to it and fall back to `MKMapView` only if a needed capability is missing)

## Success criteria

**Track 2 / Phase 1 is done when:**
- Sideloaded iOS app runs on a physical iPhone
- Every feature in the parity matrix above works against a live backend
- A user can complete a full route session (search → plan → walk → stop) without touching the web UI
- Web UI continues to work unchanged
- `controller-ios/README.md` documents sideload + verification

**Track 1 / Phase 3 is done when:**
- Spoofed iPhone is reachable from a roaming user's device with the Mac at home
- A full session completes over Tailscale with the spoofed iPhone on cellular
- Authentication is enforced when backend is bound to a non-LAN interface
- `README.md` "Remote operation" section explains the setup
