# UUID Identity & Follow-a-Leader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each iPhone a user-controllable UUID identity (default = device name, must be unique), fix parallel-session collisions by routing on that UUID, and let an iPhone follow another's route by UUID — either watch-only on the map or mirror the leader's GPS onto its own phone.

**Architecture:** `SessionManager` stays keyed by UDID (one phone = one GPS = one session). `DeviceRegistry` gains a `client_id ↔ udid` binding map; REST/WS resolve `X-Client-Id`/`?client=` first, then fall back to the existing `X-Device-Name` path. A follower's `SessionController` mirrors a leader's position snapshots to its own device. iOS adds a Settings UUID field (validated against the backend on Save) and a Map "Follow leader" sheet.

**Tech Stack:** Python 3.11+ / FastAPI / pytest · Swift 5.9 / SwiftUI / URLSession / XCTest

Spec: `docs/superpowers/specs/2026-05-29-uuid-identity-and-follow-design.md`

---

## File Structure

**Backend (modified):**
- `trail_simulator/device/registry.py` — add `client_id↔udid` binding + `DuplicateClientIdError`
- `trail_simulator/session/controller.py` — add `SessionState.following`, `follow()`/`unfollow()`, `following_leader` snapshot field
- `trail_simulator/api/rest.py` — client-id resolution precedence; `POST /api/bind`, `GET /api/clients`, `POST /api/follow`, `POST /api/unfollow`; `bound_client_id` on `/api/devices`
- `trail_simulator/api/ws.py` — `?client=` precedence on `/ws/live`

**Backend (tests, created):**
- `tests/test_registry_clientid.py`, `tests/test_controller_follow.py`, `tests/test_rest_clientid_follow.py`, `tests/test_ws_clientid.py`

**iOS (modified):**
- `Network/BackendConfig.swift` — add `clientId`
- `Network/BackendClient.swift` — `X-Client-Id` header; `bind`, `fetchClients`, `follow`, `unfollow`; new models
- `Network/LiveStatusSubscriber.swift` — `?client=` query
- `Models/SessionState.swift` — add `following`
- `Models/StatusSnapshot.swift` — add `followingLeader`
- `Views/RootView.swift` — thread `clientId`; subscriber repoint for watch-only follow
- `Views/SettingsScreen.swift` — "Identity" section + bind-on-save validation
- `Views/MapTabView.swift` — Follow toolbar button + sheet + stop control
- `Store/SessionStore.swift` — `watchingLeaderId`

**iOS (tests, created/modified):**
- `ControllerAppTests/BackendConfigClientIdTests.swift` (new), `BackendClientHeaderTests.swift` (extend), `LiveStatusSubscriberTests.swift` (extend)

**Docs:** `README.md`

`main.py` needs **no change** — client bindings are established dynamically via `/api/bind`; `--dev-no-device` and the name-registry path are unaffected.

---

## Task 1: DeviceRegistry client-id binding

**Files:**
- Modify: `trail_simulator/device/registry.py`
- Test: `tests/test_registry_clientid.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry_clientid.py
import pytest
from trail_simulator.device.registry import DeviceRegistry, DuplicateClientIdError


def _reg(*pairs):
    r = DeviceRegistry()
    for udid, name in pairs:
        r.register(udid=udid, name=name)
    return r


def test_bind_and_resolve_client():
    r = _reg(("UDID-A", "Jack"))
    r.bind("uuid-1", "UDID-A")
    assert r.resolve_client("uuid-1") == "UDID-A"
    assert r.client_for("UDID-A") == "uuid-1"
    assert r.resolve_client("nope") is None


def test_bind_same_client_same_udid_idempotent():
    r = _reg(("UDID-A", "Jack"))
    r.bind("uuid-1", "UDID-A")
    r.bind("uuid-1", "UDID-A")  # no raise
    assert r.resolve_client("uuid-1") == "UDID-A"


def test_duplicate_client_id_on_other_udid_raises():
    r = _reg(("UDID-A", "Jack"), ("UDID-B", "Spare"))
    r.bind("uuid-1", "UDID-A")
    with pytest.raises(DuplicateClientIdError):
        r.bind("uuid-1", "UDID-B")


def test_rebinding_udid_releases_old_client():
    r = _reg(("UDID-A", "Jack"))
    r.bind("old", "UDID-A")
    r.bind("new", "UDID-A")
    assert r.resolve_client("old") is None
    assert r.resolve_client("new") == "UDID-A"
    assert r.client_for("UDID-A") == "new"


def test_auto_bind_single():
    r = _reg(("UDID-A", "Jack"))
    assert r.auto_bind_single("uuid-x") == "UDID-A"
    assert r.resolve_client("uuid-x") == "UDID-A"


def test_auto_bind_single_none_when_multiple():
    r = _reg(("UDID-A", "Jack"), ("UDID-B", "Spare"))
    assert r.auto_bind_single("uuid-x") is None


def test_auto_bind_single_none_when_already_bound_to_other():
    r = _reg(("UDID-A", "Jack"))
    r.bind("owner", "UDID-A")
    assert r.auto_bind_single("intruder") is None


def test_list_clients():
    r = _reg(("UDID-A", "Jack"), ("UDID-B", "Spare"))
    r.bind("uuid-1", "UDID-A")
    assert r.list_clients() == [("uuid-1", "UDID-A", "Jack")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry_clientid.py -v`
Expected: ImportError (`DuplicateClientIdError`) / AttributeError.

- [ ] **Step 3: Implement the binding map**

In `trail_simulator/device/registry.py`, add the error class after `DuplicateDeviceNameError`:

```python
class DuplicateClientIdError(RuntimeError):
    """Another device already registered this client UUID."""
```

In `DeviceRegistry.__init__`, add two maps:

```python
    def __init__(self) -> None:
        self._by_name: dict[str, str] = {}
        self._by_udid: dict[str, str] = {}
        self._client_to_udid: dict[str, str] = {}
        self._udid_to_client: dict[str, str] = {}
```

