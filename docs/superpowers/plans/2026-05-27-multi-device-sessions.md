# Multi-Device Parallel Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let multiple iPhones (each running TrailController) connect to the **same** backend and each run its **own** independent session in parallel. Backend hosts one `SessionController` per USB-tethered UDID; each TrailController auto-binds to "its" backend session by sending its `UIDevice.current.name`, which the backend resolves to a UDID via a startup-built device registry.

**Architecture:**
- Backend: introduce `SessionManager` (dict `{udid → SessionController}`) and `DeviceRegistry` (maps DeviceName → UDID, built from lockdown). REST/WS routes read `X-Device-Name` header / `?device=` query and dispatch to the right controller. Existing `MultiLocationClient` mirror behavior is preserved behind a new opt-in `--mirror` flag.
- iOS: `BackendClient` stamps every request with `X-Device-Name`; `LiveStatusSubscriber` passes the same value in the WS query string. No UI changes required for the auto-bind path.
- Web frontend: out of scope — continues to work because the backend defaults to the single registered device when no header is provided.

**Tech Stack:** Python 3.11+ / FastAPI / pymobiledevice3 / asyncio · Swift 5.9 / SwiftUI / URLSession

---

## File Structure

**Backend (new):**
- `trail_simulator/device/registry.py` — `DeviceRegistry` + `fetch_device_name(udid)`
- `trail_simulator/session/manager.py` — `SessionManager`
- `tests/test_device_registry.py`
- `tests/test_session_manager.py`

**Backend (modified):**
- `trail_simulator/api/rest.py` — accept `X-Device-Name` / `?device=`; add `GET /api/devices`; route to `SessionManager`
- `trail_simulator/api/ws.py` — `/ws/live?device=…` routes to per-UDID controller
- `trail_simulator/main.py` — add `--mirror` flag; build registry + manager; preserve existing CLI examples

**iOS (modified):**
- `controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift` — add `deviceName`; send `X-Device-Name` on every request; add `fetchDevices()`
- `controller-ios/ControllerApp/ControllerApp/Network/LiveStatusSubscriber.swift` — `start(baseURL:deviceName:)` with `?device=` query
- `controller-ios/ControllerApp/ControllerApp/Views/RootView.swift` — thread `UIDevice.current.name` through `BackendClient` and `LiveStatusSubscriber`
- `controller-ios/ControllerApp/ControllerAppTests/` — add a header-presence test for `BackendClient`

**Docs:**
- `README.md` — new "Connecting multiple iPhones to one backend" section

---

## Tasks

### Task 1: DeviceRegistry

**Files:**
- Create: `trail_simulator/device/registry.py`
- Test:   `tests/test_device_registry.py`

- [ ] **Step 1: Write failing test for register/resolve/list and duplicate-name error**

```python
# tests/test_device_registry.py
import pytest
from trail_simulator.device.registry import DeviceRegistry, DuplicateDeviceNameError


def test_register_and_resolve_by_name():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    assert r.resolve("Jack iPhone") == "UDID-A"
    assert r.resolve("Unknown") is None


def test_list_devices_returns_all_pairs():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    r.register(udid="UDID-B", name="Spare iPhone")
    pairs = sorted(r.list_devices())
    assert pairs == [("UDID-A", "Jack iPhone"), ("UDID-B", "Spare iPhone")]


def test_duplicate_name_raises():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="iPhone")
    with pytest.raises(DuplicateDeviceNameError):
        r.register(udid="UDID-B", name="iPhone")


def test_default_udid_when_single_device():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    assert r.default_udid() == "UDID-A"


def test_default_udid_none_when_multi_or_empty():
    r = DeviceRegistry()
    assert r.default_udid() is None
    r.register(udid="UDID-A", name="A")
    r.register(udid="UDID-B", name="B")
    assert r.default_udid() is None
```

- [ ] **Step 2: Run test — confirm import error**

```bash
pytest tests/test_device_registry.py -v
```
Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 3: Implement DeviceRegistry**

