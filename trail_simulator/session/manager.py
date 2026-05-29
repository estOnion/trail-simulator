from __future__ import annotations

import logging
from typing import Callable

from ..device.location import LocationClient
from .controller import SessionController
from .store import Store

log = logging.getLogger(__name__)

DeviceFactory = Callable[[str], LocationClient]


class SessionManager:
    """Holds one SessionController per iPhone UDID. Controllers are created
    lazily on first reference so iPhones that never receive a command don't
    open a DVT tunnel."""

    def __init__(self, device_factory: DeviceFactory, store: Store) -> None:
        self._factory = device_factory
        self._store = store
        self._controllers: dict[str, SessionController] = {}

    def get_or_create(self, udid: str) -> SessionController:
        c = self._controllers.get(udid)
        if c is None:
            c = SessionController(self._factory(udid), self._store)
            self._controllers[udid] = c
            log.info("session controller created for udid=%s", udid)
        return c

    def get(self, udid: str) -> SessionController | None:
        return self._controllers.get(udid)

    def list_active(self) -> list[tuple[str, SessionController]]:
        return list(self._controllers.items())

    async def stop_all(self) -> None:
        for udid, c in self._controllers.items():
            try:
                await c.stop()
                await c.reset_device()
            except Exception as e:  # noqa: BLE001
                log.warning("stop_all failed for %s: %s", udid, e)
