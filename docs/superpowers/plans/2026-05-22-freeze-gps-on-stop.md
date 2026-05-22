# Freeze GPS at Last Spoofed Location on Stop/Finish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a simulation ends by user Stop or by reaching the last destination, keep the phone frozen at the last spoofed location (don't revert to real GPS) until a new trail begins; add an explicit "Reset to real GPS" control.

**Architecture:** Split the two jobs currently bundled in `LocationClient.clear()` (tell iOS to stop simulating + tear down the DVT session) into two observable behaviors. **Freeze** = stop ticking but keep the DVT session open holding the last `set()` point (iOS holds a simulated location only while the session stays open). **Release** = full `clear()`, triggered only by an explicit Reset and by server shutdown. The change is concentrated in `SessionController._run`'s `finally` block (clear only on error), plus a new `reset_device()` path and idempotent `open()`.

**Tech Stack:** Python 3 / FastAPI / pytest + pytest-asyncio (backend); vanilla JS + Leaflet (web); Swift / SwiftUI / XCTest (iOS).

**Spec:** `docs/superpowers/specs/2026-05-22-freeze-gps-on-stop-design.md`

**Test fixture used by several backend tasks** — a recording fake device (Tasks 2–4 each define it inline in their own test module; repeated intentionally so tasks can be implemented out of order):

```python
class FakeDevice:
    def __init__(self):
        self.open_count = 0
        self.set_calls = []
        self.clear_count = 0
    async def open(self):
        self.open_count += 1
    async def set(self, lat, lon):
        self.set_calls.append((lat, lon))
    async def clear(self):
        self.clear_count += 1
```

**Run all backend tests with:** `python -m pytest -q` (from repo root).

---

## Task 1: Make `LocationClient.open()` idempotent

Without this, the *next* trail's `_run` calls `open()` again and builds a fresh DVT session, leaking/overwriting the frozen one. Guard so a second `open()` is a no-op while connected.

**Files:**
- Modify: `trail_simulator/device/location.py` (`open`, lines 38-40)
- Test: `tests/test_location_client.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_location_client.py
from __future__ import annotations

import pytest

from trail_simulator.device.location import LocationClient


@pytest.mark.asyncio
async def test_open_is_noop_when_already_connected(monkeypatch):
    client = LocationClient()
    calls = {"n": 0}

    async def fake_connect():
        calls["n"] += 1
        client._loc = object()  # simulate an open session

    monkeypatch.setattr(client, "_connect", fake_connect)

    await client.open()          # first open -> connects
    await client.open()          # second open -> must be a no-op
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_open_connects_when_not_connected(monkeypatch):
    client = LocationClient()
    calls = {"n": 0}

    async def fake_connect():
        calls["n"] += 1
        client._loc = object()

    monkeypatch.setattr(client, "_connect", fake_connect)
    await client.open()
    assert calls["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_location_client.py -v`
Expected: `test_open_is_noop_when_already_connected` FAILS (`calls["n"] == 2`).

- [ ] **Step 3: Add the idempotency guard**

In `trail_simulator/device/location.py`, change `open()`:

```python
    async def open(self) -> None:
        async with self._lock:
            if self._loc is not None:
                return
            await self._connect()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_location_client.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/device/location.py tests/test_location_client.py
git commit -m "fix(device): make LocationClient.open() idempotent so a held session is reused"
```

---

## Task 2: Freeze on stop/finish — `_run` finally clears only on error

The core behavior change. On a normal stop or last-destination completion the state settles to `idle`; on a fault it is `error`. Clear the device only in the `error` case.

