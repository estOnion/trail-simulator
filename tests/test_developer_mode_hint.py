from __future__ import annotations

from trail_simulator.device import developer_mode


def test_wifi_hint_windows(monkeypatch):
    monkeypatch.setattr(developer_mode.sys, "platform", "win32")
    msg = developer_mode._wifi_setup_hint()
    assert "run-tunneld.ps1" in msg
    assert "this PC" in msg
    assert "sudo" not in msg
    assert "this Mac" not in msg


def test_wifi_hint_macos(monkeypatch):
    monkeypatch.setattr(developer_mode.sys, "platform", "darwin")
    msg = developer_mode._wifi_setup_hint()
    assert "sudo pymobiledevice3 remote tunneld" in msg
    assert "this Mac" in msg
    assert "run-tunneld.ps1" not in msg
