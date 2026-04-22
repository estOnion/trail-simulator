from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..config import SETTINGS

log = logging.getLogger(__name__)


class DeviceUnavailable(RuntimeError):
    pass


class LocationClient:
    """Wraps pymobiledevice3's LocationSimulation over DVT (iOS 17+).

    The current pymobiledevice3 is fully async:
      - `async with DvtProvider(provider) as dvt`
      - `async with LocationSimulation(dvt) as loc`
      - `await loc.set(lat, lon)` / `await loc.clear()`

    We keep the DvtProvider + LocationSimulation contexts open for the full
    session — opening them per-tick adds hundreds of ms of jitter.
    """

    def __init__(self) -> None:
        self._provider: Any = None
        self._dvt_cm: Any = None   # DvtProvider context manager
        self._loc_cm: Any = None   # LocationSimulation context manager
        self._loc: Any = None      # entered LocationSimulation
        self._reconnecting = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    async def open(self) -> None:
        async with self._lock:
            await self._connect()

    async def _connect(self) -> None:
        from pymobiledevice3.services.dvt.instruments.dvt_provider import (
            DvtProvider,
        )
        from pymobiledevice3.services.dvt.instruments.location_simulation import (
            LocationSimulation,
        )

        provider = await _build_service_provider()
        dvt_cm = DvtProvider(provider)
        dvt = await dvt_cm.__aenter__()
        loc_cm = LocationSimulation(dvt)
        loc = await loc_cm.__aenter__()

        self._provider = provider
        self._dvt_cm = dvt_cm
        self._loc_cm = loc_cm
        self._loc = loc
        log.info("DVT LocationSimulation session opened")

    # ------------------------------------------------------------------ #
    async def set(self, lat: float, lon: float) -> None:
        if self._loc is None:
            await self._reconnect()
        try:
            await self._loc.set(lat, lon)
        except Exception as e:  # noqa: BLE001
            log.warning("location.set failed: %s — reconnecting", e)
            await self._reconnect()
            if self._loc is not None:
                await self._loc.set(lat, lon)

    # ------------------------------------------------------------------ #
    async def clear(self) -> None:
        loc_cm, dvt_cm, loc = self._loc_cm, self._dvt_cm, self._loc
        self._loc_cm = None
        self._dvt_cm = None
        self._loc = None
        self._provider = None

        if loc is not None:
            try:
                await loc.clear()
                log.info("DVT LocationSimulation cleared on device")
            except Exception as e:  # noqa: BLE001
                log.warning("location.clear failed: %s", e)
        if loc_cm is not None:
            try:
                await loc_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if dvt_cm is not None:
            try:
                await dvt_cm.__aexit__(None, None, None)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    async def _reconnect(self) -> None:
        if self._reconnecting:
            return
        self._reconnecting = True
        backoff = 1.0
        try:
            for _ in range(6):
                await asyncio.sleep(backoff)
                try:
                    await self._connect()
                    return
                except Exception as e:  # noqa: BLE001
                    log.warning("reconnect failed: %s", e)
                    backoff = min(backoff * 2, SETTINGS.reconnect_max_backoff_s)
            raise DeviceUnavailable("could not reconnect to iPhone")
        finally:
            self._reconnecting = False


# ---------------------------------------------------------------------- #
# Service provider resolution
# ---------------------------------------------------------------------- #
async def _build_service_provider() -> Any:
    """Get an RSD handle from tunneld. DVT on iOS 17+ requires tunneld —
    plain lockdown returns InvalidService, so we don't fall back."""
    from pymobiledevice3.tunneld.api import (
        TUNNELD_DEFAULT_ADDRESS,
        get_tunneld_devices,
    )
    from .tunneld import tunneld_reachable, start_instructions

    if not tunneld_reachable():
        raise DeviceUnavailable(start_instructions())

    try:
        rsds = await get_tunneld_devices(TUNNELD_DEFAULT_ADDRESS)
    except Exception as e:
        raise DeviceUnavailable(f"tunneld query failed: {e}") from e

    if not rsds:
        raise DeviceUnavailable(
            "tunneld is running but reports no devices. "
            "Check the USB cable and ensure the iPhone is trusted."
        )
    return rsds[0]
