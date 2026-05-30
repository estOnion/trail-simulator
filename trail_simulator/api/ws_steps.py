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
    client_uuid: str | None
    udid: str | None
    connected_at: float
    last_heartbeat_at: float
    total_acked: int


class StepFanout:
    def __init__(self) -> None:
        self._clients: dict[str, StepClient] = {}
        self._change_cb = None
        self._registry = None

    def set_change_callback(self, cb) -> None:
        self._change_cb = cb

    def set_registry(self, registry) -> None:
        self._registry = registry

    def _udid_for(self, client: StepClient) -> str | None:
        """Resolve a companion to its device UDID at call time, so binding the
        device after the companion connected still routes steps correctly."""
        if self._registry is not None and client.client_uuid is not None:
            return self._registry.resolve_client(client.client_uuid)
        return client.udid

    def _fire_change(self) -> None:
        if self._change_cb is None:
            return
        try:
            asyncio.create_task(self._change_cb())
        except RuntimeError:
            pass

    def has_clients(self, udid: str | None = None) -> bool:
        if udid is None:
            return bool(self._clients)
        return any(self._udid_for(c) == udid for c in self._clients.values())

    def _register(self, client_id: str, client: StepClient) -> None:
        self._clients[client_id] = client
        self._fire_change()

    def _remove(self, client_id: str) -> None:
        if self._clients.pop(client_id, None) is not None:
            self._fire_change()

    async def send(self, payload: dict, udid: str | None = None) -> None:
        targets = [
            (cid, c)
            for cid, c in self._clients.items()
            if udid is None or self._udid_for(c) == udid
        ]
        if not targets:
            return
        failed = []
        results = await asyncio.gather(
            *[c.ws.send_json(payload) for _, c in targets],
            return_exceptions=True,
        )
        for (client_id, _), result in zip(targets, results):
            if isinstance(result, Exception):
                log.warning("step companion %s send failed — removing", client_id)
                failed.append(client_id)
        for client_id in failed:
            self._remove(client_id)

    def snapshot(self, udid: str | None = None) -> list[dict]:
        out = []
        for c in self._clients.values():
            if udid is not None and self._udid_for(c) != udid:
                continue
            out.append({
                "label": c.label,
                "udid": self._udid_for(c),
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
        conn_id = uuid.uuid4().hex[:8]

        label = f"device-{conn_id}"
        client_uuid: str | None = None
        udid: str | None = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=_HELLO_TIMEOUT_S)
            import json
            msg = json.loads(raw)
            if msg.get("type") == "hello":
                client_uuid = msg.get("client_id") or None
                label = msg.get("device_label") or client_uuid or label
                udid = msg.get("udid") or None
        except (asyncio.TimeoutError, Exception):
            pass

        client = StepClient(
            ws=ws,
            label=label,
            client_uuid=client_uuid,
            udid=udid,
            connected_at=time.time(),
            last_heartbeat_at=time.time(),
            total_acked=0,
        )
        broadcaster._register(conn_id, client)
        log.info("step companion connected: %s (%s) client=%s", label, conn_id, client_uuid)

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
            broadcaster._remove(conn_id)
            log.info("step companion disconnected: %s (%s)", label, conn_id)

    return r