**Files:**
- Modify: `trail_simulator/session/controller.py` (`_run` finally, lines 485-498)
- Test: `tests/test_controller_freeze.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_controller_freeze.py
from __future__ import annotations

import asyncio

import pytest

import trail_simulator.session.controller as controller_mod
from trail_simulator.routing.osrm import RouteError
from trail_simulator.session.controller import SessionController, SessionState
from trail_simulator.session.store import Store


class FakeDevice:
    def __init__(self):
        self.open_count = 0
        self.set_calls = []
        self.clear_count = 0
    async def open(self):
        self.open_count += 1
    async def set(self, lat, lon):
        self.set_calls.append((lat, lon))
    async def clear(self):
        self.clear_count += 1


def _patch_route(monkeypatch, polyline):
    async def fake_route(a_lat, a_lon, b_lat, b_lon):
        return list(polyline)
    monkeypatch.setattr(controller_mod, "fetch_walking_route", fake_route)


@pytest.mark.asyncio
async def test_user_stop_does_not_clear_device(tmp_path, monkeypatch):
    # A long leg so the tick loop is still running when we stop.
    _patch_route(monkeypatch, [(0.0, 0.0), (0.0, 0.001)])
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await asyncio.sleep(0.05)        # let it teleport + enter the tick loop
    await c.stop()

    assert dev.clear_count == 0      # frozen — device NOT released
    assert c._state == SessionState.idle


@pytest.mark.asyncio
async def test_completion_does_not_clear_device(tmp_path, monkeypatch):
    # Degenerate route (start == dest) completes after one leg.
    _patch_route(monkeypatch, [(0.0, 0.0), (0.0, 0.0)])
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.0)], speed_kmh=4.0)
    await asyncio.wait_for(c._task, timeout=2.0)

    assert dev.clear_count == 0      # frozen at last destination
    assert c._state == SessionState.idle


@pytest.mark.asyncio
async def test_route_error_clears_device(tmp_path, monkeypatch):
    async def boom(a_lat, a_lon, b_lat, b_lon):
        raise RouteError("no route")
    monkeypatch.setattr(controller_mod, "fetch_walking_route", boom)
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await asyncio.wait_for(c._task, timeout=2.0)

    assert dev.clear_count == 1      # error path still releases
    assert c._state == SessionState.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_controller_freeze.py -v`
Expected: `test_user_stop_does_not_clear_device` and `test_completion_does_not_clear_device` FAIL (`clear_count == 1`); `test_route_error_clears_device` already PASSES.

- [ ] **Step 3: Change the finally block to clear only on error**

In `trail_simulator/session/controller.py` `_run`, replace the existing `finally` body's clear logic. The current block is:

```python
        finally:
            try:
                await self._device.clear()
            except Exception:
                pass
            # Ensure a clean state — covers CancelledError path where state wasn't set.
            if self._state not in (SessionState.idle, SessionState.error):
                self._state = SessionState.idle
            if self._session_id is not None:
                self._store.session_end(
                    self._session_id,
                    "completed" if self._state == SessionState.idle else self._state.value,
                )
            await self._broadcast()
```

Replace with (clear moved AFTER the state is settled, and gated on `error`):

```python
        finally:
            # Ensure a clean state — covers CancelledError path where state wasn't set.
            if self._state not in (SessionState.idle, SessionState.error):
                self._state = SessionState.idle
            # Freeze: on normal stop/completion (idle) keep the DVT session open
            # holding the last spoofed point. Only release the device on error.
            if self._state == SessionState.error:
                try:
                    await self._device.clear()
                except Exception:
                    pass
            if self._session_id is not None:
                self._store.session_end(
                    self._session_id,
                    "completed" if self._state == SessionState.idle else self._state.value,
                )
            await self._broadcast()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_controller_freeze.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/session/controller.py tests/test_controller_freeze.py
git commit -m "feat(session): freeze at last spoofed location on stop/finish (clear only on error)"
```

---

## Task 3: Add `reset_device()` + `POST /api/reset`

Explicit release back to real GPS. Allowed only when settled (`idle`/`error`); otherwise 409.