Add these methods to `DeviceRegistry` (after `default_udid`):

```python
    def bind(self, client_id: str, udid: str) -> None:
        existing = self._client_to_udid.get(client_id)
        if existing is not None and existing != udid:
            raise DuplicateClientIdError(
                f"client id {client_id!r} is already bound to another device."
            )
        old = self._udid_to_client.get(udid)
        if old is not None and old != client_id:
            self._client_to_udid.pop(old, None)
        self._client_to_udid[client_id] = udid
        self._udid_to_client[udid] = client_id

    def resolve_client(self, client_id: str) -> str | None:
        return self._client_to_udid.get(client_id)

    def client_for(self, udid: str) -> str | None:
        return self._udid_to_client.get(udid)

    def auto_bind_single(self, client_id: str) -> str | None:
        if len(self._by_udid) != 1:
            return None
        udid = next(iter(self._by_udid))
        existing = self._udid_to_client.get(udid)
        if existing is not None and existing != client_id:
            return None
        self.bind(client_id, udid)
        return udid

    def list_clients(self) -> list[tuple[str, str, str]]:
        return [
            (cid, udid, self._by_udid.get(udid, ""))
            for cid, udid in self._client_to_udid.items()
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry_clientid.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/device/registry.py tests/test_registry_clientid.py
git commit -m "feat(backend): add client-id binding map to DeviceRegistry"
```

---

## Task 2: SessionController follow/unfollow

**Files:**
- Modify: `trail_simulator/session/controller.py`
- Test: `tests/test_controller_follow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_controller_follow.py
import pytest
from trail_simulator.session.controller import SessionController, SessionState
from trail_simulator.session.store import Store


class _RecordingDevice:
    def __init__(self):
        self.points = []
        self.opened = False
    async def open(self):
        self.opened = True
    async def set(self, lat, lon):
        self.points.append((lat, lon))
    async def clear(self):
        pass


def _controller(tmp_path, name):
    return SessionController(_RecordingDevice(), Store(path=tmp_path / f"{name}.db"))


@pytest.mark.asyncio
async def test_follow_mirrors_leader_position(tmp_path):
    leader = _controller(tmp_path, "leader")
    follower = _controller(tmp_path, "follower")

    await follower.follow(leader, "Leader iPhone")
    assert follower.status().state == SessionState.following
    assert follower.status().following_leader == "Leader iPhone"

    # Simulate the leader producing a position update.
    leader._current = (35.0, 139.0)
    await leader._broadcast()

    assert follower._device.points[-1] == (35.0, 139.0)


@pytest.mark.asyncio
async def test_unfollow_stops_mirroring(tmp_path):
    leader = _controller(tmp_path, "leader2")
    follower = _controller(tmp_path, "follower2")
    await follower.follow(leader, "Leader iPhone")
    await follower.unfollow()
    assert follower.status().state == SessionState.idle
    assert follower.status().following_leader is None

    before = len(follower._device.points)
    leader._current = (1.0, 2.0)
    await leader._broadcast()
    assert len(follower._device.points) == before  # no longer mirroring


@pytest.mark.asyncio
async def test_cannot_follow_self(tmp_path):
    c = _controller(tmp_path, "selfc")
    with pytest.raises(RuntimeError):
        await c.follow(c, "Me")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_controller_follow.py -v`
Expected: AttributeError (`follow` not defined) / `following` not on `SessionState`.

- [ ] **Step 3: Add the state, snapshot field, fields, and methods**

In `SessionState` (controller.py), add a member:

```python
class SessionState(str, Enum):
    idle = "idle"
    starting = "starting"
    running = "running"
    paused = "paused"
    stopping = "stopping"
    reconnecting = "reconnecting"
    error = "error"
    following = "following"
```

In the `StatusSnapshot` dataclass, add a field at the end (default keeps existing callers valid):

```python
    step_companions: list[dict]
    following_leader: str | None = None
```

In `SessionController.__init__`, add (near the listener fields):

```python
        self._follow_source: "SessionController | None" = None
        self._follow_listener: Listener | None = None
        self._following_leader: str | None = None
```

In `status()`, pass the new field to `StatusSnapshot(...)`:

```python
            step_companions=_step_broadcaster.snapshot(),
            following_leader=self._following_leader,
        )
```

Add the two methods (after `reset_device`):

```python
    async def follow(self, leader: "SessionController", leader_label: str) -> None:
        """Mirror `leader`'s live position onto this controller's device until
        unfollow(). Stops any session this controller is currently running."""
        if leader is self:
            raise RuntimeError("cannot follow self")
        if self._state in (
            SessionState.running,
            SessionState.starting,
            SessionState.paused,
            SessionState.reconnecting,
        ):
            await self.stop()
        await self._device.open()

        async def _mirror(snap: StatusSnapshot) -> None:
            if snap.current_lat is None or snap.current_lon is None:
                return
            try:
                await self._device.set(snap.current_lat, snap.current_lon)
                self._current = (snap.current_lat, snap.current_lon)
            except Exception:  # noqa: BLE001
                pass

        self._follow_source = leader
        self._follow_listener = _mirror
        self._following_leader = leader_label
        leader.add_listener(_mirror)
        self._state = SessionState.following

        # Seed immediately from the leader's current position.
        await _mirror(leader.status())
        await self._broadcast()

    async def unfollow(self) -> None:
        if self._follow_source is not None and self._follow_listener is not None:
            self._follow_source.remove_listener(self._follow_listener)
        self._follow_source = None
        self._follow_listener = None
        self._following_leader = None
        self._state = SessionState.idle
        await self._broadcast()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_controller_follow.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/session/controller.py tests/test_controller_follow.py
git commit -m "feat(backend): SessionController follow/unfollow mirrors a leader"
```

---

## Task 3: REST client-id routing + bind/clients/follow endpoints

