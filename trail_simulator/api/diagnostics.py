from __future__ import annotations

from ..device.registry import DeviceRegistry


def explain_unroutable(
    registry: DeviceRegistry, client: str | None, device: str | None
) -> str:
    """Explain why a request could not be routed to a device.

    Shared by /ws/live (close reason) and the REST resolver (HTTP detail) so
    a phone that gets a 400 on "Test connection" sees the same scenario the
    backend log does: no devices, an unmatched client id, a device already
    held by someone else, or an ambiguous multi-device setup.
    """
    names = [n for _, n in registry.list_devices()]
    if not names:
        return "no devices registered — is the iPhone connected and paired?"
    if client is not None:
        udid = registry.resolve(client) or registry.default_udid()
        if udid is None:
            return (
                f"client {client!r} does not match any device name; "
                f"expected one of {names}"
            )
        holder = registry.client_for(udid)
        return (
            f"device {registry.name_for(udid)!r} is already bound to "
            f"client {holder!r} (connecting client: {client!r})"
        )
    if device is not None:
        return f"unknown device {device!r}; expected one of {names}"
    return f"no client/device specified and {len(names)} devices are connected: {names}"