**Files:**
- Modify: `trail_simulator/session/controller.py` (new method after `stop`, ~line 280)
- Modify: `trail_simulator/api/rest.py` (new route after `/stop`, ~line 101)
- Test: `tests/test_reset.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reset.py
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trail_simulator.api.rest import build_router
from trail_simulator.session.controller import SessionController, SessionState
from trail_simulator.session.store import Store


class FakeDevice:
    def __init__(self):
        self.open_count = 0
        self.set_calls = []
        self.clear_count = 0
    async def open(self):
        self.open_count += 1
    async def set(self, lat, lon):
        self.set_calls.append((lat, lon))
    async def clear(self):
        self.clear_count += 1


@pytest.mark.asyncio
async def test_reset_device_when_idle_clears(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    c._current = (1.0, 2.0)
    c._current_leg_target = (3.0, 4.0)

    await c.reset_device()

    assert dev.clear_count == 1
    assert c._current is None
    assert c._current_leg_target is None
    assert c._state == SessionState.idle


@pytest.mark.asyncio
async def test_reset_device_when_active_raises(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    c._state = SessionState.running

    with pytest.raises(RuntimeError):
        await c.reset_device()
    assert dev.clear_count == 0


def test_reset_endpoint_ok(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    app = FastAPI()
    app.include_router(build_router(c), prefix="/api")
    client = TestClient(app)

    r = client.post("/api/reset")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert dev.clear_count == 1


def test_reset_endpoint_conflict_when_active(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    c._state = SessionState.running
    app = FastAPI()
    app.include_router(build_router(c), prefix="/api")
    client = TestClient(app)

    r = client.post("/api/reset")
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reset.py -v`
Expected: FAIL — `SessionController` has no attribute `reset_device`; `/api/reset` returns 404.

- [ ] **Step 3a: Add `reset_device()` to the controller**

In `trail_simulator/session/controller.py`, add this method immediately after `stop()` (after line 279):

```python
    async def reset_device(self) -> None:
        """Release the phone back to real GPS (full clear + disconnect).
        Only valid when settled — the UI must stop an active session first."""
        async with self._lifecycle_lock:
            if self._state not in (SessionState.idle, SessionState.error):
                raise RuntimeError("stop the session before resetting")
            try:
                await self._device.clear()
            except Exception:  # noqa: BLE001
                pass
            self._current = None
            self._current_leg_target = None
            self._last_error = None
            self._state = SessionState.idle
            await self._broadcast()
```

- [ ] **Step 3b: Add the `/api/reset` route**

In `trail_simulator/api/rest.py`, add immediately after the `/stop` route (after line 101):

```python
    @r.post("/reset")
    async def reset():
        try:
            await controller.reset_device()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reset.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/session/controller.py trail_simulator/api/rest.py tests/test_reset.py
git commit -m "feat(api): add reset_device() + POST /api/reset to release phone to real GPS"
```

---

## Task 4: Release device on server shutdown

Freeze means `stop()` no longer clears. So shutdown must explicitly release, or the phone is left spoofed after the server quits.

**Files:**
- Modify: `trail_simulator/main.py` (lifespan, lines 47-55)
- Test: `tests/test_shutdown_release.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shutdown_release.py
from __future__ import annotations

from fastapi.testclient import TestClient

from trail_simulator.main import build_app
from trail_simulator.session.controller import SessionController
from trail_simulator.session.store import Store


class FakeDevice:
    def __init__(self):
        self.open_count = 0
        self.set_calls = []
        self.clear_count = 0
    async def open(self):
        self.open_count += 1
    async def set(self, lat, lon):
        self.set_calls.append((lat, lon))
    async def clear(self):
        self.clear_count += 1


def test_shutdown_releases_device(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    app = build_app(c)

    # Entering/exiting the TestClient context triggers lifespan startup+shutdown.
    with TestClient(app):
        pass

    assert dev.clear_count == 1   # shutdown released the phone to real GPS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shutdown_release.py -v`
Expected: FAIL (`clear_count == 0`) — current lifespan only calls `stop()`, which now freezes.

- [ ] **Step 3: Add the release to lifespan**

In `trail_simulator/main.py`, change the lifespan `finally`:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            try:
                await controller.stop()
                await controller.reset_device()
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_shutdown_release.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest -q`
Expected: all tests pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add trail_simulator/main.py tests/test_shutdown_release.py
git commit -m "feat(main): release device to real GPS on server shutdown"
```

---

## Task 5: Web frontend — "Reset to real GPS" button

Shown/enabled only when settled (`idle`) and a spoofed position is still held. On reset, the status broadcast returns `current_lat == null`, so also drop the stale current marker.

**Files:**
- Modify: `frontend/static/index.html` (controls block, after line 47)
- Modify: `frontend/static/app.js` (onclick wiring near line 376; `renderSnapshot` near lines 422-460)