**Files:**
- Modify: `trail_simulator/api/rest.py`
- Test: `tests/test_rest_clientid_follow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rest_clientid_follow.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trail_simulator.api.rest import build_router
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


def _make(tmp_path, names):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    for udid, name in names:
        registry.register(udid=udid, name=name)
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_router(manager, registry), prefix="/api")
    return TestClient(app)


def test_bind_then_route_by_client_id(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    assert c.post("/api/bind", json={"client_id": "uuid-1", "udid": "UDID-A"}).status_code == 200
    r = c.get("/api/status", headers={"X-Client-Id": "uuid-1"})
    assert r.status_code == 200 and r.json()["state"] == "idle"


def test_bind_duplicate_returns_409(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    c.post("/api/bind", json={"client_id": "uuid-1", "udid": "UDID-A"})
    r = c.post("/api/bind", json={"client_id": "uuid-1", "udid": "UDID-B"})
    assert r.status_code == 409


def test_bind_unknown_udid_404(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack")])
    r = c.post("/api/bind", json={"client_id": "uuid-1", "udid": "GHOST"})
    assert r.status_code == 404


def test_unbound_client_auto_binds_single_device(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack")])
    r = c.get("/api/status", headers={"X-Client-Id": "fresh"})
    assert r.status_code == 200


def test_unbound_client_multi_device_400(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    r = c.get("/api/status", headers={"X-Client-Id": "fresh"})
    assert r.status_code == 400


def test_devices_includes_bound_client_id(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack")])
    c.post("/api/bind", json={"client_id": "uuid-1", "udid": "UDID-A"})
    body = c.get("/api/devices").json()
    entry = next(d for d in body["devices"] if d["udid"] == "UDID-A")
    assert entry["bound_client_id"] == "uuid-1"


def test_clients_lists_bound(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack")])
    c.post("/api/bind", json={"client_id": "uuid-1", "udid": "UDID-A"})
    body = c.get("/api/clients").json()
    assert body["clients"] == [{"client_id": "uuid-1", "name": "Jack", "state": "idle"}]


def test_follow_self_400(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack")])
    c.post("/api/bind", json={"client_id": "uuid-1", "udid": "UDID-A"})
    r = c.post("/api/follow", json={"follower_client_id": "uuid-1", "leader_client_id": "uuid-1"})
    assert r.status_code == 400


def test_follow_and_unfollow_ok(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    c.post("/api/bind", json={"client_id": "f", "udid": "UDID-A"})
    c.post("/api/bind", json={"client_id": "l", "udid": "UDID-B"})
    assert c.post("/api/follow", json={"follower_client_id": "f", "leader_client_id": "l"}).status_code == 200
    assert c.get("/api/status", headers={"X-Client-Id": "f"}).json()["state"] == "following"
    assert c.post("/api/unfollow", json={"client_id": "f"}).status_code == 200
    assert c.get("/api/status", headers={"X-Client-Id": "f"}).json()["state"] == "idle"


def test_follow_unknown_leader_404(tmp_path):
    c = _make(tmp_path, [("UDID-A", "Jack")])
    c.post("/api/bind", json={"client_id": "f", "udid": "UDID-A"})
    r = c.post("/api/follow", json={"follower_client_id": "f", "leader_client_id": "ghost"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rest_clientid_follow.py -v`
Expected: failures (endpoints / params missing).

- [ ] **Step 3: Replace `trail_simulator/api/rest.py` with this complete file**

```python
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..device.registry import DeviceRegistry, DuplicateClientIdError
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


class BindReq(BaseModel):
    client_id: str = Field(..., min_length=1)
    udid: str = Field(..., min_length=1)


class FollowReq(BaseModel):
    follower_client_id: str = Field(..., min_length=1)
    leader_client_id: str = Field(..., min_length=1)


class UnfollowReq(BaseModel):
    client_id: str = Field(..., min_length=1)


def build_router(manager: SessionManager, registry: DeviceRegistry) -> APIRouter:
    r = APIRouter()

    def _resolve(
        x_client_id: str | None,
        x_device_name: str | None,
        client: str | None,
        device: str | None,
    ) -> SessionController:
        cid = x_client_id or client
        if cid:
            udid = registry.resolve_client(cid)
            if udid is None:
                udid = registry.auto_bind_single(cid)
            if udid is None:
                raise HTTPException(
                    status_code=400,
                    detail="Unbound client id; POST /api/bind to choose a device.",
                )
            return manager.get_or_create(udid)

        # Fallback: legacy device-name path (web frontend / single device).
        name = x_device_name or device
        udid = registry.resolve(name) if name else None
        if udid is None:
            udid = registry.default_udid()
        if udid is None:
            if name is None:
                raise HTTPException(
                    status_code=400,
                    detail="Multiple devices registered; send X-Device-Name header.",
                )
            raise HTTPException(
                status_code=404,
                detail=f"No backend device registered for name {name!r}.",
            )
        return manager.get_or_create(udid)

    @r.get("/devices")
    async def list_devices():
        return {
            "devices": [
                {"udid": u, "name": n, "bound_client_id": registry.client_for(u)}
                for u, n in registry.list_devices()
            ]
        }

    @r.get("/clients")
    async def list_clients():
        out = []
        for cid, udid, name in registry.list_clients():
            c = manager.get(udid)
            state = c.status().state.value if c else "idle"
            out.append({"client_id": cid, "name": name, "state": state})
        return {"clients": out}

    @r.post("/bind")
    async def bind(req: BindReq):
        if registry.name_for(req.udid) is None:
            raise HTTPException(
                status_code=404,
                detail=f"No connected device with udid {req.udid!r}.",
            )
        try:
            registry.bind(req.client_id, req.udid)
        except DuplicateClientIdError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True}

    @r.post("/follow")
    async def follow(req: FollowReq):
        f_udid = registry.resolve_client(req.follower_client_id)
        if f_udid is None:
            raise HTTPException(status_code=404, detail="Unknown follower client id.")
        l_udid = registry.resolve_client(req.leader_client_id)
        if l_udid is None:
            raise HTTPException(status_code=404, detail="Unknown leader client id.")
        if f_udid == l_udid:
            raise HTTPException(status_code=400, detail="A device cannot follow itself.")
        follower = manager.get_or_create(f_udid)
        leader = manager.get_or_create(l_udid)
        label = registry.name_for(l_udid) or req.leader_client_id
        await follower.follow(leader, label)
        return {"ok": True}

    @r.post("/unfollow")
    async def unfollow(req: UnfollowReq):
        udid = registry.resolve_client(req.client_id)
        if udid is None:
            raise HTTPException(status_code=404, detail="Unknown client id.")
        await manager.get_or_create(udid).unfollow()
        return {"ok": True}

    @r.get("/status")
    async def status(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        return _to_dict(controller.status())

    @r.post("/session")
    async def start(
        req: StartReq,
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
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
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
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
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        try:
            await controller.change_speed(req.speed_kmh)
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/pause")
    async def pause(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        await controller.pause()
        return {"ok": True}

    @r.post("/resume")
    async def resume(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        await controller.resume()
        return {"ok": True}

    @r.post("/stop")
    async def stop(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        await controller.stop()
        return {"ok": True}

    @r.post("/reset")
    async def reset(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
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

- [ ] **Step 4: Run tests to verify they pass (incl. regression)**

Run: `pytest tests/test_rest_clientid_follow.py tests/test_rest_device_routing.py -v`
Expected: all pass (new suite + the existing device-name suite).

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/api/rest.py tests/test_rest_clientid_follow.py
git commit -m "feat(backend): route by X-Client-Id; add bind/clients/follow/unfollow"
```

