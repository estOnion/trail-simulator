from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable

from .android import list_android_devices

log = logging.getLogger(__name__)

IosLister = Callable[[], Awaitable[list[tuple[str, str]]]]
AndroidLister = Callable[[], Awaitable[list[tuple[str, str]]]]


async def _await_if_coro(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def discover_ios() -> list[tuple[str, str]]:
    """(udid, device_name) for each iPhone visible to usbmux. Reads DeviceName
    via lockdown, falling back to the UDID when it can't be read."""
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.usbmux import list_devices

    devices = await _await_if_coro(list_devices())
    out: list[tuple[str, str]] = []
    for d in devices:
        udid = getattr(d, "serial", None) or getattr(d, "udid", None)
        if not udid:
            continue
        try:
            lockdown = await _await_if_coro(create_using_usbmux(serial=udid))
            name = (
                getattr(lockdown, "device_name", None)
                or (getattr(lockdown, "all_values", {}) or {}).get("DeviceName")
                or udid
            )
        except Exception:  # noqa: BLE001
            name = udid
        out.append((udid, str(name)))
    return out


async def discover_connected(
    ios_lister: IosLister = discover_ios,
    android_lister: AndroidLister = list_android_devices,
) -> list[tuple[str, str, str]]:
    """All currently-connected devices as (udid, name, device_type). A failure
    enumerating one transport (e.g. usbmux down, adb missing) is logged and
    skipped so the other transport's devices still surface."""
    out: list[tuple[str, str, str]] = []
    try:
        for udid, name in await ios_lister():
            out.append((udid, name, "ios"))
    except Exception as e:  # noqa: BLE001
        log.warning("iOS discovery failed: %s", e)
    try:
        for serial, name in await android_lister():
            out.append((serial, name, "android"))
    except Exception as e:  # noqa: BLE001
        log.warning("Android discovery failed: %s", e)
    return out
