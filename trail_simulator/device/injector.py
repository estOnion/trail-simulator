from __future__ import annotations

from typing import Protocol, runtime_checkable


class DeviceUnavailable(RuntimeError):
    """The target device can't be reached for GPS injection."""


@runtime_checkable
class LocationInjector(Protocol):
    """The contract SessionController depends on. iOS (LocationClient) and
    Android (AndroidLocationClient) adapters are interchangeable behind it."""

    async def open(self) -> None: ...
    async def set(self, lat: float, lon: float) -> None: ...
    async def clear(self) -> None: ...
    async def reachable(self) -> bool: ...
