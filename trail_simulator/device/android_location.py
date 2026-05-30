from __future__ import annotations

import asyncio
import logging

from ..config import SETTINGS
from .injector import DeviceUnavailable

log = logging.getLogger(__name__)

PROVIDER = "gps"

# Provider capability flags for add-test-provider. Permissive so apps that
# require e.g. satellite/altitude still accept fixes from the test provider.
_ADD_PROVIDER = (
    f"cmd location providers add-test-provider {PROVIDER} "
    "--requiresNetwork false --requiresSatellite false --requiresCell false "
    "--hasMonetaryCost false --supportsAltitude true --supportsSpeed true "
    "--supportsBearing true --powerRequirement 1"
)


class AndroidLocationClient:
    """Inject GPS into a rooted Android 12+ phone over ADB.

    Uses the built-in `cmd location` test-provider shell commands — no app is
    installed on the phone. All commands run as root via `su -c` to sidestep
    mock-location appop configuration. Implements the LocationInjector contract
    (open/set/clear/reachable); SessionController handles error/auto-resume, so
    failures here simply raise DeviceUnavailable.
    """

    def __init__(self, serial: str) -> None:
        self._serial = serial

    # ------------------------------------------------------------------ #
    async def _adb(self, *args: str) -> str:
        """Run `adb -s <serial> <args...>`. Raise DeviceUnavailable on any
        failure (missing adb, offline device, non-zero exit)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", self._serial, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise DeviceUnavailable("adb not found on PATH") from e
        out, err = await proc.communicate()
        if proc.returncode != 0:
            msg = err.decode(errors="replace").strip() or "non-zero exit"
            raise DeviceUnavailable(f"adb {' '.join(args)} failed: {msg}")
        return out.decode(errors="replace")

    async def _su(self, cmd: str) -> str:
        return await self._adb("shell", "su", "-c", cmd)

    async def _su_quiet(self, cmd: str) -> None:
        try:
            await self._su(cmd)
        except Exception as e:  # noqa: BLE001
            log.debug("best-effort su failed: %s", e)

    # ------------------------------------------------------------------ #
    async def open(self) -> None:
        # Drop any stale provider from a prior session (best-effort), then
        # (re)register and enable it. add/enable must succeed.
        await self._su_quiet(f"cmd location providers remove-test-provider {PROVIDER}")
        await self._su(_ADD_PROVIDER)
        await self._su(f"cmd location providers enable-test-provider {PROVIDER}")
        log.info("android test provider %r enabled on %s", PROVIDER, self._serial)

    async def reachable(self) -> bool:
        try:
            out = await self._adb("get-state")
        except Exception:  # noqa: BLE001
            return False
        return out.strip() == "device"

    async def set(self, lat: float, lon: float) -> None:
        cmd = (
            f"cmd location providers set-test-provider-location {PROVIDER} "
            f"--location {lat},{lon} --accuracy 5"
        )
        # Bound the call so a wedged adb/device triggers the controller's
        # reconnect path instead of stalling the tick loop forever.
        await asyncio.wait_for(self._su(cmd), timeout=SETTINGS.device_set_timeout_s)

    async def clear(self) -> None:
        await self._su_quiet(f"cmd location providers remove-test-provider {PROVIDER}")
        log.info("android test provider %r removed on %s", PROVIDER, self._serial)
