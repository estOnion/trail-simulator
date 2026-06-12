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
