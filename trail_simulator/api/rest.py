from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..device.registry import DeviceRegistry, DuplicateClientIdError
from ..geocode import GeocodeError, search as geocode_search
from ..routing.osrm import RouteError
from ..session.controller import SessionController
from ..session.manager import SessionManager


class Destination(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class StartReq(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    destinations: list[Destination] = Field(..., min_length=1)
    speed_kmh: float = Field(..., gt=0, le=20)
    loop: bool = False
    skip_cooldown: bool = False


class RetargetReq(BaseModel):
    destinations: list[Destination] = Field(..., min_length=1)
    loop: bool | None = None


class SpeedReq(BaseModel):
    speed_kmh: float = Field(..., gt=0, le=20)


class BindReq(BaseModel):
    client_id: str = Field(..., min_length=1)
    udid: str = Field(..., min_length=1)


class FollowReq(BaseModel):
    follower_client_id: str = Field(..., min_length=1)
    leader_client_id: str = Field(..., min_length=1)


class UnfollowReq(BaseModel):
    client_id: str = Field(..., min_length=1)


def build_router(manager: SessionManager, registry: DeviceRegistry) -> APIRouter:
    r = APIRouter()

    def _resolve(
        x_client_id: str | None,
        x_device_name: str | None,
        client: str | None,
        device: str | None,
    ) -> SessionController:
        cid = x_client_id or client
        if cid:
            udid = registry.resolve_client(cid)
            if udid is None:
                udid = registry.auto_bind_single(cid)
            if udid is None:
                raise HTTPException(
                    status_code=400,
                    detail="Unbound client id; POST /api/bind to choose a device.",
                )
            return manager.get_or_create(udid)

        # Fallback: legacy device-name path (web frontend / single device).
        name = x_device_name or device
        udid = registry.resolve(name) if name else None
        if udid is None:
            udid = registry.default_udid()
        if udid is None:
            if name is None:
                raise HTTPException(
                    status_code=400,
                    detail="Multiple devices registered; send X-Device-Name header.",
                )
            raise HTTPException(
                status_code=404,
                detail=f"No backend device registered for name {name!r}.",
            )
        return manager.get_or_create(udid)

    @r.get("/devices")
    async def list_devices():
        return {
            "devices": [
                {
                    "udid": u,
                    "name": n,
                    "bound_client_id": registry.client_for(u),
                    "type": registry.type_for(u),
                }
                for u, n in registry.list_devices()
            ]
        }

    @r.get("/clients")
    async def list_clients():
        out = []
        for cid, udid, name in registry.list_clients():
            c = manager.get(udid)
            state = c.status().state.value if c else "idle"
            out.append({"client_id": cid, "name": name, "state": state})
        return {"clients": out}

    @r.post("/bind")
    async def bind(req: BindReq):
        if registry.name_for(req.udid) is None:
            raise HTTPException(
                status_code=404,
                detail=f"No connected device with udid {req.udid!r}.",
            )
        try:
            registry.bind(req.client_id, req.udid)
        except DuplicateClientIdError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True}

    @r.post("/follow")
    async def follow(req: FollowReq):
        f_udid = registry.resolve_client(req.follower_client_id)
        if f_udid is None:
            raise HTTPException(status_code=404, detail="Unknown follower client id.")
        l_udid = registry.resolve_client(req.leader_client_id)
        if l_udid is None:
            raise HTTPException(status_code=404, detail="Unknown leader client id.")
        if f_udid == l_udid:
            raise HTTPException(status_code=400, detail="A device cannot follow itself.")
        follower = manager.get_or_create(f_udid)
        leader = manager.get_or_create(l_udid)
        label = registry.name_for(l_udid) or req.leader_client_id
        await follower.follow(leader, label)
        return {"ok": True}

    @r.post("/unfollow")
    async def unfollow(req: UnfollowReq):
        udid = registry.resolve_client(req.client_id)
        if udid is None:
            raise HTTPException(status_code=404, detail="Unknown client id.")
        await manager.get_or_create(udid).unfollow()
        return {"ok": True}

    @r.get("/status")
    async def status(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        return _to_dict(controller.status())

    @r.post("/session")
    async def start(
        req: StartReq,
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        dests = [(d.lat, d.lon) for d in req.destinations]
        try:
            decision = await controller.start(
                req.start_lat, req.start_lon,
                dests,
                req.speed_kmh,
                loop=req.loop,
                skip_cooldown=req.skip_cooldown,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "cooldown": True,
                    "required_wait_s": decision.required_wait_s,
                    "jump_km": decision.jump_km,
                    "reason": decision.reason,
                },
            )
        return {"ok": True, "reason": decision.reason}

    @r.post("/retarget")
    async def retarget(
        req: RetargetReq,
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        dests = [(d.lat, d.lon) for d in req.destinations]
        try:
            await controller.update_destinations(dests, loop=req.loop)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/speed")
    async def speed(
        req: SpeedReq,
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        try:
            await controller.change_speed(req.speed_kmh)
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/pause")
    async def pause(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        await controller.pause()
        return {"ok": True}

    @r.post("/resume")
    async def resume(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        await controller.resume()
        return {"ok": True}

    @r.post("/stop")
    async def stop(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        await controller.stop()
        return {"ok": True}

    @r.post("/reset")
    async def reset(
        x_client_id: str | None = Header(default=None),
        x_device_name: str | None = Header(default=None),
        client: str | None = Query(default=None),
        device: str | None = Query(default=None),
    ):
        controller = _resolve(x_client_id, x_device_name, client, device)
        try:
            await controller.reset_device()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True}

    @r.get("/search")
    async def search(q: str = "", limit: int = 8):
        query = q.strip()
        if not query:
            return {"results": []}
        capped = max(1, min(20, limit))
        try:
            results = await geocode_search(query, limit=capped)
        except GeocodeError as e:
            raise HTTPException(status_code=502, detail=f"geocode: {e}")
        return {"results": results}

    return r


def _to_dict(s) -> dict:
    d = asdict(s)
    d["state"] = s.state.value
    return d
