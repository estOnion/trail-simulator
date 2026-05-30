from __future__ import annotations

import pytest

import trail_simulator.session.controller as ctrl_mod
from trail_simulator.session.controller import SessionController
from trail_simulator.session.store import Store
from trail_simulator.device.multi_location import MultiLocationClient
from trail_simulator.device.injector import LocationInjector


class _FakeDevice:
    def __init__(self):
        self.reach_calls = 0
        self.opened = False

    async def open(self):
        self.opened = True

    async def set(self, lat, lon):
        pass

    async def clear(self):
        pass

    async def reachable(self):
        self.reach_calls += 1
        return True


@pytest.mark.asyncio
async def test_auto_resume_polls_device_reachable_not_tunneld(tmp_path, monkeypatch):
    # If the controller still polled tunneld, this would break the loop without
    # ever consulting the device — leaving reach_calls at 0.
    import trail_simulator.device.tunneld as tunneld
    monkeypatch.setattr(tunneld, "tunneld_reachable", lambda: True)

    async def no_sleep(_s):
        pass

    monkeypatch.setattr(ctrl_mod.asyncio, "sleep", no_sleep)

    dev = _FakeDevice()
    c = SessionController(dev, Store(path=tmp_path / "r.db"))
    c._last_start_params = {
        "start_lat": 25.0,
        "start_lon": 121.0,
        "destinations": [(25.001, 121.001)],
        "speed_kmh": 5.0,
        "loop": False,
    }
    started = {"n": 0}

    async def fake_start(*a, **k):
        started["n"] += 1

    monkeypatch.setattr(c, "start", fake_start)

    await c._auto_resume()

    assert dev.reach_calls >= 1   # the device was polled
    assert started["n"] == 1      # resume proceeded once reachable


def test_multilocation_satisfies_injector_protocol():
    m = MultiLocationClient(["A"])
    assert isinstance(m, LocationInjector)


@pytest.mark.asyncio
async def test_multilocation_reachable_is_any():
    m = MultiLocationClient(["A", "B"])

    class _C:
        def __init__(self, v):
            self.v = v

        async def reachable(self):
            return self.v

    m._clients = [_C(False), _C(True)]
    assert await m.reachable() is True
    m._clients = [_C(False), _C(False)]
    assert await m.reachable() is False
