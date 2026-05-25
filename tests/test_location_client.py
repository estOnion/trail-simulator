from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from trail_simulator.device import location
from trail_simulator.device.location import DeviceUnavailable, LocationClient


@pytest.mark.asyncio
async def test_open_is_noop_when_already_connected(monkeypatch):
    client = LocationClient()
    calls = {"n": 0}

    async def fake_connect():
        calls["n"] += 1
        client._loc = object()  # simulate an open session

    monkeypatch.setattr(client, "_connect", fake_connect)

    await client.open()          # first open -> connects
    await client.open()          # second open -> must be a no-op
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_open_connects_when_not_connected(monkeypatch):
    client = LocationClient()
    calls = {"n": 0}

    async def fake_connect():
        calls["n"] += 1
        client._loc = object()

    monkeypatch.setattr(client, "_connect", fake_connect)
    await client.open()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_set_does_not_hang_when_device_stalls(monkeypatch):
    # DTX simulate_location awaits a device reply with no timeout. If the
    # device/tunnel stalls, set() must surface an error (-> reconnect) rather
    # than block the tick loop forever.
    monkeypatch.setattr(
        location,
        "SETTINGS",
        SimpleNamespace(device_set_timeout_s=0.05, reconnect_max_backoff_s=0.01),
    )
    client = LocationClient()

    class HangingLoc:
        async def set(self, lat, lon):
            await asyncio.Event().wait()  # never returns — device went silent

    client._loc = HangingLoc()

    reconnects = {"n": 0}

    async def fake_reconnect():
        reconnects["n"] += 1
        client._loc = None
        raise DeviceUnavailable("dead")

    monkeypatch.setattr(client, "_reconnect", fake_reconnect)

    # Without a timeout this awaits forever; the outer wait_for would raise
    # TimeoutError instead of the expected DeviceUnavailable.
    with pytest.raises(DeviceUnavailable):
        await asyncio.wait_for(client.set(25.0, 121.0), timeout=1.0)
    assert reconnects["n"] == 1
