from __future__ import annotations

import socket

from ..config import SETTINGS


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


START_INSTRUCTIONS = """\
tunneld is not running on {host}:{port}.

On iOS 17+ the DVT location-simulation service is only reachable over the
RemoteXPC tunnel, which tunneld provides. In a SEPARATE terminal, run:

    sudo pymobiledevice3 remote tunneld

Leave it running, then relaunch `python -m trail_simulator` here.
"""


def start_instructions() -> str:
    host, port = _default_address()
    return START_INSTRUCTIONS.format(host=host, port=port)
