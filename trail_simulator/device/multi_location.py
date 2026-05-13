from __future__ import annotations

import asyncio
import logging

from .location import LocationClient

log = logging.getLogger(__name__)


class MultiLocationClient:
    """Mirror mode — broadcasts open/set/clear to N LocationClients in parallel.

    Each device gets its own DvtProvider + LocationSimulation session. set()
    fans out concurrently; per-device failures are logged but do NOT abort
    the shared session (each inner LocationClient has its own reconnect
    backoff that fires on the next tick). If every device fails on the same
    call, the first exception is re-raised so SessionController transitions
    to error via the existing path.

    Duck-compatible with LocationClient — SessionController calls only
    open/set/clear, so no inheritance is needed.
    """

    def __init__(self, udids: list[str]) -> None:
        if not udids:
            raise ValueError("MultiLocationClient requires at least one udid")
        self._udids = list(udids)
        self._clients = [LocationClient(udid=u) for u in udids]

    async def open(self) -> None:
        results = await asyncio.gather(
            *(c.open() for c in self._clients),
            return_exceptions=True,
        )
        for udid, res in zip(self._udids, results):
            if isinstance(res, Exception):
                log.warning("device %s open failed: %s", udid, res)
        if all(isinstance(r, Exception) for r in results):
            raise results[0]

    async def set(self, lat: float, lon: float) -> None:
        results = await asyncio.gather(
            *(c.set(lat, lon) for c in self._clients),
            return_exceptions=True,
        )
        for udid, res in zip(self._udids, results):
            if isinstance(res, Exception):
                log.warning("device %s set failed: %s", udid, res)
        if all(isinstance(r, Exception) for r in results):
            raise results[0]

    async def clear(self) -> None:
        results = await asyncio.gather(
            *(c.clear() for c in self._clients),
            return_exceptions=True,
        )
        for udid, res in zip(self._udids, results):
            if isinstance(res, Exception):
                log.warning("device %s clear failed: %s", udid, res)