- [ ] **Step 1: Add the button to the markup**

In `frontend/static/index.html`, add after the Stop button (line 47):

```html
      <button id="reset-gps" type="button" disabled>Reset to real GPS</button>
```

- [ ] **Step 2: Wire the click handler**

In `frontend/static/app.js`, add right after the `stop` onclick block (after line 378):

```javascript
  el('reset-gps').onclick = () => runLifecycle(async () => {
    await fetch('/api/reset', { method: 'POST' });
  });
```

- [ ] **Step 3: Enable/disable the button + drop stale marker in `renderSnapshot`**

In `frontend/static/app.js` `renderSnapshot`, after the existing `el('stop').disabled = ...` line (line 429), add:

```javascript
    // Reset is offered only when settled and the phone is still holding a
    // spoofed point (frozen). Once reset, current_lat goes null.
    el('reset-gps').disabled = !(s.state === 'idle' && s.current_lat != null);
```

Then, to clear the stale dot after a reset, replace the marker block that begins
`if (s.current_lat != null && s.current_lon != null) {` (line 433) so it has an
`else` that removes the marker:

```javascript
    if (s.current_lat != null && s.current_lon != null) {
      const ll = [s.current_lat, s.current_lon];
      if (!currentMarker) {
        currentMarker = L.circleMarker(ll, {
          radius: 7, color: '#0a7', fillColor: '#0a7', fillOpacity: 0.85,
        }).addTo(map).bindTooltip('current');
      } else {
        currentMarker.setLatLng(ll);
      }
      const inSession = s.state === 'starting' || s.state === 'running' || s.state === 'paused';
      if (inSession) {
        breadcrumbPoints.push(ll);
        if (!breadcrumb) {
          breadcrumb = L.polyline(breadcrumbPoints, { color: '#0a7', weight: 3, opacity: 0.6 }).addTo(map);
        } else {
          breadcrumb.setLatLngs(breadcrumbPoints);
        }
      }
    } else if (currentMarker) {
      map.removeLayer(currentMarker);
      currentMarker = null;
    }
```

- [ ] **Step 4: Manual verification**

There is no JS test harness. Verify by hand:
- Run `python -m trail_simulator --dev-no-device` and open the UI.
- Start a trail, click Stop → state `idle`, the current dot remains, **"Reset to real GPS"** becomes enabled.
- Click **Reset to real GPS** → button disables again and the current dot disappears.

(Backend behavior is already covered by Tasks 2–4 tests.)

- [ ] **Step 5: Commit**

```bash
git add frontend/static/index.html frontend/static/app.js
git commit -m "feat(web): add 'Reset to real GPS' button for frozen sessions"
```

---

## Task 6: iOS — `BackendClient.reset()`

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift` (after line 44)
- Test: `controller-ios/ControllerApp/ControllerAppTests/BackendClientTests.swift` (new test method)

- [ ] **Step 1: Write the failing test**

Add this method inside `BackendClientTests` in `BackendClientTests.swift`:

```swift
    func testResetPostsToResetEndpoint() async throws {
        let body = #"{"ok":true}"#.data(using: .utf8)!
        let client = makeClient { req in
            XCTAssertEqual(req.url?.path, "/api/reset")
            XCTAssertEqual(req.httpMethod, "POST")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        try await client.reset()
    }
```

- [ ] **Step 2: Add `reset()` to the client**

In `BackendClient.swift`, add after the `stop()` line (line 44):

```swift
    func reset() async throws { _ = try await postEmpty("/api/reset") }
```

- [ ] **Step 3: Build to verify it compiles**

From `controller-ios/ControllerApp`:

Run: `xcodebuild build-for-testing -scheme ControllerApp -destination 'generic/platform=iOS' -derivedDataPath /tmp/dd-controller -quiet`
Expected: `** BUILD SUCCEEDED **`.

> Note (per project memory `xcodebuild-sim-wedge`): running tests on a booted simulator can hang ~50 min. Use `build-for-testing` on the generic destination for compile verification. If you choose to run the suite on a simulator and it wedges, terminate `xcodebuild` and run `xcrun simctl shutdown all` to recover.

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift \
        controller-ios/ControllerApp/ControllerAppTests/BackendClientTests.swift
git commit -m "feat(controller-ios): add BackendClient.reset() for POST /api/reset"
```

---

## Task 7: iOS — `SessionStore.apply` nulls `currentPosition` on nil coords

After a reset the snapshot carries nil coords. Today `apply` never clears `currentPosition`, so the marker and Reset button would stay stuck. Null it when coords are absent.

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Store/SessionStore.swift` (`apply`, lines 32-42)
- Test: `controller-ios/ControllerApp/ControllerAppTests/SessionStoreTests.swift` (new test method)

- [ ] **Step 1: Write the failing test**

Add inside `SessionStoreTests` in `SessionStoreTests.swift`:

```swift
    func testNilCoordinatesClearCurrentPosition() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .running, lat: 5, lon: 5))
        XCTAssertNotNil(store.currentPosition)

        // A reset broadcast carries nil coords — the marker must clear.
        store.apply(snapshot: snapshot(state: .idle, lat: nil, lon: nil))
        XCTAssertNil(store.currentPosition)
    }
