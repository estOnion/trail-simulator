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

    # FastAPI's TestClient raises WebSocketDisconnect when server closes.
    try:
        with client.websocket_connect("/ws/live?device=Ghost") as ws:
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
