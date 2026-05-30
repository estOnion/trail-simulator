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


def test_get_devices_runs_on_demand_discovery(tmp_path):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()  # starts empty — nothing registered at launch

    async def discover():
        return [("UDID-A", "Jack", "ios"), ("SER-1", "Pixel", "android")]

    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_router(manager, registry, discover=discover), prefix="/api")
    body = TestClient(app).get("/api/devices").json()
    by_name = {d["name"]: d for d in body["devices"]}
    assert by_name["Jack"]["type"] == "ios"
    assert by_name["Pixel"]["type"] == "android"


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
    client = _make_app(tmp_path, [("UDID-A", "Jack"), ("UDID-B", "Spare")])
    resp = client.get("/api/status", headers={"X-Device-Name": "Ghost"})
    assert resp.status_code == 404


def test_status_unknown_name_falls_back_to_single_device(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack")])
    resp = client.get("/api/status", headers={"X-Device-Name": "Ghost"})
    assert resp.status_code == 200


def test_bind_409_when_device_owned_by_other_client(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack")])
    assert client.post("/api/bind", json={"client_id": "jack", "udid": "UDID-A"}).status_code == 200
    resp = client.post("/api/bind", json={"client_id": "anna", "udid": "UDID-A"})
    assert resp.status_code == 409
    # The first binding is intact: Jack still routes to the device.
    assert client.get("/api/status", headers={"X-Client-Id": "jack"}).status_code == 200


def test_rebind_takes_over_device(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack")])
    assert client.post("/api/bind", json={"client_id": "jack", "udid": "UDID-A"}).status_code == 200
    # Operator takeover: anna reclaims the device that jack held.
    assert client.post("/api/rebind", json={"client_id": "anna", "udid": "UDID-A"}).status_code == 200
    assert client.get("/api/status", headers={"X-Client-Id": "anna"}).status_code == 200
    # Jack is now unbound — with two? no, single device, so jack auto-binds elsewhere is N/A.
    assert client.get("/api/clients").json()["clients"] == [
        {"client_id": "anna", "name": "Jack", "state": "idle"}
    ]


def test_rebind_unknown_udid_404(tmp_path):
    client = _make_app(tmp_path, [("UDID-A", "Jack")])
    assert client.post("/api/rebind", json={"client_id": "anna", "udid": "GHOST"}).status_code == 404


def test_devices_includes_type(tmp_path):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack iPhone")
    registry.register(udid="SER-1", name="Pixel 7", device_type="android")
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_router(manager, registry), prefix="/api")
    body = TestClient(app).get("/api/devices").json()
    by_name = {d["name"]: d for d in body["devices"]}
    assert by_name["Jack iPhone"]["type"] == "ios"
    assert by_name["Pixel 7"]["type"] == "android"