```

- [ ] **Step 2: Update `apply`**

In `SessionStore.swift`, change `apply` so the coordinate block has an `else` that clears `currentPosition`:

```swift
    func apply(snapshot: StatusSnapshot) {
        latest = snapshot

        if let lat = snapshot.currentLat, let lon = snapshot.currentLon {
            let coord = CLLocationCoordinate2D(latitude: lat, longitude: lon)
            currentPosition = coord
            if Self.activeStates.contains(snapshot.state) {
                breadcrumb.append(coord)
            }
        } else {
            currentPosition = nil
        }
    }
```

- [ ] **Step 3: Build to verify it compiles**

From `controller-ios/ControllerApp`:

Run: `xcodebuild build-for-testing -scheme ControllerApp -destination 'generic/platform=iOS' -derivedDataPath /tmp/dd-controller -quiet`
Expected: `** BUILD SUCCEEDED **`.

> The existing `testNilCoordinatesAreNoOp` and `testBreadcrumbAccumulatesOnlyInActiveStates` tests still hold: the former starts from nil (stays nil); the latter only ever sends non-nil coords.

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Store/SessionStore.swift \
        controller-ios/ControllerApp/ControllerAppTests/SessionStoreTests.swift
git commit -m "feat(controller-ios): clear currentPosition when snapshot has nil coords"
```

---

## Task 8: iOS — `SessionControls` Reset button

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/SessionControls.swift` (HStack, lines 19-35)

- [ ] **Step 1: Add the Reset button**

In `SessionControls.swift`, inside the `HStack(spacing: 8)` block, add after the Stop button's closing (after line 34, before the HStack closes on line 35):

```swift
                if store.state == .idle, store.currentPosition != nil {
                    Button("Reset GPS", role: .destructive) {
                        Task {
                            await action { try await client.reset() }
                            store.clearBreadcrumb()
                        }
                    }
                    .buttonStyle(.bordered)
                }
```

- [ ] **Step 2: Build to verify it compiles**

From `controller-ios/ControllerApp`:

Run: `xcodebuild build-for-testing -scheme ControllerApp -destination 'generic/platform=iOS' -derivedDataPath /tmp/dd-controller -quiet`
Expected: `** BUILD SUCCEEDED **`.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/SessionControls.swift
git commit -m "feat(controller-ios): add Reset GPS button shown when frozen/idle"
```

---

## Final verification

- [ ] Run the full backend suite: `python -m pytest -q` → all pass.
- [ ] iOS compiles: `xcodebuild build-for-testing -scheme ControllerApp -destination 'generic/platform=iOS' -derivedDataPath /tmp/dd-controller -quiet` → BUILD SUCCEEDED.
- [ ] Manual web check (Task 5, Step 4).
- [ ] Spec coverage re-check against `docs/superpowers/specs/2026-05-22-freeze-gps-on-stop-design.md`: freeze-on-stop (Task 2), freeze-on-completion (Task 2), idempotent open (Task 1), reset endpoint/method (Task 3), shutdown release (Task 4), web button (Task 5), iOS client/store/button (Tasks 6–8).
