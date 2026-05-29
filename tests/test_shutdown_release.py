from __future__ import annotations

from fastapi.testclient import TestClient

from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.main import build_app
from trail_simulator.session.controller import SessionController
from trail_simulator.session.manager import SessionManager
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
    registry = DeviceRegistry()
    registry.register(udid="UDID-TEST", name="Test iPhone")
    manager = SessionManager(device_factory=lambda u: dev, store=Store(tmp_path / "t.db"))
    manager._controllers["UDID-TEST"] = c
    app = build_app(manager, registry)

    # Entering/exiting the TestClient context triggers lifespan startup+shutdown.
    with TestClient(app):
        pass

    assert dev.clear_count == 1   # shutdown released the phone to real GPS
