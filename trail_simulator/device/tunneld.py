from __future__ import annotations

import socket
import sys
from typing import Any

from ..config import SETTINGS


def rsd_udid(rsd: Any) -> str | None:
    """Extract the udid from a tunneld RemoteServiceDiscovery object.

    Field name has varied across pymobiledevice3 versions, so fall back.
    """
    return (
        getattr(rsd, "udid", None)
        or getattr(rsd, "serial", None)
        or getattr(rsd, "identifier", None)
    )


def _default_address() -> tuple[str, int]:
    try:
        from pymobiledevice3.tunneld.api import TUNNELD_DEFAULT_ADDRESS
        return TUNNELD_DEFAULT_ADDRESS
    except Exception:
        return ("127.0.0.1", 49151)


def tunneld_reachable(timeout_s: float = 1.0) -> bool:
    """Cheap TCP probe: is something listening on tunneld's port?"""
    host, port = _default_address()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


_UNIX_INSTRUCTIONS = """\
tunneld is not running on {host}:{port}.

On iOS 17+ the DVT location-simulation service is only reachable over the
RemoteXPC tunnel, which tunneld provides. In a SEPARATE terminal, run:

    sudo pymobiledevice3 remote tunneld

Leave it running. If the app is already running, tunneld will be picked up
automatically — you do not need to restart the app.

For Wi-Fi-only operation (no USB cable), the iPhone must already have been
paired via USB once and have Wi-Fi pairing enabled:

    python3 -m pymobiledevice3 lockdown wifi-connections on
"""

_WINDOWS_INSTRUCTIONS = """\
tunneld is not running on {host}:{port}.

On iOS 17+ the DVT location-simulation service is only reachable over the
RemoteXPC tunnel, which tunneld provides. In a SEPARATE, ELEVATED window run
(right-click PowerShell -> Run as Administrator, or use the helper which
self-elevates):

    .\\scripts\\win\\run-tunneld.ps1

Leave it running. If the app is already running, tunneld will be picked up
automatically — you do not need to restart the app.

See docs/WINDOWS.md for driver setup (Apple Devices / usbmux) and the WSL2
alternative.
"""


def start_instructions() -> str:
    host, port = _default_address()
    template = (
        _WINDOWS_INSTRUCTIONS if sys.platform == "win32" else _UNIX_INSTRUCTIONS
    )
    return template.format(host=host, port=port)
