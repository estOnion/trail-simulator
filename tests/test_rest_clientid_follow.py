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
