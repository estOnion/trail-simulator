# tests/test_multidevice_isolation.py
"""Regression test for the two-phone override bug: with dynamic discovery,
two phones bind to distinct devices and neither can hijack the other's."""
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


def _app(tmp_path):
    registry = DeviceRegistry()  # empty at launch — devices arrive via discovery

    async def discover():
        return [("UDID-A", "Jack", "ios"), ("UDID-B", "Anna", "ios")]

    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=Store(tmp_path / "s.db"))
    app = FastAPI()
    app.include_router(build_router(manager, registry, discover=discover), prefix="/api")
    return TestClient(app)


def test_two_phones_bind_to_distinct_devices_and_route_independently(tmp_path):
    client = _app(tmp_path)
    # Dynamic discovery registers both phones on first device list fetch.
    assert client.get("/api/devices").status_code == 200

    assert client.post("/api/bind", json={"client_id": "jack", "udid": "UDID-A"}).status_code == 200
    assert client.post("/api/bind", json={"client_id": "anna", "udid": "UDID-B"}).status_code == 200

    # Each phone's status resolves to its own session — independently.
    assert client.get("/api/status", headers={"X-Client-Id": "jack"}).status_code == 200
    assert client.get("/api/status", headers={"X-Client-Id": "anna"}).status_code == 200


def test_phone_cannot_hijack_anothers_device(tmp_path):
    client = _app(tmp_path)
    client.get("/api/devices")
    assert client.post("/api/bind", json={"client_id": "jack", "udid": "UDID-A"}).status_code == 200
    # Anna tries to claim Jack's device — must be refused, not silently stolen.
    assert client.post("/api/bind", json={"client_id": "anna", "udid": "UDID-A"}).status_code == 409
    assert client.get("/api/status", headers={"X-Client-Id": "jack"}).status_code == 200
