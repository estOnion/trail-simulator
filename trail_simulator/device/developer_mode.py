from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any


log = logging.getLogger(__name__)


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


_WIFI_SETUP_HINT = (
    "No iPhone detected over USB or Wi-Fi.\n\n"
    "For Wi-Fi-only operation (iOS 17.4+):\n"
    "  1. Plug the iPhone in via USB once and tap 'Trust'.\n"
    "  2. Enable Developer Mode: Settings → Privacy & Security → Developer Mode.\n"
    "  3. Run: python3 -m pymobiledevice3 lockdown wifi-connections on\n"
    "  4. Unplug the cable; keep iPhone on the same LAN as this Mac.\n"
    "  5. Ensure 'sudo pymobiledevice3 remote tunneld' is running.\n\n"
    "Or plug in the iPhone via USB and rerun."
)


def _usbmux_udid(device: Any) -> str | None:
    return getattr(device, "serial", None) or getattr(device, "udid", None)


async def _preflight_via_tunneld(udid: str | None = None) -> PreflightResult:
    """Fall-through path when usbmux returns no matching device.

    Tunneld monitors USB, usbmux, mobdev2, AND Wi-Fi (RemotePairing) — so if
    the iPhone has `wifi-connections on` and is on the same LAN, tunneld will
    surface it here even with no cable attached.
    """
    from .tunneld import rsd_udid, start_instructions, tunneld_reachable

    if not tunneld_reachable():
        return PreflightResult(
            False, None, None, None,
            "No matching iPhone over USB, and tunneld is not running.\n\n"
            + start_instructions(),
        )

    try:
        from pymobiledevice3.tunneld.api import (
            TUNNELD_DEFAULT_ADDRESS,
            get_tunneld_devices,
        )
    except ImportError as e:
        return PreflightResult(
            False, None, None, None,
            f"pymobiledevice3 tunneld api missing: {e}",
        )

    try:
        rsds = await get_tunneld_devices(TUNNELD_DEFAULT_ADDRESS)
    except Exception as e:  # noqa: BLE001
        return PreflightResult(
            False, None, None, None,
            f"tunneld query failed: {e}",
        )

    def _has_target(items: list[Any], target: str | None) -> bool:
        if target is None:
            return bool(items)
        return any(rsd_udid(r) == target for r in items)

    # Bonjour mDNS discovery can take several seconds — especially the first
    # query after tunneld starts, or when multiple WiFi peers are converging
    # at different rates. Poll until the target appears (or any device if
    # no target was specified). A transient query failure should not abort
    # the wait — keep polling.
    for _ in range(8):
        if _has_target(rsds, udid):
            break
        await asyncio.sleep(1.0)
        try:
            rsds = await get_tunneld_devices(TUNNELD_DEFAULT_ADDRESS)
        except Exception:  # noqa: BLE001
            continue

    if udid is not None:
        rsds = [r for r in rsds if rsd_udid(r) == udid]
        if not rsds:
            return PreflightResult(
                False, None, None, None,
                f"Device with udid={udid} not found via USB or Wi-Fi/tunneld.",
            )

    if not rsds:
        return PreflightResult(False, None, None, None, _WIFI_SETUP_HINT)

    if len(rsds) > 1:
        udids = "\n  - ".join(rsd_udid(r) or "<unknown>" for r in rsds)
        return PreflightResult(
            False, None, None, None,
            "Multiple iPhones reachable via tunneld. Pass --udid to pick one.\n"
            f"Available UDIDs:\n  - {udids}",
        )

    first = rsds[0]
    target_udid = rsd_udid(first)
    ios_version = (
        getattr(first, "product_version", None)
        or getattr(first, "ios_version", None)
    )
    return PreflightResult(
        True, target_udid, ios_version, None,
        f"iPhone OK via Wi-Fi/tunneld (udid={target_udid}, iOS {ios_version or '?'})",
    )


async def _preflight_async(udid: str | None = None) -> PreflightResult:
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

    if udid is not None:
        devices = [d for d in devices if _usbmux_udid(d) == udid]

    if not devices:
        if udid is None:
            log.info("usbmux reports no devices; falling through to tunneld/Wi-Fi discovery")
        else:
            log.info("udid %s not on USB; trying tunneld/Wi-Fi discovery", udid)
        return await _preflight_via_tunneld(udid=udid)

    if len(devices) > 1:
        udids = "\n  - ".join(_usbmux_udid(d) or "<unknown>" for d in devices)
        return PreflightResult(
            False, None, None, None,
            "Multiple iPhones detected over USB. Pass --udid to pick one.\n"
            f"Available UDIDs:\n  - {udids}",
        )

    first = devices[0]
    target_udid = _usbmux_udid(first)
    try:
        lockdown = await _await_if_coro(create_using_usbmux(serial=target_udid))
    except Exception as e:  # noqa: BLE001
        return PreflightResult(
            False, target_udid, None, None,
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
            False, target_udid, ios_version, False,
            "Developer Mode is OFF. Enable: Settings → Privacy & Security → Developer Mode.",
        )

    return PreflightResult(
        True, target_udid, ios_version, dev_mode,
        f"iPhone OK (udid={target_udid}, iOS {ios_version})",
    )


def preflight(udid: str | None = None) -> PreflightResult:
    return asyncio.run(_preflight_async(udid=udid))
