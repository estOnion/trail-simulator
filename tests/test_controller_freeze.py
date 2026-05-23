from __future__ import annotations

import asyncio

import pytest

import trail_simulator.session.controller as controller_mod
from trail_simulator.routing.osrm import RouteError
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


def _patch_route(monkeypatch, polyline):
    async def fake_route(a_lat, a_lon, b_lat, b_lon):
        return list(polyline)
    monkeypatch.setattr(controller_mod, "fetch_walking_route", fake_route)


@pytest.mark.asyncio
async def test_user_stop_does_not_clear_device(tmp_path, monkeypatch):
    # A long leg so the tick loop is still running when we stop.
    _patch_route(monkeypatch, [(0.0, 0.0), (0.0, 0.001)])
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await asyncio.sleep(0.05)        # let it teleport + enter the tick loop
    await c.stop()

    assert dev.clear_count == 0      # frozen — device NOT released
    assert c._state == SessionState.idle


@pytest.mark.asyncio
async def test_completion_does_not_clear_device(tmp_path, monkeypatch):
    # Degenerate route (start == dest) completes after one leg.
    _patch_route(monkeypatch, [(0.0, 0.0), (0.0, 0.0)])
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.0)], speed_kmh=4.0)
    await asyncio.wait_for(c._task, timeout=2.0)

    assert dev.clear_count == 0      # frozen at last destination
    assert c._state == SessionState.idle


@pytest.mark.asyncio
async def test_route_error_clears_device(tmp_path, monkeypatch):
    async def boom(a_lat, a_lon, b_lat, b_lon):
        raise RouteError("no route")
    monkeypatch.setattr(controller_mod, "fetch_walking_route", boom)
    dev = FakeDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await asyncio.wait_for(c._task, timeout=2.0)

    assert dev.clear_count == 1      # error path still releases
    assert c._state == SessionState.error