```python
# trail_simulator/device/registry.py
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class DuplicateDeviceNameError(RuntimeError):
    """Two iPhones report the same DeviceName — the user must rename one."""


class DeviceRegistry:
    """In-memory map from human DeviceName to iPhone UDID.

    Populated at startup from pymobiledevice3 lockdown for each --udid the
    user passed (or the single auto-detected device). The TrailController
    iOS app sends UIDevice.current.name in the X-Device-Name header; the
    backend routes the request to the matching session.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, str] = {}
        self._by_udid: dict[str, str] = {}

    def register(self, udid: str, name: str) -> None:
        if name in self._by_name and self._by_name[name] != udid:
            raise DuplicateDeviceNameError(
                f"Two iPhones share the name {name!r}. Rename one in "
                "Settings → General → About → Name and restart the backend."
            )
        self._by_name[name] = udid
        self._by_udid[udid] = name

    def resolve(self, name: str) -> str | None:
        return self._by_name.get(name)

    def name_for(self, udid: str) -> str | None:
        return self._by_udid.get(udid)

    def list_devices(self) -> list[tuple[str, str]]:
        return [(u, n) for u, n in self._by_udid.items()]

    def default_udid(self) -> str | None:
        return next(iter(self._by_udid)) if len(self._by_udid) == 1 else None


async def fetch_device_name(udid: str) -> str:
    """Read DeviceName from pymobiledevice3 lockdown for the given UDID."""
    from pymobiledevice3.lockdown import create_using_usbmux

    lockdown = create_using_usbmux(serial=udid)
    name = (
        getattr(lockdown, "device_name", None)
        or (getattr(lockdown, "all_values", {}) or {}).get("DeviceName")
    )
    if not name:
        raise RuntimeError(f"lockdown returned no DeviceName for {udid}")
    return str(name)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/test_device_registry.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/device/registry.py tests/test_device_registry.py
git commit -m "feat(backend): add DeviceRegistry to map DeviceName → UDID"
```

---

### Task 2: SessionManager

**Files:**
- Create: `trail_simulator/session/manager.py`
- Test:   `tests/test_session_manager.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_session_manager.py
import pytest
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.controller import SessionController
from trail_simulator.session.store import Store


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


def _factory(udid):
    return _StubDevice()


def test_get_or_create_caches_per_udid(tmp_path):
    store = Store(path=tmp_path / "s.db")
    m = SessionManager(device_factory=_factory, store=store)
    c1 = m.get_or_create("UDID-A")
    c2 = m.get_or_create("UDID-A")
    c3 = m.get_or_create("UDID-B")
    assert isinstance(c1, SessionController)
    assert c1 is c2
    assert c3 is not c1


def test_list_active_returns_all(tmp_path):
    store = Store(path=tmp_path / "s.db")
    m = SessionManager(device_factory=_factory, store=store)
    m.get_or_create("UDID-A")
    m.get_or_create("UDID-B")
    assert sorted(u for u, _ in m.list_active()) == ["UDID-A", "UDID-B"]


@pytest.mark.asyncio
async def test_stop_all_stops_each(tmp_path):
    store = Store(path=tmp_path / "s.db")
    m = SessionManager(device_factory=_factory, store=store)
    m.get_or_create("UDID-A")
    m.get_or_create("UDID-B")
    await m.stop_all()  # must not raise even with no running sessions
```

- [ ] **Step 2: Run test — confirm import error**

```bash
pytest tests/test_session_manager.py -v
```

- [ ] **Step 3: Implement SessionManager**

```python
# trail_simulator/session/manager.py
from __future__ import annotations

import logging
from typing import Callable

from ..device.location import LocationClient
from .controller import SessionController
from .store import Store

log = logging.getLogger(__name__)

DeviceFactory = Callable[[str], LocationClient]


class SessionManager:
    """Holds one SessionController per iPhone UDID. Controllers are created
    lazily on first reference so iPhones that never receive a command don't
    open a DVT tunnel."""

    def __init__(self, device_factory: DeviceFactory, store: Store) -> None:
        self._factory = device_factory
        self._store = store
        self._controllers: dict[str, SessionController] = {}

    def get_or_create(self, udid: str) -> SessionController:
        c = self._controllers.get(udid)
        if c is None:
            c = SessionController(self._factory(udid), self._store)
            self._controllers[udid] = c
            log.info("session controller created for udid=%s", udid)
        return c

    def get(self, udid: str) -> SessionController | None:
        return self._controllers.get(udid)

    def list_active(self) -> list[tuple[str, SessionController]]:
        return list(self._controllers.items())

    async def stop_all(self) -> None:
        for udid, c in self._controllers.items():
            try:
                await c.stop()
                await c.reset_device()
            except Exception as e:  # noqa: BLE001
                log.warning("stop_all failed for %s: %s", udid, e)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_session_manager.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/session/manager.py tests/test_session_manager.py
git commit -m "feat(backend): add SessionManager for per-UDID session routing"
```

