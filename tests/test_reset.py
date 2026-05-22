from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trail_simulator.api.rest import build_router
from trail_simulator.session.controller import SessionController, SessionState
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


@pytest.mark.asyncio
async def test_reset_device_when_idle_clears(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    c._current = (1.0, 2.0)
    c._current_leg_target = (3.0, 4.0)

    await c.reset_device()

    assert dev.clear_count == 1
    assert c._current is None
    assert c._current_leg_target is None
    assert c._state == SessionState.idle


@pytest.mark.asyncio
async def test_reset_device_when_active_raises(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    c._state = SessionState.running

    with pytest.raises(RuntimeError):
        await c.reset_device()
    assert dev.clear_count == 0


def test_reset_endpoint_ok(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    app = FastAPI()
    app.include_router(build_router(c), prefix="/api")
    client = TestClient(app)

    r = client.post("/api/reset")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert dev.clear_count == 1


def test_reset_endpoint_conflict_when_active(tmp_path):
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))
    c._state = SessionState.running
    app = FastAPI()
    app.include_router(build_router(c), prefix="/api")
    client = TestClient(app)

    r = client.post("/api/reset")
    assert r.status_code == 409