---

## Task 4: WebSocket `?client=` precedence

**Files:**
- Modify: `trail_simulator/api/ws.py`
- Test: `tests/test_ws_clientid.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ws_clientid.py
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


def _app(tmp_path):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    registry.register(udid="UDID-B", name="Spare")
    registry.bind("uuid-1", "UDID-A")
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_ws_router(manager, registry))
    return TestClient(app)


def test_ws_live_by_client_id(tmp_path):
    client = _app(tmp_path)
    with client.websocket_connect("/ws/live?client=uuid-1") as ws:
        snap = json.loads(ws.receive_text())
        assert snap["state"] == "idle"


def test_ws_live_unbound_client_closed(tmp_path):
    client = _app(tmp_path)
    with client.websocket_connect("/ws/live?client=ghost") as ws:
        try:
            ws.receive_text()
            assert False, "expected close"
        except Exception:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ws_clientid.py -v`
Expected: failure (client param not handled).

- [ ] **Step 3: Update `ws_live` resolution in `trail_simulator/api/ws.py`**

Replace the resolution block at the top of `ws_live` (the lines computing `device`/`udid` before `controller = manager.get_or_create(udid)`) with:

```python
        client = ws.query_params.get("client")
        device = ws.query_params.get("device")
        if client:
            udid = registry.resolve_client(client)
            if udid is None:
                udid = registry.auto_bind_single(client)
        else:
            udid = registry.resolve(device) if device else None
            if udid is None:
                udid = registry.default_udid()
        if udid is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
```

- [ ] **Step 4: Run tests to verify they pass (incl. regression)**

Run: `pytest tests/test_ws_clientid.py tests/test_ws_device_routing.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add trail_simulator/api/ws.py tests/test_ws_clientid.py
git commit -m "feat(backend): scope /ws/live by ?client= with device-name fallback"
```

---

## Task 5: iOS BackendConfig clientId

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Network/BackendConfig.swift`
- Test: `controller-ios/ControllerApp/ControllerAppTests/BackendConfigClientIdTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
// ControllerAppTests/BackendConfigClientIdTests.swift
import XCTest
@testable import ControllerApp

final class BackendConfigClientIdTests: XCTestCase {
    private func freshDefaults() -> UserDefaults {
        let d = UserDefaults(suiteName: "BackendConfigClientIdTests")!
        d.removePersistentDomain(forName: "BackendConfigClientIdTests")
        return d
    }

    func testDefaultsToProvidedDeviceNameWhenUnset() {
        let d = freshDefaults()
        let cfg = BackendConfig.loadFromUserDefaults(d, defaultClientId: "Jack’s iPhone")
        XCTAssertEqual(cfg.clientId, "Jack’s iPhone")
    }