---

### Task 3: REST routes resolve device

**Files:**
- Modify: `trail_simulator/api/rest.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/test_rest_device_routing.py
import pytest
from fastapi.testclient import TestClient

from trail_simulator.api.rest import build_router
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store
from fastapi import FastAPI


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


def _make_app(tmp_path, names):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    for udid, name in names:
        registry.register(udid=udid, name=name)
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_router(manager, registry), prefix="/api")
    return TestClient(app)


def test_get_devices_lists_registered(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack iPhone"), ("UDID-B", "Spare")])
    resp = client.get("/api/devices")
    assert resp.status_code == 200
    body = resp.json()
    names = sorted(d["name"] for d in body["devices"])
    assert names == ["Jack iPhone", "Spare"]


def test_status_routes_by_header(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    resp = client.get("/api/status", headers={"X-Device-Name": "Jack"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "idle"


def test_status_defaults_when_single_device(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack")])
    resp = client.get("/api/status")  # no header
    assert resp.status_code == 200


def test_status_400_when_ambiguous(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    resp = client.get("/api/status")
    assert resp.status_code == 400


def test_status_404_when_name_unknown(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack")])
    resp = client.get("/api/status", headers={"X-Device-Name": "Ghost"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test — expect failures**

```bash
pytest tests/test_rest_device_routing.py -v
```

- [ ] **Step 3: Refactor build_router to take (manager, registry)**

Replace the contents of `trail_simulator/api/rest.py` with the version below. Every route resolves the device via a shared `_resolve` helper that reads `X-Device-Name` header first, then `?device=` query, then `registry.default_udid()`. Errors map to 400 (no device specified and multiple registered) or 404 (specified name not registered).

```python
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..device.registry import DeviceRegistry
from ..geocode import GeocodeError, search as geocode_search
from ..routing.osrm import RouteError
from ..session.controller import SessionController
from ..session.manager import SessionManager


