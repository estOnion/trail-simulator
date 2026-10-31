from __future__ import annotations

from typing import NamedTuple

from ..device.registry import DeviceRegistry


class Diagnosis(NamedTuple):
    """Why a request could not be routed: its incident code and its text."""

    code: str
    text: str


def diagnose_unroutable(
    registry: DeviceRegistry, client: str | None, device: str | None
) -> Diagnosis:
    """Explain why a request could not be routed to a device, with the
    incident code of the scenario (ADR-0048)."""
    names = [n for _, n in registry.list_devices()]
    if not names:
        return Diagnosis(
            "addressing.no_devices",
            "no devices registered — is the iPhone connected and paired?",
        )
    if client is not None:
        udid = registry.resolve(client) or registry.default_udid()
        if udid is None:
            return Diagnosis(
                "addressing.client_unmatched",
                f"client {client!r} does not match any device name; "
                f"expected one of {names}",
            )
        holder = registry.client_for(udid)
        return Diagnosis(
            "addressing.device_held",
            f"device {registry.name_for(udid)!r} is already bound to "
            f"client {holder!r} (connecting client: {client!r})",
        )
    if device is not None:
        return Diagnosis(
            "addressing.unknown_device",
            f"unknown device {device!r}; expected one of {names}",
        )
    return Diagnosis(
        "addressing.ambiguous",
        f"no client/device specified and {len(names)} devices are connected: {names}",
    )


def explain_unroutable(
    registry: DeviceRegistry, client: str | None, device: str | None
) -> str:
    """Explain why a request could not be routed to a device.

    Shared by /ws/live (close reason) and the REST resolver (HTTP detail) so
    a phone that gets a 400 on "Test connection" sees the same scenario the
    backend log does: no devices, an unmatched client id, a device already
    held by someone else, or an ambiguous multi-device setup.
    """
    return diagnose_unroutable(registry, client, device).text
