from __future__ import annotations

import pytest

from trail_simulator.device.injector import DeviceUnavailable, LocationInjector
from trail_simulator.device.location import LocationClient
from trail_simulator.device import location as location_mod


def test_location_client_satisfies_injector_protocol():
    assert isinstance(LocationClient(), LocationInjector)


def test_device_unavailable_reexported_from_location():
    # Existing imports must keep working after the type moved to injector.
    assert location_mod.DeviceUnavailable is DeviceUnavailable


@pytest.mark.asyncio
async def test_location_client_reachable_true(monkeypatch):
    import trail_simulator.device.tunneld as tunneld
    monkeypatch.setattr(tunneld, "tunneld_reachable", lambda: True)
    assert await LocationClient().reachable() is True


@pytest.mark.asyncio
async def test_location_client_reachable_false(monkeypatch):
    import trail_simulator.device.tunneld as tunneld
    monkeypatch.setattr(tunneld, "tunneld_reachable", lambda: False)
    assert await LocationClient().reachable() is False