class Destination(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class StartReq(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    destinations: list[Destination] = Field(..., min_length=1)
    speed_kmh: float = Field(..., gt=0, le=20)
    loop: bool = False
    skip_cooldown: bool = False


class RetargetReq(BaseModel):
    destinations: list[Destination] = Field(..., min_length=1)
    loop: bool | None = None


class SpeedReq(BaseModel):
    speed_kmh: float = Field(..., gt=0, le=20)


def build_router(manager: SessionManager, registry: DeviceRegistry) -> APIRouter:
    r = APIRouter()

    def _resolve(
        x_device_name: str | None,
        device: str | None,
    ) -> SessionController:
        name = x_device_name or device
        if name is None:
            udid = registry.default_udid()
            if udid is None:
                raise HTTPException(
                    status_code=400,
                    detail="Multiple devices registered; send X-Device-Name header.",
                )
            return manager.get_or_create(udid)
        udid = registry.resolve(name)
        if udid is None:
            raise HTTPException(
                status_code=404,
                detail=f"No backend device registered for name {name!r}.",
            )
        return manager.get_or_create(udid)

    @r.get("/devices")
    async def list_devices():
        return {
            "devices": [
                {"udid": u, "name": n} for u, n in registry.list_devices()
            ]
        }

    @r.get("/status")
    async def status(
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        return _to_dict(controller.status())

    @r.post("/session")
    async def start(
        req: StartReq,
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        dests = [(d.lat, d.lon) for d in req.destinations]
        try:
            decision = await controller.start(
                req.start_lat, req.start_lon,
                dests,
                req.speed_kmh,
                loop=req.loop,
                skip_cooldown=req.skip_cooldown,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "cooldown": True,
                    "required_wait_s": decision.required_wait_s,
                    "jump_km": decision.jump_km,
                    "reason": decision.reason,
                },
            )
        return {"ok": True, "reason": decision.reason}

    @r.post("/retarget")
    async def retarget(
        req: RetargetReq,
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        dests = [(d.lat, d.lon) for d in req.destinations]
        try:
            await controller.update_destinations(dests, loop=req.loop)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/speed")
    async def speed(
        req: SpeedReq,
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        try:
            await controller.change_speed(req.speed_kmh)
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/pause")
    async def pause(
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        await controller.pause()
        return {"ok": True}

    @r.post("/resume")
    async def resume(
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        await controller.resume()
        return {"ok": True}

    @r.post("/stop")
    async def stop(
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        await controller.stop()
        return {"ok": True}

    @r.post("/reset")
    async def reset(
        x_device_name: str | None = Header(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_device_name, device)
        try:
            await controller.reset_device()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True}

    @r.get("/search")
    async def search(q: str = "", limit: int = 8):
        query = q.strip()
        if not query:
            return {"results": []}
        capped = max(1, min(20, limit))
        try:
            results = await geocode_search(query, limit=capped)
        except GeocodeError as e:
            raise HTTPException(status_code=502, detail=f"geocode: {e}")
        return {"results": results}

    return r


def _to_dict(s) -> dict:
    d = asdict(s)
    d["state"] = s.state.value
    return d
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_rest_device_routing.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/api/rest.py tests/test_rest_device_routing.py
git commit -m "feat(backend): route REST requests by X-Device-Name header"
```

---

### Task 4: WS live filters by device

**Files:**
- Modify: `trail_simulator/api/ws.py`

- [ ] **Step 1: Add test verifying broadcast isolation**

```python
# tests/test_ws_device_routing.py
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trail_simulator.api.ws import build_ws_router
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


def test_ws_live_404_unknown_device(tmp_path):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_ws_router(manager, registry))
    client = TestClient(app)

    with client.websocket_connect("/ws/live?device=Ghost") as ws:
        # FastAPI's TestClient surfaces a close on rejection; receive will raise.
        try:
            ws.receive_text()
            assert False, "expected close on unknown device"
        except Exception:
            pass


def test_ws_live_initial_snapshot_per_device(tmp_path):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    registry.register(udid="UDID-B", name="Spare")
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_ws_router(manager, registry))
    client = TestClient(app)

    with client.websocket_connect("/ws/live?device=Jack") as ws:
        snap = json.loads(ws.receive_text())
        assert snap["state"] == "idle"
```

- [ ] **Step 2: Run — expect import errors**

```bash
pytest tests/test_ws_device_routing.py -v
```

- [ ] **Step 3: Replace ws.py**

```python
from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ..device.registry import DeviceRegistry
from ..session.controller import StatusSnapshot
from ..session.manager import SessionManager


def build_ws_router(manager: SessionManager, registry: DeviceRegistry) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        device = ws.query_params.get("device")
        if device is None:
            udid = registry.default_udid()
            if udid is None:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        else:
            udid = registry.resolve(device)
            if udid is None:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return

        controller = manager.get_or_create(udid)
        await ws.accept()
        queue: asyncio.Queue[StatusSnapshot] = asyncio.Queue(maxsize=64)

        async def listener(snap: StatusSnapshot) -> None:
            if queue.full():
                try:
                    queue.get_nowait()
                except Exception:
                    pass
            await queue.put(snap)

        controller.add_listener(listener)
        await queue.put(controller.status())

        try:
            while True:
                snap = await queue.get()
                await ws.send_json(_snap(snap))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            controller.remove_listener(listener)

    return r


def _snap(s: StatusSnapshot) -> dict:
    d = asdict(s)
    d["state"] = s.state.value
    return d
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ws_device_routing.py -v
```

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/api/ws.py tests/test_ws_device_routing.py
git commit -m "feat(backend): scope /ws/live to a specific device via ?device= query"
```

---

### Task 5: main.py wiring + --mirror flag

**Files:**
- Modify: `trail_simulator/main.py`

- [ ] **Step 1: Update CLI**

In `main()`, after the existing `--udid` argparse block, add:

```python
parser.add_argument(
    "--mirror",
    action="store_true",
    help="Mirror one session across all --udid devices (legacy fan-out). "
         "Default is parallel sessions — each --udid runs an independent "
         "session, addressed by the iPhone's DeviceName.",
)
```

Then replace the device + controller construction block (lines roughly 159-170) with:

```python
store = Store()

from .device.registry import DeviceRegistry, fetch_device_name
from .session.manager import SessionManager

registry = DeviceRegistry()

if args.dev_no_device:
    # Stub: register a single fake device named after this Mac.
    import socket
    fake_udid = resolved_udids[0] or "DEV-STUB"
    registry.register(udid=fake_udid, name=socket.gethostname())
    def _factory(udid):
        return _StubLocation(udid=udid)
    manager = SessionManager(device_factory=_factory, store=store)
elif args.mirror and len(resolved_udids) > 1:
    # Legacy mirror mode: one controller, MultiLocationClient across N devices.
    mirror_udids = [u for u in resolved_udids if u is not None]
    primary_udid = mirror_udids[0]
    try:
        primary_name = asyncio.run(fetch_device_name(primary_udid))
    except Exception:  # noqa: BLE001
        primary_name = primary_udid
    registry.register(udid=primary_udid, name=primary_name)
    mirror_client = MultiLocationClient(mirror_udids)
    def _factory(udid):  # returns the shared mirror client every time
        return mirror_client
    manager = SessionManager(device_factory=_factory, store=store)
    print(f"[devices] --mirror active for {len(mirror_udids)} devices "
          f"(addressable as {primary_name!r})")
else:
    # Default: one SessionController per UDID. Build the registry by
    # asking each device for its DeviceName.
    for u in resolved_udids:
        if u is None:
            continue
        try:
            name = asyncio.run(fetch_device_name(u))
        except Exception as e:  # noqa: BLE001
            log.warning("could not read DeviceName for %s, using UDID: %s", u, e)
            name = u
        registry.register(udid=u, name=name)
    def _factory(udid):
        return LocationClient(udid=udid)
    manager = SessionManager(device_factory=_factory, store=store)
    if len(resolved_udids) > 1:
        names = ", ".join(n for _, n in registry.list_devices())
        print(f"[devices] parallel session mode for {len(resolved_udids)} "
              f"devices: {names}")

from .api.ws_steps import broadcaster as _step_broadcaster
# Step broadcaster is global today; wire it to broadcast on every controller.
_step_broadcaster.set_change_callback(
    lambda: asyncio.gather(*[c._broadcast() for _, c in manager.list_active()])
)
app = build_app(manager, registry)
```

Then update `build_app`:

```python
def build_app(manager: SessionManager, registry: DeviceRegistry) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            try:
                await manager.stop_all()
            except Exception:
                pass

    app = FastAPI(title="Trail Simulator", lifespan=lifespan)
    app.include_router(build_router(manager, registry), prefix="/api")
    app.include_router(build_ws_router(manager, registry))
    app.include_router(build_ws_steps_router())
    ...
```

- [ ] **Step 2: Manual smoke**

```bash
python -m trail_simulator --dev-no-device --no-browser --port 8080 &
sleep 2
curl -s http://127.0.0.1:8080/api/devices | python -m json.tool
curl -s http://127.0.0.1:8080/api/status | python -m json.tool  # default udid
kill %1
```
Expected: `/api/devices` lists one entry; `/api/status` returns idle.

- [ ] **Step 3: Commit**

```bash
git add trail_simulator/main.py
git commit -m "feat(backend): wire SessionManager + DeviceRegistry in main; add --mirror"
```

---

### Task 6: iOS BackendClient sends X-Device-Name

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift`

- [ ] **Step 1: Add deviceName state + header injection**

Edit BackendClient: change the actor to hold `private var deviceName: String?`, accept it in the initializer, and add `func updateDeviceName(_ name: String?)`. Update `getJSON`, `postJSON`, `postEmpty`, and `search(query:)` to set `request.setValue(name, forHTTPHeaderField: "X-Device-Name")` whenever `deviceName` is non-nil.

Add a new struct + endpoint:

```swift
struct BackendDevice: Codable, Sendable {
    let udid: String
    let name: String
}

private struct DevicesResponse: Codable, Sendable {
    let devices: [BackendDevice]
}

func fetchDevices() async throws -> [BackendDevice] {
    try await getJSON("/api/devices", as: DevicesResponse.self).devices
}
```

Concretely the `private func postEmpty(_ path: String)` becomes:

```swift
private func postEmpty(_ path: String) async throws -> Bool {
    var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
    req.httpMethod = "POST"
    applyDeviceHeader(&req)
    let (data, resp) = try await session.data(for: req)
    try checkOk(resp, data: data, isStart: false)
    return (try? decoder.decode(Ok.self, from: data).ok) ?? true
}

private func applyDeviceHeader(_ req: inout URLRequest) {
    if let name = deviceName {
        req.setValue(name, forHTTPHeaderField: "X-Device-Name")
    }
}
```

Apply the same `applyDeviceHeader(&req)` line in `getJSON`, `postJSON`, and `search`.

- [ ] **Step 2: Test (lightweight Xcode unit test)**

Add to `controller-ios/ControllerApp/ControllerAppTests/BackendClientHeaderTests.swift`:

```swift
import XCTest
@testable import ControllerApp

final class BackendClientHeaderTests: XCTestCase {
    func testDeviceHeaderAppliedToRequests() async throws {
        let url = URL(string: "http://127.0.0.1:0/")!
        let recorder = HeaderRecordingURLProtocol.self
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [recorder]
        let session = URLSession(configuration: config)
        let client = BackendClient(baseURL: url, deviceName: "Jack iPhone", session: session)

        _ = try? await client.fetchStatus()  // recorder fakes a response

        XCTAssertEqual(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"), "Jack iPhone")
    }
}

final class HeaderRecordingURLProtocol: URLProtocol {
    nonisolated(unsafe) static var lastRequest: URLRequest?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lastRequest = request
        let resp = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
        let body = Data("{\"state\":\"idle\"}".utf8)
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
```

The BackendClient initializer must change to accept `deviceName: String?` (default nil) and `session: URLSession` (already there). Update existing call sites (`RootView`) accordingly in the next task.

- [ ] **Step 3: Build + run tests**

```bash
xcodebuild test -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,id=12317245-05FA-4166-8191-4DCE64B2B9D0' -only-testing:ControllerAppTests/BackendClientHeaderTests 2>&1 | tail -30
```

(Use the iPhone 17 simulator UDID from prior runs. If that simulator is unavailable, `xcrun simctl list devices | grep iPhone` to pick another.)

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift \
        controller-ios/ControllerApp/ControllerAppTests/BackendClientHeaderTests.swift
git commit -m "feat(ios): send X-Device-Name on every backend request"
```

---

### Task 7: iOS LiveStatusSubscriber passes device

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Network/LiveStatusSubscriber.swift`

- [ ] **Step 1: Add deviceName parameter**

Change `start(baseURL:)` to `start(baseURL:deviceName:)`. Update `webSocketURL` to take a `deviceName` and append `URLQueryItem(name: "device", value: deviceName)`:

```swift
static func webSocketURL(from baseURL: URL, deviceName: String?) -> URL {
    var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
    components.scheme = (baseURL.scheme == "https") ? "wss" : "ws"
    components.path = "/ws/live"
    if let name = deviceName {
        components.queryItems = [URLQueryItem(name: "device", value: name)]
    } else {
        components.query = nil
    }
    return components.url!
}
```

And the `start(baseURL:deviceName:)` signature passes `deviceName` into the closure capturing `wsURL`.

- [ ] **Step 2: Add a unit test for the URL construction**

Append to existing `LiveStatusSubscriberTests.swift` (or create one if absent):

```swift
func testWebSocketURLEncodesDeviceQuery() {
    let url = LiveStatusSubscriber.webSocketURL(
        from: URL(string: "http://10.0.0.1:8080/")!,
        deviceName: "Jack iPhone"
    )
    XCTAssertEqual(url.absoluteString, "ws://10.0.0.1:8080/ws/live?device=Jack%20iPhone")
}

func testWebSocketURLNoDevice() {
    let url = LiveStatusSubscriber.webSocketURL(
        from: URL(string: "http://10.0.0.1:8080/")!,
        deviceName: nil
    )
    XCTAssertEqual(url.absoluteString, "ws://10.0.0.1:8080/ws/live")
}
```

- [ ] **Step 3: Build + test**

```bash
xcodebuild test -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,id=12317245-05FA-4166-8191-4DCE64B2B9D0' 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Network/LiveStatusSubscriber.swift \
        controller-ios/ControllerApp/ControllerAppTests/
git commit -m "feat(ios): scope /ws/live subscription to UIDevice.current.name"
```

---

### Task 8: Wire device name through RootView

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/RootView.swift`

- [ ] **Step 1: Thread UIDevice.current.name to BackendClient and subscriber**

Change `init()`:

```swift
init() {
    let cfg = BackendConfig.loadFromUserDefaults()
    _config = State(initialValue: cfg)
    _client = State(initialValue: BackendClient(baseURL: cfg.baseURL, deviceName: UIDevice.current.name))
}
```

In the `.task(id: ConnectionKey(...))` block, replace `subscriber.start(baseURL: config.baseURL)` with `subscriber.start(baseURL: config.baseURL, deviceName: UIDevice.current.name)`.

`health.connect(baseURL:label:)` already passes `UIDevice.current.name` — no change.

- [ ] **Step 2: Build**

```bash
xcodebuild build -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -10
```

Expected: BUILD SUCCEEDED.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/RootView.swift
git commit -m "feat(ios): bind each TrailController to its own device name"
```

---

### Task 9: README "Connecting multiple iPhones to one backend"

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a top-level section**

Add a new section under the existing iOS / TrailController section in `README.md`:

```markdown
## Connecting multiple iPhones to one backend

TrailController supports running an independent session on each iPhone connected to the same Mac and the same backend. Each iPhone gets its own spoofed GPS track without interfering with the others.

**How it works**

- The backend builds a registry mapping each `--udid` to that iPhone's DeviceName (Settings → General → About → Name) at startup.
- Each TrailController iPhone sends `UIDevice.current.name` in the `X-Device-Name` HTTP header and the `?device=` WebSocket query on every request.
- The backend routes the request to the matching session — one `SessionController` per UDID.

**Setup**

1. Make sure every iPhone has a **unique** name in Settings → General → About → Name. The backend will refuse to start if two iPhones share a name.
2. Plug each iPhone into the Mac via USB (or use Wi-Fi pairing once they're paired). Tap "Trust".
3. Run `sudo pymobiledevice3 remote tunneld` and keep it running.
4. Start the backend with one `--udid` flag per iPhone:

   ```bash
   python -m trail_simulator --port 8080 \
     --udid 00008140-001A2B3C4D5E6F70 \
     --udid 00008130-005ABCDE12345678
   ```

   On startup you'll see `[devices] parallel session mode for 2 devices: Jack iPhone, Spare iPhone`.

5. On **each iPhone**, install TrailController and point Settings → Backend at `http://<your-mac-LAN-ip>:8080`. No further configuration is needed — the app auto-binds by DeviceName.

**Verify**

```bash
curl http://127.0.0.1:8080/api/devices
# {"devices":[{"udid":"00008140-...","name":"Jack iPhone"}, ...]}

curl -H "X-Device-Name: Jack iPhone" http://127.0.0.1:8080/api/status
# {"state":"idle", ...}
```

**Falling back to mirror mode**

If you want one session that fans out to multiple iPhones (the original behaviour — useful for keeping a spare phone in sync with the primary), add `--mirror`:

```bash
python -m trail_simulator --port 8080 --mirror \
  --udid 00008140-... --udid 00008130-...
```

In mirror mode only the primary iPhone's DeviceName is registered; all spoofed devices follow that one session.

**Troubleshooting**

- *"No backend device registered for name 'X'"*: the iPhone's name isn't in the backend's startup list. Confirm with `curl /api/devices` and rename the iPhone or re-launch the backend with the right `--udid`.
- *"Multiple devices registered; send X-Device-Name header"*: someone hit a backend endpoint without the header while two or more devices are registered. The web frontend always falls back to the first device; this only affects custom tooling.
- Two iPhones with the same name: the backend will exit on startup. Rename one in Settings → General → About → Name.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: explain multi-iPhone parallel session setup"
```

---

## Self-review notes

- Backwards compatibility: a single-iPhone setup with no `X-Device-Name` header still works because `_resolve` falls back to `registry.default_udid()` when exactly one device is registered. Existing web frontend continues to work.
- `--mirror` keeps the old `MultiLocationClient` behaviour for users who already documented or scripted it.
- Step companion channel (`/ws/steps`) is intentionally not scoped per session — it already supports multiple clients via labels and remains compatible with both single and multi-device modes.
- HealthKit/`StepCompanionsPanel` is unchanged.
- iOS app does **not** add UI for picking a device because the auto-bind path covers the explicit user choice ("Backend + iOS + docs only — auto-bind by device name"). A future task could add a Settings list showing `GET /api/devices`.