    func testPersistedCustomClientIdWins() {
        let d = freshDefaults()
        var cfg = BackendConfig.loadFromUserDefaults(d, defaultClientId: "iPhone")
        cfg.clientId = "custom-uuid-123"
        cfg.save(to: d)

        let reloaded = BackendConfig.loadFromUserDefaults(d, defaultClientId: "iPhone")
        XCTAssertEqual(reloaded.clientId, "custom-uuid-123")
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run (build): `xcodebuild build-for-testing -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -15`
Expected: compile error — `clientId` / `defaultClientId:` missing.

- [ ] **Step 3: Add clientId to BackendConfig**

Replace `controller-ios/ControllerApp/ControllerApp/Network/BackendConfig.swift` with:

```swift
import Foundation

struct BackendConfig: Equatable, Sendable {
    var baseURL: URL
    // Primary routing identity sent as X-Client-Id. Defaults to the device
    // name; the user can override it in Settings (persisted below).
    var clientId: String
    // Legacy fallback identity (X-Device-Name) kept for the web frontend /
    // single-device path.
    var deviceName: String?

    static let storageKey = "BackendConfig.baseURL"
    static let clientIdKey = "BackendConfig.clientId"
    static let deviceNameKey = "BackendConfig.deviceName"

    static func loadFromUserDefaults(
        _ defaults: UserDefaults = .standard,
        defaultClientId: String
    ) -> BackendConfig {
        let url = (defaults.string(forKey: storageKey)).flatMap(URL.init(string:))
            ?? URL(string: "http://127.0.0.1:8787")!
        let clientId = defaults.string(forKey: clientIdKey) ?? defaultClientId
        let name = defaults.string(forKey: deviceNameKey)
        return BackendConfig(baseURL: url, clientId: clientId, deviceName: name)
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(baseURL.absoluteString, forKey: Self.storageKey)
        defaults.set(clientId, forKey: Self.clientIdKey)
        if let deviceName {
            defaults.set(deviceName, forKey: Self.deviceNameKey)
        } else {
            defaults.removeObject(forKey: Self.deviceNameKey)
        }
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `xcodebuild test -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ControllerAppTests/BackendConfigClientIdTests 2>&1 | tail -15`
Expected: Test Suite passed. (If `iPhone 16` is unavailable, run `xcrun simctl list devices available | grep iPhone` and substitute a name.)

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Network/BackendConfig.swift \
        controller-ios/ControllerApp/ControllerAppTests/BackendConfigClientIdTests.swift
git commit -m "feat(ios): add clientId to BackendConfig (defaults to device name)"
```

> **Note for next tasks:** `BackendConfig.loadFromUserDefaults` now **requires** `defaultClientId:`. RootView (Task 8) supplies `UIDevice.current.name`. The project will not build until Task 8 updates those call sites — Tasks 6 and 7 only touch files that don't call the loader, so build them with `build-for-testing` against their own test targets if needed, or proceed straight through to Task 8 before a full build.

---

## Task 6: iOS BackendClient — X-Client-Id + new endpoints

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift`
- Test: `controller-ios/ControllerApp/ControllerAppTests/BackendClientHeaderTests.swift` (extend)

- [ ] **Step 1: Add a failing header test**

Append inside `BackendClientHeaderTests` (before the closing brace):

```swift
    func testClientIdHeaderStamped() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HeaderRecordingURLProtocol.self]
        let session = URLSession(configuration: config)
        let client = BackendClient(
            baseURL: URL(string: "http://localhost:8080")!,
            deviceName: nil,
            clientId: "uuid-9",
            session: session
        )
        _ = try? await client.fetchStatus()
        XCTAssertEqual(
            HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Client-Id"),
            "uuid-9"
        )
    }
```

- [ ] **Step 2: Run to verify it fails**

Run (build): `xcodebuild build-for-testing -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -15`
Expected: compile error — `clientId:` initializer arg missing.

- [ ] **Step 3: Add clientId + endpoints to BackendClient**

In `BackendClient.swift`, add a stored property and init param. Change the stored vars and `init`:

```swift
    private var baseURL: URL
    private var deviceName: String?
    private var clientId: String?
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL, deviceName: String? = nil, clientId: String? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.deviceName = deviceName
        self.clientId = clientId
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    func updateClientId(_ id: String?) {
        clientId = id
    }
```

Update `applyDeviceHeader` to also stamp the client id:

```swift
    private func applyDeviceHeader(_ req: inout URLRequest) {
        if let clientId {
            req.setValue(clientId, forHTTPHeaderField: "X-Client-Id")
        }
        if let name = deviceName {
            req.setValue(name, forHTTPHeaderField: "X-Device-Name")
        }
    }
```

Add the new models at the top of the file (after `BackendDevice`):

```swift
struct BackendDevice: Codable, Sendable {
    let udid: String
    let name: String
    let boundClientId: String?

    enum CodingKeys: String, CodingKey {
        case udid, name
        case boundClientId = "bound_client_id"
    }
}

struct BackendLeader: Codable, Sendable, Identifiable {
    let clientId: String
    let name: String
    let state: String
    var id: String { clientId }

    enum CodingKeys: String, CodingKey {
        case clientId = "client_id"
        case name, state
    }
}
```

(Replace the existing `BackendDevice` struct with the version above — it adds `boundClientId`.)

Add the endpoint methods (after `fetchDevices()`):

```swift
    private struct BindBody: Encodable { let clientId: String; let udid: String
        enum CodingKeys: String, CodingKey { case clientId = "client_id"; case udid } }
    private struct FollowBody: Encodable { let followerClientId: String; let leaderClientId: String
        enum CodingKeys: String, CodingKey { case followerClientId = "follower_client_id"; case leaderClientId = "leader_client_id" } }
    private struct UnfollowBody: Encodable { let clientId: String
        enum CodingKeys: String, CodingKey { case clientId = "client_id" } }
    private struct LeadersResponse: Decodable { let clients: [BackendLeader] }

    func fetchLeaders() async throws -> [BackendLeader] {
        try await getJSON("/api/clients", as: LeadersResponse.self).clients
    }

    /// Binds this UUID to a device. Throws BackendError.duplicateClientId on 409.
    func bind(clientId: String, udid: String) async throws {
        _ = try await postJSON("/api/bind", body: BindBody(clientId: clientId, udid: udid), decode: Ok.self)
    }

    func follow(leaderClientId: String) async throws {
        guard let mine = clientId else { throw BackendError.routing("no client id set") }
        _ = try await postJSON("/api/follow",
                               body: FollowBody(followerClientId: mine, leaderClientId: leaderClientId),
                               decode: Ok.self)
    }

    func unfollow() async throws {
        guard let mine = clientId else { return }
        _ = try await postJSON("/api/unfollow", body: UnfollowBody(clientId: mine), decode: Ok.self)
    }
```

Add a `duplicateClientId` case to `BackendError` (file `Models/BackendError.swift`) and map 409 on `/api/bind`. In `BackendError.swift`, add the case alongside the others:

```swift
    case duplicateClientId(String)
```

In `checkOk(...)`, change the `case 409:` branch to special-case bind:

```swift
        case 409:
            let msg = (detail as? String) ?? "conflict"
            if isBind { throw BackendError.duplicateClientId(msg) }
            throw isStart ? BackendError.sessionAlreadyActive(msg) : .sessionNotActive(msg)
