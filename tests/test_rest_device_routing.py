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
