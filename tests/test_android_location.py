from __future__ import annotations

from types import SimpleNamespace

import pytest

from trail_simulator.device import android_location as mod
from trail_simulator.device.android_location import AndroidLocationClient
from trail_simulator.device.injector import DeviceUnavailable, LocationInjector


def _recorder(client):
    """Replace the single adb seam with a recorder that succeeds."""
    calls: list[tuple[str, ...]] = []

    async def fake_adb(*args: str) -> str:
        calls.append(args)
        return ""

    client._adb = fake_adb
    return calls


def test_satisfies_injector_protocol():
    assert isinstance(AndroidLocationClient("SERIAL"), LocationInjector)


@pytest.mark.asyncio
async def test_set_formats_set_test_provider_location():
    client = AndroidLocationClient("SERIAL")
    calls = _recorder(client)
    await client.set(25.0375, 121.5637)
    # The last adb invocation runs a su shell carrying the cmd-location string.
    cmd = calls[-1][-1]
    assert "cmd location providers set-test-provider-location gps" in cmd
    assert "--location 25.0375,121.5637" in cmd


@pytest.mark.asyncio
async def test_open_adds_and_enables_provider():
    client = AndroidLocationClient("SERIAL")
    calls = _recorder(client)
    await client.open()
    joined = " ; ".join(c[-1] for c in calls)
    assert "add-test-provider gps" in joined
    assert "enable-test-provider gps" in joined
    # add must precede enable
    assert joined.index("add-test-provider") < joined.index("enable-test-provider")


@pytest.mark.asyncio
async def test_open_tolerates_stale_provider_removal_failure():
    client = AndroidLocationClient("SERIAL")
    seq: list[str] = []

    async def fake_adb(*args: str) -> str:
        cmd = args[-1]
        seq.append(cmd)
        if "remove-test-provider" in cmd:
            raise DeviceUnavailable("no such provider")  # stale cleanup may fail
        return ""

    client._adb = fake_adb
    await client.open()  # must not raise
    assert any("enable-test-provider" in c for c in seq)


@pytest.mark.asyncio
async def test_clear_removes_provider():
    client = AndroidLocationClient("SERIAL")
    calls = _recorder(client)
    await client.clear()
    assert any("remove-test-provider gps" in c[-1] for c in calls)


@pytest.mark.asyncio
async def test_reachable_true_when_get_state_device():
    client = AndroidLocationClient("SERIAL")

    async def fake_adb(*args: str) -> str:
        assert args == ("get-state",)
        return "device\n"

    client._adb = fake_adb
    assert await client.reachable() is True


@pytest.mark.asyncio
async def test_reachable_false_when_adb_fails():
    client = AndroidLocationClient("SERIAL")

    async def fake_adb(*args: str) -> str:
        raise DeviceUnavailable("offline")

    client._adb = fake_adb
    assert await client.reachable() is False


@pytest.mark.asyncio
async def test_set_raises_device_unavailable_on_adb_failure():
    client = AndroidLocationClient("SERIAL")

    async def fake_adb(*args: str) -> str:
        raise DeviceUnavailable("boom")

    client._adb = fake_adb
    with pytest.raises(DeviceUnavailable):
        await client.set(1.0, 2.0)


@pytest.mark.asyncio
async def test_adb_maps_nonzero_exit_to_device_unavailable(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return (b"", b"error: no devices/emulators found")

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)
    client = AndroidLocationClient("SERIAL")
    with pytest.raises(DeviceUnavailable):
        await client._adb("get-state")
