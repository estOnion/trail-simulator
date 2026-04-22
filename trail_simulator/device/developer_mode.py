from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    udid: str | None
    ios_version: str | None
    developer_mode: bool | None
    message: str


async def _await_if_coro(val: Any) -> Any:
    if inspect.iscoroutine(val):
        return await val
    return val


async def _preflight_async() -> PreflightResult:
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.usbmux import list_devices
    except ImportError as e:
        return PreflightResult(
            False, None, None, None,
            f"pymobiledevice3 not installed: {e}",
        )

    try:
        devices = await _await_if_coro(list_devices())
    except Exception as e:  # noqa: BLE001
        return PreflightResult(
            False, None, None, None,
            f"usbmux list_devices failed: {e}",
        )

    if not devices:
        return PreflightResult(
            False, None, None, None,
            "No USB iPhone detected. Plug it in and tap 'Trust' on the device.",
        )

    first = devices[0]
    udid = getattr(first, "serial", None) or getattr(first, "udid", None)
    try:
        lockdown = await _await_if_coro(create_using_usbmux(serial=udid))
    except Exception as e:  # noqa: BLE001
        return PreflightResult(
            False, udid, None, None,
            f"Lockdown handshake failed (is the device trusted?): {e}",
        )

    ios_version = None
    try:
        ios_version = getattr(lockdown, "product_version", None)
        if ios_version is None:
            all_vals = getattr(lockdown, "all_values", {}) or {}
            ios_version = all_vals.get("ProductVersion")
    except Exception:
        pass

    dev_mode: bool | None = None
    try:
        result = lockdown.get_value(
            domain="com.apple.security.mac.amfi", key="DeveloperModeStatus"
        )
        result = await _await_if_coro(result)
        dev_mode = bool(result)
    except Exception:
        dev_mode = None

    if dev_mode is False:
        return PreflightResult(
            False, udid, ios_version, False,
            "Developer Mode is OFF. Enable: Settings → Privacy & Security → Developer Mode.",
        )

    return PreflightResult(
        True, udid, ios_version, dev_mode,
        f"iPhone OK (udid={udid}, iOS {ios_version})",
    )


def preflight() -> PreflightResult:
    return asyncio.run(_preflight_async())
