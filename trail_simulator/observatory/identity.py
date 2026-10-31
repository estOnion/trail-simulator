"""Who a request or session belongs to: client ID, device, session."""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote


class Identity:
    """Resolves the client and device behind a request or a device key,
    without raising and without binding anything."""

    def __init__(self, registry: Any, manager: Any) -> None:
        self._registry = registry
        self._manager = manager

    def for_udid(self, udid: str | None, client_id: str | None = None) -> dict:
        out: dict[str, Any] = {
            "client_id": client_id,
            "device_udid": udid,
            "device_name": None,
            "session_id": None,
            "session_state": None,
        }
        if udid is None:
            return out
        out["device_name"] = self._registry.name_for(udid)
        if out["client_id"] is None:
            out["client_id"] = self._registry.client_for(udid)
        controller = self._manager.get(udid)
        if controller is not None:
            snap = controller.status()
            out["session_id"] = snap.session_id
            out["session_state"] = snap.state.value
        return out

    def for_request(self, request: Any) -> dict:
        """Mirror of the REST resolver: client ID wins, else device name."""
        headers, query = request.headers, request.query_params
        client = headers.get("x-client-id") or query.get("client") or None
        if client:
            return self.for_udid(self._registry.resolve_client(client), client)
        name = headers.get("x-device-name")
        if name is not None:
            name = unquote(name)
        name = name or query.get("device") or None
        udid = self._registry.resolve(name) if name else None
        if udid is None:
            udid = self._registry.default_udid()
        return self.for_udid(udid, None)
