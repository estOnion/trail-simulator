from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class DuplicateDeviceNameError(RuntimeError):
    """Two iPhones report the same DeviceName — the user must rename one."""


class DeviceRegistry:
    """In-memory map from human DeviceName to iPhone UDID.

    Populated at startup from pymobiledevice3 lockdown for each --udid the
    user passed (or the single auto-detected device). The TrailController
    iOS app sends UIDevice.current.name in the X-Device-Name header; the
    backend routes the request to the matching session.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, str] = {}
        self._by_udid: dict[str, str] = {}

    def register(self, udid: str, name: str) -> None:
        if name in self._by_name and self._by_name[name] != udid:
            raise DuplicateDeviceNameError(
                f"Two iPhones share the name {name!r}. Rename one in "
                "Settings → General → About → Name and restart the backend."
            )
        self._by_name[name] = udid
        self._by_udid[udid] = name

    def resolve(self, name: str) -> str | None:
        return self._by_name.get(name)

    def name_for(self, udid: str) -> str | None:
        return self._by_udid.get(udid)

    def list_devices(self) -> list[tuple[str, str]]:
        return [(u, n) for u, n in self._by_udid.items()]

    def default_udid(self) -> str | None:
        return next(iter(self._by_udid)) if len(self._by_udid) == 1 else None


async def fetch_device_name(udid: str) -> str:
    """Read DeviceName from pymobiledevice3 lockdown for the given UDID."""
    from pymobiledevice3.lockdown import create_using_usbmux

    lockdown = create_using_usbmux(serial=udid)
    name = (
        getattr(lockdown, "device_name", None)
        or (getattr(lockdown, "all_values", {}) or {}).get("DeviceName")
    )
    if not name:
        raise RuntimeError(f"lockdown returned no DeviceName for {udid}")
    return str(name)
