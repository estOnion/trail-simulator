from __future__ import annotations

import asyncio
import logging

from .injector import DeviceUnavailable

log = logging.getLogger(__name__)


async def _adb(*args: str) -> str:
    """Run `adb <args...>`, return stdout. Raise DeviceUnavailable on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", *args,
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


def _parse_devices(out: str) -> list[str]:
    """Serials in state 'device' from `adb devices` output (skip the header,
    blanks, and offline/unauthorized entries)."""
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


async def list_android_devices() -> list[tuple[str, str]]:
    """(serial, model_name) for each online ADB device. Falls back to the
    serial when the model prop is empty."""
    serials = _parse_devices(await _adb("devices"))
    out: list[tuple[str, str]] = []
    for serial in serials:
        model = (
            await _adb("-s", serial, "shell", "getprop", "ro.product.model")
        ).strip()
        out.append((serial, model or serial))
    return out


async def android_sdk_int(serial: str) -> int:
    """API level from ro.build.version.sdk (e.g. 33 for Android 13)."""
    out = await _adb("-s", serial, "shell", "getprop", "ro.build.version.sdk")
    return int(out.strip() or "0")
