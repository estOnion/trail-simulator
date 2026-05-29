from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ..device.registry import DeviceRegistry
from ..session.controller import StatusSnapshot
from ..session.manager import SessionManager


def build_ws_router(manager: SessionManager, registry: DeviceRegistry) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        client = ws.query_params.get("client")
        device = ws.query_params.get("device")
        if client:
            udid = registry.resolve_client(client)
            if udid is None:
                udid = registry.auto_bind_single(client)
        else:
            udid = registry.resolve(device) if device else None
            if udid is None:
                udid = registry.default_udid()
        if udid is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
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


def _snap(s: StatusSnapshot) -> dict:
    d = asdict(s)
    d["state"] = s.state.value
    return d
