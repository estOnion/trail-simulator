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
        self._journal = None
        self._identity = None

    @property
    def store(self) -> Store:
        return self._store

    def attach_observatory(self, journal, identity) -> None:
        """Give every controller (existing and future) the journal and a way
        to learn which client and device it serves (OBS-01, OBS-03)."""
        self._journal = journal
        self._identity = identity
        for c in self._controllers.values():
            c.attach_observatory(journal, identity)

    def get_or_create(self, udid: str) -> SessionController:
        c = self._controllers.get(udid)
        if c is None:
            c = SessionController(self._factory(udid), self._store, udid=udid)
            if self._journal is not None:
                c.attach_observatory(self._journal, self._identity)
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
