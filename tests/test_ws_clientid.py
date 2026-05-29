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
    connected = False
    try:
        with client.websocket_connect("/ws/live?client=ghost") as ws:
            connected = True
            ws.receive_text()
    except Exception:
        pass
    assert not connected, "expected connection to be rejected"
