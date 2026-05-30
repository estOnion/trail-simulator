# tests/test_discovery.py
import pytest

from trail_simulator.device.discovery import discover_connected


@pytest.mark.asyncio
async def test_discover_combines_ios_and_android_with_types():
    async def ios():
        return [("UDID-A", "Jack"), ("UDID-B", "Anna")]

    async def android():
        return [("SER-1", "Pixel 7")]

    out = await discover_connected(ios_lister=ios, android_lister=android)
    assert ("UDID-A", "Jack", "ios") in out
    assert ("UDID-B", "Anna", "ios") in out
    assert ("SER-1", "Pixel 7", "android") in out


@pytest.mark.asyncio
async def test_ios_failure_does_not_block_android():
    async def ios():
        raise RuntimeError("usbmux down")

    async def android():
        return [("SER-1", "Pixel 7")]

    out = await discover_connected(ios_lister=ios, android_lister=android)
    assert out == [("SER-1", "Pixel 7", "android")]


@pytest.mark.asyncio
async def test_android_failure_does_not_block_ios():
    async def ios():
        return [("UDID-A", "Jack")]

    async def android():
        raise RuntimeError("adb not found")

    out = await discover_connected(ios_lister=ios, android_lister=android)
    assert out == [("UDID-A", "Jack", "ios")]
