from __future__ import annotations

from typing import Protocol, runtime_checkable


class DeviceUnavailable(RuntimeError):
    """The target device can't be reached for GPS injection.

    ``code`` is the incident code (ADR-0048); the controller falls back to
    ``device.connection_lost`` when a raise site gave none."""

    def __init__(self, *args: object, code: str | None = None) -> None:
        super().__init__(*args)
        self.code = code


@runtime_checkable
class LocationInjector(Protocol):
    """The contract SessionController depends on. iOS (LocationClient) and
    Android (AndroidLocationClient) adapters are interchangeable behind it."""

    async def open(self) -> None: ...
    async def set(self, lat: float, lon: float) -> None: ...
    async def clear(self) -> None: ...
    async def reachable(self) -> bool: ...
