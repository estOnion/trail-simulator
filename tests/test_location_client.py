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


@pytest.mark.asyncio
async def test_set_counts_success(monkeypatch):
    client = LocationClient()

    class OkLoc:
        async def set(self, lat, lon):
            return None

    client._loc = OkLoc()
    await client.set(25.0, 121.0)
    assert client._set_total == 1
    assert client._set_fail == 0


@pytest.mark.asyncio
async def test_set_counts_failure_then_recovers(monkeypatch):
    monkeypatch.setattr(
        location,
        "SETTINGS",
        SimpleNamespace(device_set_timeout_s=0.05, reconnect_max_backoff_s=0.01),
    )
    client = LocationClient()

    class FlakyLoc:
        def __init__(self):
            self.calls = 0

        async def set(self, lat, lon):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("stall")
            return None

    flaky = FlakyLoc()
    client._loc = flaky

    async def fake_reconnect():
        # leave the same flaky loc in place; second call succeeds
        return None

    monkeypatch.setattr(client, "_reconnect", fake_reconnect)

    await client.set(25.0, 121.0)
    assert client._set_total == 1
    assert client._set_fail == 1  # first attempt failed even though retry recovered
    assert flaky.calls == 2  # first attempt raised, retry after reconnect ran


@pytest.mark.asyncio
async def test_reliability_logged_every_60_with_rate(monkeypatch, caplog):
    client = LocationClient()

    class OkLoc:
        async def set(self, lat, lon):
            return None

    client._loc = OkLoc()
    # Seed to 59 so the 60th call hits the `% 60 == 0` boundary; pretend 1 of
    # the prior calls failed so the logged rate is a non-trivial value.
    client._set_total = 59
    client._set_fail = 1

    with caplog.at_level("INFO", logger="trail_simulator.device.location"):
        await client.set(25.0, 121.0)

    msgs = [r.getMessage() for r in caplog.records]
    assert any("location.set reliability: 59/60 ok (98.33%)" in m for m in msgs)