```

Thread an `isBind` flag: change `checkOk(_:data:isStart:)` to `checkOk(_:data:isStart:isBind:)` with `isBind: Bool = false`, and in `postJSON` pass `isBind: path.hasSuffix("/bind")`:

```swift
    private func postJSON<Body: Encodable, T: Decodable>(_ path: String, body: Body, decode: T.Type) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(body)
        applyDeviceHeader(&req)
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: path.hasSuffix("/session"), isBind: path.hasSuffix("/bind"))
        return try decoder.decode(T.self, from: data)
    }
```

Update the other `checkOk(...)` callers (`getJSON`, `postEmpty`, `search`) to pass `isBind: false` (or rely on the default) and the `checkOk` signature:

```swift
    private func checkOk(_ response: URLResponse, data: Data, isStart: Bool, isBind: Bool = false) throws {
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `xcodebuild test -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ControllerAppTests/BackendClientHeaderTests 2>&1 | tail -20`
Expected: passes (will fully link only after Task 8 fixes RootView call sites; if the scheme fails to build due to RootView, proceed to Task 8 then re-run).

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Network/BackendClient.swift \
        controller-ios/ControllerApp/ControllerApp/Models/BackendError.swift \
        controller-ios/ControllerApp/ControllerAppTests/BackendClientHeaderTests.swift
git commit -m "feat(ios): BackendClient sends X-Client-Id; add bind/leaders/follow"
```

---

## Task 7: iOS LiveStatusSubscriber `?client=` + SessionState/StatusSnapshot

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Network/LiveStatusSubscriber.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp/Models/SessionState.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp/Models/StatusSnapshot.swift`
- Test: `controller-ios/ControllerApp/ControllerAppTests/LiveStatusSubscriberTests.swift` (extend)

- [ ] **Step 1: Write the failing test**

Append to `LiveStatusSubscriberTests.swift` (inside the test class):

```swift
    func testWebSocketURLEncodesClientQuery() {
        let url = LiveStatusSubscriber.webSocketURL(
            from: URL(string: "http://10.0.0.1:8080/")!,
            clientId: "uuid 7"
        )
        XCTAssertEqual(url.absoluteString, "ws://10.0.0.1:8080/ws/live?client=uuid%207")
    }

    func testWebSocketURLNoClient() {
        let url = LiveStatusSubscriber.webSocketURL(
            from: URL(string: "http://10.0.0.1:8080/")!,
            clientId: nil
        )
        XCTAssertEqual(url.absoluteString, "ws://10.0.0.1:8080/ws/live")
    }
```

- [ ] **Step 2: Run to verify it fails**

Run (build): `xcodebuild build-for-testing -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -15`
Expected: compile error — `webSocketURL(from:clientId:)` missing.

- [ ] **Step 3: Switch subscriber to clientId**

In `LiveStatusSubscriber.swift`, change `start` and `webSocketURL` to use `clientId` and the `client` query key:

```swift
    func start(baseURL: URL, clientId: String?) -> AsyncStream<StatusSnapshot> {
        cancel()

        let wsURL = Self.webSocketURL(from: baseURL, clientId: clientId)
        let (stream, cont) = AsyncStream<StatusSnapshot>.makeStream()
        continuation = cont
        // ... rest of method unchanged ...
```

```swift
    static func webSocketURL(from baseURL: URL, clientId: String?) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.scheme = (baseURL.scheme == "https") ? "wss" : "ws"
        components.path = "/ws/live"
        if let clientId {
            components.queryItems = [URLQueryItem(name: "client", value: clientId)]
        } else {
            components.query = nil
        }
        return components.url!
    }
```

In `Models/SessionState.swift`, add `following`:

```swift
    case idle, starting, running, paused, stopping, reconnecting, error
    case following
    case unknown
```

In `Models/StatusSnapshot.swift`, add the optional field + key:

```swift
    let stepCompanions: [StepCompanionInfo]
    let followingLeader: String?
```
and in `CodingKeys`:
```swift
        case stepCompanions = "step_companions"
        case followingLeader = "following_leader"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `xcodebuild test -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ControllerAppTests/LiveStatusSubscriberTests 2>&1 | tail -20`
Expected: passes (full link may require Task 8; if RootView blocks the build, proceed and re-run after Task 8).

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Network/LiveStatusSubscriber.swift \
        controller-ios/ControllerApp/ControllerApp/Models/SessionState.swift \
        controller-ios/ControllerApp/ControllerApp/Models/StatusSnapshot.swift \
        controller-ios/ControllerApp/ControllerAppTests/LiveStatusSubscriberTests.swift
git commit -m "feat(ios): subscribe /ws/live by client id; add following state"
```

---

## Task 8: Wire clientId through RootView + SessionStore watch override

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Store/SessionStore.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/RootView.swift`

- [ ] **Step 1: Add `watchingLeaderId` to SessionStore**

In `SessionStore.swift`, add near `isConnected`:

```swift
    // When set, the Map view watches a leader's live stream instead of this
    // device's own session (view-only follow). RootView repoints the subscriber.
    @Published var watchingLeaderId: String? = nil
```

- [ ] **Step 2: Update RootView to use clientId and the watch override**

Replace `RootView.swift` with:

```swift
import SwiftUI
import UIKit

struct RootView: View {
    @StateObject private var store = SessionStore()
    @EnvironmentObject var health: HealthStore
    @State private var config: BackendConfig
    @State private var client: BackendClient
    @State private var subscriber = LiveStatusSubscriber()

    init() {
        let cfg = BackendConfig.loadFromUserDefaults(defaultClientId: UIDevice.current.name)
        _config = State(initialValue: cfg)
        _client = State(initialValue: BackendClient(
            baseURL: cfg.baseURL, deviceName: cfg.deviceName, clientId: cfg.clientId))
    }

    private struct ConnectionKey: Equatable {
        let url: URL
        let clientId: String
        let watching: String?
        let connected: Bool
    }

    var body: some View {
        TabView {
            MapTabView(client: client)
                .environmentObject(store)
                .tabItem { Label("Map", systemImage: "map") }

            HealthTabView(health: health)
                .tabItem { Label("Health", systemImage: "heart.text.square") }

            SettingsTabView(config: $config, client: client)
                .environmentObject(store)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task(id: ConnectionKey(url: config.baseURL, clientId: config.clientId,
                                watching: store.watchingLeaderId, connected: store.isConnected)) {
            await subscriber.cancel()
            health.disconnect()
            await client.updateBaseURL(config.baseURL)
            await client.updateClientId(config.clientId)
            await client.updateDeviceName(config.deviceName)
            guard store.isConnected else { return }
            health.connect(baseURL: config.baseURL, label: config.clientId)
            let effective = store.watchingLeaderId ?? config.clientId
            let stream = await subscriber.start(baseURL: config.baseURL, clientId: effective)
            for await snap in stream {
                store.apply(snapshot: snap)
            }
        }
    }
}
```

- [ ] **Step 3: Full build to verify everything links**

Run: `xcodebuild build -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -15`
Expected: BUILD SUCCEEDED.

- [ ] **Step 4: Run the iOS test suites touched so far**

Run: `xcodebuild test -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ControllerAppTests/BackendConfigClientIdTests -only-testing:ControllerAppTests/BackendClientHeaderTests -only-testing:ControllerAppTests/LiveStatusSubscriberTests 2>&1 | tail -20`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Store/SessionStore.swift \
        controller-ios/ControllerApp/ControllerApp/Views/RootView.swift
git commit -m "feat(ios): route by clientId; repoint subscriber for watch-only follow"
```

---

## Task 9: Settings — Identity section + bind-on-save validation

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/SettingsScreen.swift`

- [ ] **Step 1: Add the Identity section and validation logic**

In `SettingsScreen.swift`, add state vars near the top of the struct:

```swift
    @State private var clientIdText: String = ""
    @State private var savingIdentity: Bool = false
    @State private var identityError: String? = nil
```

Add an "Identity" section to the `Form`, immediately after the `Section("Backend")` block:

```swift
                Section("Identity (UUID)") {
                    TextField("This iPhone's UUID", text: $clientIdText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(savingIdentity ? "Validating…" : "Save UUID") {
                        urlFocused = false
                        Task { await saveIdentity() }
                    }
                    .disabled(savingIdentity || clientIdText.trimmingCharacters(in: .whitespaces).isEmpty)
                    if let identityError {
                        Text(identityError).font(.caption).foregroundStyle(.red)
                    } else {
                        Text("Default is your device name. Must be unique across devices.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
```

Update `.onAppear` to seed the field:

```swift
            .onAppear {
                urlText = config.baseURL.absoluteString
                clientIdText = config.clientId
            }
```

Add the validation method (sibling of `save()`):

```swift
    private func saveIdentity() async {
        let newId = clientIdText.trimmingCharacters(in: .whitespaces)
        guard !newId.isEmpty else { return }
        savingIdentity = true
        identityError = nil
        defer { savingIdentity = false }

        // Determine which connected device this UUID should bind to.
        let found = (try? await client.fetchDevices()) ?? []
        let targetUdid: String?
        if found.count == 1 {
            targetUdid = found[0].udid
        } else {
            targetUdid = found.first(where: { $0.name == config.deviceName })?.udid
        }
        guard let udid = targetUdid else {
            identityError = "Pick this iPhone in the Device list below first."
            return
        }

        do {
            try await client.bind(clientId: newId, udid: udid)
            config.clientId = newId
            config.save()
            await client.updateClientId(newId)
            probeMessage = .ok("UUID saved ✓")
        } catch BackendError.duplicateClientId {
            identityError = "That UUID is already used by another device — pick a different one."
        } catch {
            identityError = "Couldn't validate UUID — check the backend connection."
        }
    }
```

- [ ] **Step 2: Build**

Run: `xcodebuild build -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -15`
Expected: BUILD SUCCEEDED.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/SettingsScreen.swift
git commit -m "feat(ios): Settings UUID field with duplicate-check on save"
```

---

## Task 10: Map — Follow-leader sheet + stop control

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Views/FollowSheet.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/MapTabView.swift`

- [ ] **Step 1: Create the Follow sheet**

```swift
// Views/FollowSheet.swift
import SwiftUI

struct FollowSheet: View {
    let client: BackendClient
    @EnvironmentObject var store: SessionStore
    @Environment(\.dismiss) private var dismiss

    @State private var leaders: [BackendLeader] = []
    @State private var loading = false
    @State private var pasteText = ""
    @State private var selectedId: String? = nil
    @State private var mirrorGPS = false
    @State private var errorText: String? = nil
    @State private var working = false

    private var chosenLeaderId: String? {
        let pasted = pasteText.trimmingCharacters(in: .whitespaces)
        return pasted.isEmpty ? selectedId : pasted
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Active leaders") {
                    if loading {
                        HStack { ProgressView(); Text("Loading…") }
                    } else if leaders.isEmpty {
                        Text("No active leaders found.").font(.caption).foregroundStyle(.secondary)
                    } else {
                        Picker("Leader", selection: $selectedId) {
                            Text("None").tag(String?.none)
                            ForEach(leaders) { l in
                                Text("\(l.name) · \(l.state)").tag(Optional(l.clientId))
                            }
                        }
                    }
                    Button("Refresh") { Task { await load() } }.disabled(loading)
                }

                Section("Or paste a UUID") {
                    TextField("leader UUID", text: $pasteText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    Toggle("Mirror onto this phone (GPS)", isOn: $mirrorGPS)
                    Text(mirrorGPS
                         ? "This phone's GPS will track the leader's route."
                         : "Watch the leader on the map only; this phone is unaffected.")
                        .font(.caption).foregroundStyle(.secondary)
                }

                if let errorText {
                    Section { Text(errorText).font(.caption).foregroundStyle(.red) }
                }

                Section {
                    Button(working ? "Starting…" : "Start following") {
                        Task { await startFollowing() }
                    }
                    .disabled(working || chosenLeaderId == nil)
                }
            }
            .navigationTitle("Follow a leader")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task { await load() }
        }
    }

    private func load() async {
        loading = true; defer { loading = false }
        leaders = (try? await client.fetchLeaders()) ?? []
    }

    private func startFollowing() async {
        guard let leaderId = chosenLeaderId else { return }
        working = true; errorText = nil; defer { working = false }
        if mirrorGPS {
            do {
                try await client.follow(leaderClientId: leaderId)
                store.watchingLeaderId = nil   // own session now shows mirrored track
                dismiss()
            } catch {
                errorText = "Couldn't start GPS follow — check the leader UUID."
            }
        } else {
            store.watchingLeaderId = leaderId  // RootView repoints the subscriber
            dismiss()
        }
    }
}
```

- [ ] **Step 2: Add a Follow button + Stop control to MapTabView**

In `MapTabView.swift`, add a state var and present the sheet. Replace the `struct MapTabView` body's `.toolbar { ... }` and add follow state:

```swift
struct MapTabView: View {
    @EnvironmentObject var store: SessionStore
    let client: BackendClient
    @State private var showFollow = false

    private var isFollowing: Bool {
        store.watchingLeaderId != nil || store.state == .following
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(client: client) { coord in
                    store.setPin(at: coord)
                    store.focusCamera(on: coord)
                }
                .padding(.horizontal)
                .padding(.top, 8)

                if isFollowing {
                    HStack {
                        Image(systemName: "dot.radiowaves.left.and.right")
                        Text(store.watchingLeaderId != nil ? "Watching a leader" : "Mirroring a leader")
                            .font(.caption)
                        Spacer()
                        Button("Stop") { Task { await stopFollowing() } }
                            .font(.caption).tint(.red)
                    }
                    .padding(.horizontal).padding(.vertical, 6)
                    .background(.thinMaterial)
                }

                MapScreen()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                VStack(spacing: 10) {
                    SessionControls(client: client)
                    StepCompanionsPanel()
                }
                .padding(.horizontal)
                .padding(.vertical, 10)
            }
            .navigationTitle("Trail Controller")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    MapStatePill(state: store.state)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showFollow = true } label: {
                        Label("Follow", systemImage: "person.2.wave.2")
                    }
                }
            }
            .sheet(isPresented: $showFollow) {
                FollowSheet(client: client).environmentObject(store)
            }
        }
    }

    private func stopFollowing() async {
        if store.watchingLeaderId != nil {
            store.watchingLeaderId = nil
        } else {
            try? await client.unfollow()
        }
    }
}
```

In `MapStatePill`'s `color` switch, add a `following` case:

```swift
        case .following:    return .teal
