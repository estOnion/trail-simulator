from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ..device.registry import DeviceRegistry
from ..session.controller import StatusSnapshot
from ..session.manager import SessionManager

log = logging.getLogger(__name__)


def build_ws_router(manager: SessionManager, registry: DeviceRegistry) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        client = ws.query_params.get("client")
        device = ws.query_params.get("device")
        if client:
            udid = registry.resolve_client(client)
            if udid is None:
                udid = registry.auto_bind(client)
        else:
            udid = registry.resolve(device) if device else None
            if udid is None:
                udid = registry.default_udid()
        if udid is None:
            reason = _reject_reason(registry, client, device)
            log.warning("rejecting /ws/live: %s", reason)
            await ws.close(
                code=status.WS_1008_POLICY_VIOLATION,
                # close-frame reasons are capped at 123 bytes
                reason=reason.encode()[:120].decode("utf-8", "ignore"),
            )
            return

        controller = manager.get_or_create(udid)
        await ws.accept()
        queue: asyncio.Queue[StatusSnapshot] = asyncio.Queue(maxsize=64)

        async def listener(snap: StatusSnapshot) -> None:
            if queue.full():
                try:
                    queue.get_nowait()
                except Exception:
                    pass
            await queue.put(snap)

        controller.add_listener(listener)
        await queue.put(controller.status())

        try:
            while True:
                snap = await queue.get()
                await ws.send_json(_snap(snap))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            controller.remove_listener(listener)

    return r


def _reject_reason(
    registry: DeviceRegistry, client: str | None, device: str | None
) -> str:
    """Explain why a /ws/live connection could not be routed to a device."""
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


def _snap(s: StatusSnapshot) -> dict:
    d = asdict(s)
    d["state"] = s.state.value
    return d
