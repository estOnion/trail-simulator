from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..routing.osrm import RouteError
from ..session.controller import SessionController


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


def build_router(controller: SessionController) -> APIRouter:
    r = APIRouter()

    @r.get("/status")
    async def status():
        s = controller.status()
        return _to_dict(s)

    @r.post("/session")
    async def start(req: StartReq):
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
    async def retarget(req: RetargetReq):
        dests = [(d.lat, d.lon) for d in req.destinations]
        try:
            await controller.update_destinations(dests, loop=req.loop)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/speed")
    async def speed(req: SpeedReq):
        try:
            await controller.change_speed(req.speed_kmh)
        except RouteError as e:
            raise HTTPException(status_code=502, detail=f"route: {e}")
        return {"ok": True}

    @r.post("/pause")
    async def pause():
        await controller.pause()
        return {"ok": True}

    @r.post("/resume")
    async def resume():
        await controller.resume()
        return {"ok": True}

    @r.post("/stop")
    async def stop():
        await controller.stop()
        return {"ok": True}

    return r


def _to_dict(s) -> dict:
    d = asdict(s)
    d["state"] = s.state.value
    return d
