from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..session.controller import SessionController, StatusSnapshot


def build_ws_router(controller: SessionController) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        await ws.accept()
        queue: asyncio.Queue[StatusSnapshot] = asyncio.Queue(maxsize=64)

        async def listener(snap: StatusSnapshot) -> None:
            if queue.full():
                # drop oldest to keep latest
                try:
                    queue.get_nowait()
                except Exception:
                    pass
            await queue.put(snap)

        controller.add_listener(listener)
        # push initial snapshot
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
