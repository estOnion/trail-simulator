from __future__ import annotations

import asyncio
import dataclasses

import pytest

import trail_simulator.session.controller as controller_mod
from trail_simulator.session.controller import SessionController, SessionState
from trail_simulator.session.store import Store


class DisconnectingDevice:
    """set() works once (the initial teleport), then the transport dies with
    the errno-49 OSError a vanished Wi-Fi tunnel produces."""

    def __init__(self):
        self.set_calls = 0

    async def open(self):
        pass

    async def set(self, lat, lon):
        self.set_calls += 1
        if self.set_calls > 1:
            raise OSError(49, "Can't assign requested address")

    async def clear(self):
        pass

    async def reachable(self):
        return False  # keep auto-resume polling so tests can observe the task


def _patch_route(monkeypatch, polyline):
    async def fake_route(a_lat, a_lon, b_lat, b_lon):
        return list(polyline)
    monkeypatch.setattr(controller_mod, "fetch_walking_route", fake_route)


@pytest.mark.asyncio
async def test_transport_oserror_mid_session_enters_device_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        controller_mod,
        "SETTINGS",
        dataclasses.replace(controller_mod.SETTINGS, tick_hz=50.0),
    )
    _patch_route(monkeypatch, [(0.0, 0.0), (0.0, 0.001)])
    dev = DisconnectingDevice()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await asyncio.wait_for(c._task, timeout=2.0)

    # An OSError from the device layer is a disconnect, not "unexpected:" —
    # the "device:" prefix is what gates the auto-resume task. Once that task
    # gets a turn on the loop it flips error → reconnecting.
    assert c._last_error is not None and c._last_error.startswith("device:")
    assert c._reconnect_task is not None and not c._reconnect_task.done()
    assert c._state in (SessionState.error, SessionState.reconnecting)

    await c.stop()  # cancels the pending auto-resume


@pytest.mark.asyncio
async def test_transport_oserror_on_open_enters_device_error(tmp_path, monkeypatch):
    class DeadOnOpen(DisconnectingDevice):
        async def open(self):
            raise OSError(49, "Can't assign requested address")

    _patch_route(monkeypatch, [(0.0, 0.0), (0.0, 0.001)])
    dev = DeadOnOpen()
    c = SessionController(dev, Store(tmp_path / "t.db"))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await asyncio.wait_for(c._task, timeout=2.0)

    assert c._last_error is not None and c._last_error.startswith("device:")
    assert c._reconnect_task is not None and not c._reconnect_task.done()
    assert c._state in (SessionState.error, SessionState.reconnecting)

    await c.stop()
