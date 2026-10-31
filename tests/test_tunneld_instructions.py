from __future__ import annotations

from trail_simulator.device import tunneld


def test_start_instructions_windows(monkeypatch):
    monkeypatch.setattr(tunneld.sys, "platform", "win32")
    msg = tunneld.start_instructions()
    assert "Administrator" in msg
    assert "run-tunneld.ps1" in msg
    assert "sudo" not in msg


def test_start_instructions_macos(monkeypatch):
    monkeypatch.setattr(tunneld.sys, "platform", "darwin")
    msg = tunneld.start_instructions()
    assert "sudo pymobiledevice3 remote tunneld" in msg
    assert "Administrator" not in msg


def test_tunnel_not_running_raises_device_unavailable_with_tunnel_down_code(monkeypatch):
    import asyncio

    import pytest

    from trail_simulator.device import location
    from trail_simulator.device.injector import DeviceUnavailable

    monkeypatch.setattr(tunneld, "tunneld_reachable", lambda *a, **k: False)
    with pytest.raises(DeviceUnavailable) as ei:
        asyncio.run(location._build_service_provider(udid="U"))
    assert ei.value.code == "device.tunnel_down"
