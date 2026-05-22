from __future__ import annotations

import pytest

from trail_simulator.device.location import LocationClient


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
