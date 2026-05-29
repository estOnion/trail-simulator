# Phase 1 — On-Device Verification (Task 12)

Manual end-to-end verification of the TrailController iOS app against the trail-simulator backend.
Fill in **Result** (✅ / ❌) and **Notes** as you go.

- **Tester:**
- **Date:**
- **App build / commit:**
- **Backend version:** trail-simulator 0.1.0
- **Device & iOS version:**
- **Test environment:** [ ] iOS Simulator (UI/wiring only)  [ ] Physical iPhone (full GPS spoof)

> The **Simulator** validates UI + backend wiring but does **not** spoof a real device's GPS.
> Real GPS-spoofing behavior must be confirmed on a **physical iPhone** (the spoof target),
> with the Mac running `tunneld` and the device reachable (LAN or Tailscale).

---

## 0. Setup

| # | Step | Result | Notes |
|---|------|--------|-------|
| 0.1 | Backend started: `uv run trail-simulator --host 0.0.0.0 --port 8787` | | |
| 0.2 | App launches without crash; state pill shows `idle` | | |
| 0.3 | (Device only) Settings → enter Mac LAN IP → **Test connection** → `OK — state: idle` → **Save** | | |
| 0.4 | (Device only) Granted Location + Local Network permission prompts | | |

## 1. Golden path

| # | Step | Expected | Result | Notes |
|---|------|----------|--------|-------|
| 1.1 | Tap map once | Green **Start** pin drops | | |
| 1.2 | Tap map again | Red **End** pin drops; crosshair overlay clears | | |
| 1.3 | Drag **Speed** slider | Value updates (0.5–20 km/h) | | |
| 1.4 | Tap **Walk** | Session starts; pill → `starting`/`running` | | |
| 1.5 | Watch route | Blue dot moves; green breadcrumb traces path | | |
| 1.6 | Tap **Pause** while running | Pill → `paused`; dot stops; breadcrumb frozen | | |
| 1.7 | Tap **Resume** while paused | Pill → `running`; movement resumes | | |
| 1.8 | Tap **Stop** | Pill → `idle`/`stopping`; movement halts | | |

## 2. Search

| # | Step | Expected | Result | Notes |
|---|------|----------|--------|-------|
| 2.1 | Type an address/place in search bar, run search | Results list appears | | |
| 2.2 | Tap a result | Next pin drops at that location | | |

## 3. Edge cases

| # | Step | Expected | Result | Notes |
|---|------|----------|--------|-------|
| 3.1 | Trigger a cooldown-gated move (Walk again immediately after Stop) | Cooldown alert with reason, jump distance, required wait | | |
| 3.2 | Dismiss / **Skip cooldown** in alert | Behaves as labeled | | |
| 3.3 | Tap **Reset pins** | Both pins + breadcrumb cleared | | |
| 3.4 | Background the app, then foreground | WS reconnects; pill returns to live state | | |
| 3.5 | Stop the backend mid-session | App surfaces transport/connection error gracefully | | |

## 4. Step companions (optional)

| # | Step | Expected | Result | Notes |
|---|------|----------|--------|-------|
| 4.1 | Connect a companion-ios device | Panel lists it (label, UDID, total acked) | | |
| 4.2 | No companions connected | Panel shows "No step companions connected." | | |

---

## Summary

- **Overall:** [ ] PASS  [ ] FAIL
- **Blocking issues found:**
- **Non-blocking issues found:**

## Phase 1.5 — HealthKit merge verification

- [ ] Fresh install → app prompts for HealthKit auth on first launch (HealthTabView "Request" button if denied initially).
- [ ] Toggle "Write steps to HealthKit" → row shows "Writes enabled".
- [ ] Start a session from the Map tab → step counter on Health tab increments live.
- [ ] Open iOS Health app → Steps source list shows TrailController writing samples.
- [ ] Background the app (home gesture) → after 2 minutes, return to app; counters should still be increasing (BackgroundAudioKeeper).
- [ ] Lock the phone → step events keep flowing (verify in Health app source data).
- [ ] Change backend URL in Settings → /ws/live and /ws/steps both reconnect; counters continue.
- [ ] Toggle off → /ws/steps disconnects, session counters reset to 0, cumulative persists.
