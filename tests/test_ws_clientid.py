# tests/test_ws_clientid.py
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trail_simulator.api.ws import _reject_reason, build_ws_router
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


def test_ws_live_auto_binds_client_named_after_its_device(tmp_path):
    # Two devices connected, so the single-device rule cannot apply; the
    # client id matches a device name, which is enough to route it.
    client = _app(tmp_path)
    with client.websocket_connect("/ws/live?client=Spare") as ws:
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


def test_ws_live_rejection_logs_reason(tmp_path, caplog):
    client = _app(tmp_path)
    with caplog.at_level(logging.WARNING, logger="trail_simulator.api.ws"):
        try:
            with client.websocket_connect("/ws/live?client=ghost"):
                pass
        except Exception:
            pass
    assert "'ghost' does not match any device name" in caplog.text
    assert "'Jack'" in caplog.text and "'Spare'" in caplog.text


def test_reject_reason_no_devices():
    registry = DeviceRegistry()
    assert "no devices registered" in _reject_reason(registry, "Anna", None)


def test_reject_reason_unmatched_client_lists_device_names():
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    registry.register(udid="UDID-B", name="Annn's iPhone")
    reason = _reject_reason(registry, "Anna", None)
    assert "'Anna' does not match any device name" in reason
    assert "Jack" in reason and "Annn's iPhone" in reason


def test_reject_reason_device_held_by_other_client():
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    registry.bind("uuid-1", "UDID-A")
    reason = _reject_reason(registry, "Anna", None)
    assert "'Jack' is already bound to client 'uuid-1'" in reason


def test_reject_reason_unknown_device_param():
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    registry.register(udid="UDID-B", name="Spare")
    reason = _reject_reason(registry, None, "Ghost Phone")
    assert "unknown device 'Ghost Phone'" in reason
    assert "Jack" in reason and "Spare" in reason
