from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

_HELLO_TIMEOUT_S = 5.0


@dataclass
class StepClient:
    ws: WebSocket
    label: str
    udid: str | None
    connected_at: float
    last_heartbeat_at: float
    total_acked: int


class StepFanout:
    def __init__(self) -> None:
        self._clients: dict[str, StepClient] = {}
        self._change_cb = None

    def set_change_callback(self, cb) -> None:
        self._change_cb = cb

    def _fire_change(self) -> None:
        if self._change_cb is None:
            return
        try:
            asyncio.create_task(self._change_cb())
        except RuntimeError:
            pass

    def has_clients(self) -> bool:
        return bool(self._clients)

    def _register(self, client_id: str, client: StepClient) -> None:
        self._clients[client_id] = client
        self._fire_change()

    def _remove(self, client_id: str) -> None:
        if self._clients.pop(client_id, None) is not None:
            self._fire_change()

    async def send(self, payload: dict) -> None:
        if not self._clients:
            return
        failed = []
        results = await asyncio.gather(
            *[c.ws.send_json(payload) for c in self._clients.values()],
            return_exceptions=True,
        )
        for client_id, result in zip(list(self._clients), results):
            if isinstance(result, Exception):
                log.warning("step companion %s send failed — removing", client_id)
                failed.append(client_id)
        for client_id in failed:
            self._remove(client_id)

    def snapshot(self) -> list[dict]:
        out = []
        for c in self._clients.values():
            out.append({
                "label": c.label,
                "udid": c.udid,
                "connected_at_iso": datetime.fromtimestamp(c.connected_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_heartbeat_iso": datetime.fromtimestamp(c.last_heartbeat_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total_acked": c.total_acked,
            })
        return out


broadcaster = StepFanout()


def build_ws_steps_router() -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/steps")
    async def ws_steps(ws: WebSocket):
        await ws.accept()
        client_id = uuid.uuid4().hex[:8]

        label = f"device-{client_id}"
        udid: str | None = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=_HELLO_TIMEOUT_S)
            import json
            msg = json.loads(raw)
            if msg.get("type") == "hello":
                label = msg.get("device_label") or label
                udid = msg.get("udid") or None
        except (asyncio.TimeoutError, Exception):
            pass

        now = time.monotonic()
        client = StepClient(
            ws=ws,
            label=label,
            udid=udid,
            connected_at=time.time(),
            last_heartbeat_at=time.time(),
            total_acked=0,
        )
        broadcaster._register(client_id, client)
        log.info("step companion connected: %s (%s)", label, client_id)

        try:
            while True:
                text = await ws.receive_text()
                try:
                    import json as _json
                    msg = _json.loads(text)
                    if msg.get("type") == "heartbeat":
                        client.last_heartbeat_at = time.time()
                        client.total_acked = msg.get("total_written", client.total_acked)
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            broadcaster._remove(client_id)
            log.info("step companion disconnected: %s (%s)", label, client_id)

    return r
