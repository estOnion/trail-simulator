from __future__ import annotations

import pytest

from trail_simulator.device import android as mod
from trail_simulator.device.android import (
    _parse_devices,
    android_sdk_int,
    list_android_devices,
)


def test_parse_devices_keeps_only_online():
    out = (
        "List of devices attached\n"
        "RZ8N\tdevice\n"
        "emulator-5554\toffline\n"
        "ABCD\tunauthorized\n"
        "\n"
    )
    assert _parse_devices(out) == ["RZ8N"]


@pytest.mark.asyncio
async def test_list_android_devices_reads_model_name(monkeypatch):
    async def fake_adb(*args: str) -> str:
        if args == ("devices",):
            return "List of devices attached\nRZ8N\tdevice\n"
        if args[:2] == ("-s", "RZ8N") and "ro.product.model" in args:
            return "Pixel 7\n"
        return ""

    monkeypatch.setattr(mod, "_adb", fake_adb)
    assert await list_android_devices() == [("RZ8N", "Pixel 7")]


@pytest.mark.asyncio
async def test_list_android_devices_falls_back_to_serial_when_no_model(monkeypatch):
    async def fake_adb(*args: str) -> str:
        if args == ("devices",):
            return "List of devices attached\nRZ8N\tdevice\n"
        return "\n"  # empty model

    monkeypatch.setattr(mod, "_adb", fake_adb)
    assert await list_android_devices() == [("RZ8N", "RZ8N")]


@pytest.mark.asyncio
async def test_android_sdk_int_parses_prop(monkeypatch):
    async def fake_adb(*args: str) -> str:
        assert "ro.build.version.sdk" in args
        return "33\n"

    monkeypatch.setattr(mod, "_adb", fake_adb)
    assert await android_sdk_int("RZ8N") == 33