```

- [ ] **Step 3: Build**

Run: `xcodebuild build -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator' 2>&1 | tail -15`
Expected: BUILD SUCCEEDED.

> If `FollowSheet.swift` is not picked up by the build, add it to the `ControllerApp` target in `project.pbxproj` (Xcode adds new files automatically when created via the IDE; for CLI-created files confirm membership with `xcodebuild ... 2>&1 | grep -i FollowSheet`). If unresolved, add a `// MARK:` file reference using the same group as `MapTabView.swift`.

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/FollowSheet.swift \
        controller-ios/ControllerApp/ControllerApp/Views/MapTabView.swift \
        controller-ios/ControllerApp/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(ios): Map follow-leader sheet (watch-only or GPS mirror)"
```

---

## Task 11: README — UUID identity & following

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a section**

Add under the existing multi-iPhone section in `README.md`:

```markdown
## Per-iPhone UUID identity & following a leader

Each TrailController iPhone carries a **UUID** (Settings → Identity). It defaults
to the device name and can be edited to any unique string. The app sends it as
`X-Client-Id` on every request; the backend binds the UUID to the connected
device and routes that iPhone's session by it, so two phones never share a
session.

- **Uniqueness:** on Save the app calls `POST /api/bind`; if another device
  already holds that UUID the backend returns `409` and the change is rejected.
