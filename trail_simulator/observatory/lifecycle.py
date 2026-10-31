"""Background upkeep that runs with the server (HST-36): the availability
heartbeat (OBS-10) and the daily retention sweep (OBS-09)."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from .availability import HEARTBEAT_S
from .journal import Journal

log = logging.getLogger(__name__)

SWEEP_S = 86400.0

Sleep = Callable[[float], Awaitable[None]]


async def run_heartbeat(
    journal: Journal, interval_s: float = HEARTBEAT_S, sleep: Sleep = asyncio.sleep
) -> None:
    while True:
        await sleep(interval_s)
        try:
            journal.availability.beat()
        except Exception:  # noqa: BLE001
            log.exception("availability heartbeat failed")


async def run_sweep(
    journal: Journal, interval_s: float = SWEEP_S, sleep: Sleep = asyncio.sleep
) -> None:
    while True:
        await sleep(interval_s)
        try:
            journal.prune()
        except Exception:  # noqa: BLE001
            log.exception("incident retention sweep failed")


def start(journal: Journal) -> list[asyncio.Task]:
    """Prune once, open an availability span, and start the periodic tasks."""
    try:
        journal.prune()
    except Exception:  # noqa: BLE001
        log.exception("incident retention sweep failed")
    try:
        journal.availability.start()
    except Exception:  # noqa: BLE001
        log.exception("could not open an availability span")
    return [
        asyncio.create_task(run_heartbeat(journal)),
        asyncio.create_task(run_sweep(journal)),
    ]


async def stop(journal: Journal, tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    try:
        journal.availability.shutdown()
    except Exception:  # noqa: BLE001
        log.exception("could not close the availability span")