- **Single device:** the UUID auto-binds — no device picking needed.
- **Multiple devices:** pick this iPhone in Settings → Device, then save the UUID.

**Following a leader** (Map → Follow button):
- *Watch on map only* — your map shows the leader's live position; your phone is
  untouched.
- *Mirror onto this phone (GPS)* — your phone's spoofed GPS tracks the leader's
  route (`POST /api/follow`). Tap **Stop** to end (`POST /api/unfollow`).

```bash
curl -H "X-Client-Id: my-uuid" http://127.0.0.1:8080/api/status
curl http://127.0.0.1:8080/api/clients   # active leaders to follow
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document UUID identity and follow-a-leader"
```

---

## Self-Review Notes

- **Spec coverage:** Bug fix → Tasks 1,3,4 (client-id routing → distinct sessions). Feature 1 (UUID, default=name, unique) → Tasks 1,3,5,9. Feature 2 (follow, per-follow choice) → Tasks 2,3,10 (+ watch-only via Task 8 subscriber repoint). "Keep both" fallback preserved in Tasks 3,4. Docs → Task 11.
- **Type consistency:** `bind`/`follow`/`unfollow`/`fetchLeaders` signatures match between BackendClient (Task 6) and callers (Tasks 9,10). `BackendLeader.clientId`, `BackendDevice.boundClientId`, `SessionState.following`, `StatusSnapshot.followingLeader`, registry `resolve_client`/`auto_bind_single`/`client_for`/`list_clients`, controller `follow(leader, label)`/`unfollow()` are used consistently.
- **Build ordering caveat:** Task 5 changes `loadFromUserDefaults` to require `defaultClientId:`; the project only fully builds again after Task 8. Tasks 6–7 verify via their unit test targets / `build-for-testing` and are fully validated by the Task 8 full build. This is called out inline in each affected task.
- **No main.py change:** bindings are dynamic; `--dev-no-device` single-device path auto-binds.
- **Simulator name:** commands use `iPhone 16`; substitute an available one via `xcrun simctl list devices available`.
```
