"""Incident endpoints (API-34 to API-38)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field, field_validator

from . import catalogue
from .identity import Identity
from .journal import IncidentFilter, Journal


class ClientReport(BaseModel):
    report_id: str
    code: str
    message: str
    started_at: AwareDatetime
    ended_at: AwareDatetime
    attempts: int = Field(..., ge=0)
    app_build: str
    os_version: str

    @field_validator("report_id")
    @classmethod
    def _is_uuid(cls, v: str) -> str:
        UUID(v)  # ValueError becomes a 422
        return v


class ReportBatch(BaseModel):
    sent_at: AwareDatetime
    reports: list[ClientReport] = Field(..., max_length=200)


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _epoch(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def build_incident_router(journal: Journal, identity: Identity, registry: Any) -> APIRouter:
    r = APIRouter()

    def _filter(
        kind: str | None, code: str | None, client: str | None, device: str | None,
        session: int | None, since: datetime | None, until: datetime | None,
        q: str | None,
    ) -> IncidentFilter:
        return IncidentFilter(
            kinds=_split(kind), codes=_split(code), client=client or None,
            device=device or None, session=session, since=_epoch(since),
            until=_epoch(until), q=q or None,
        )

    @r.post("/incidents")
    async def report(batch: ReportBatch, x_client_id: str | None = Header(default=None)):
        """Client failure reports (API-34). Addressing is optional: a phone
        that cannot reach its device must still be able to report."""
        for rep in batch.reports:
            if not catalogue.is_client_code(rep.code):
                raise HTTPException(
                    status_code=422,
                    detail=f"{rep.code!r} is not a client-failure code",
                )
        udid = registry.resolve_client(x_client_id) if x_client_id else None
        ids = identity.for_udid(udid, x_client_id)
        # Client times -> host clock, using the clock difference at upload.
        offset = journal.clock() - batch.sent_at.timestamp()
        accepted: list[dict] = []
        duplicates: list[str] = []
        for rep in batch.reports:
            # Echo the ID as sent; compare and store it as a UUID value, so
            # letter case never makes a stored report look new.
            rid = rep.report_id
            canonical = str(UUID(rid))
            if journal.has_report(canonical):
                duplicates.append(rid)
                continue
            ref = journal.add_client_failure(
                report_id=canonical,
                code=rep.code,
                message=rep.message,
                started_at=rep.started_at.timestamp() + offset,
                ended_at=rep.ended_at.timestamp() + offset,
                attempts=rep.attempts,
                app_build=rep.app_build,
                os_version=rep.os_version,
                client_id=ids["client_id"],
                device_udid=ids["device_udid"],
                device_name=ids["device_name"],
                offset_s=offset,
                client_times=(rep.started_at.isoformat(), rep.ended_at.isoformat()),
                sent_at=batch.sent_at.isoformat(),
            )
            accepted.append({"report_id": rid, "id": ref["id"]})
        return {"accepted": accepted, "duplicates": duplicates}

    @r.get("/incidents")
    async def list_incidents(
        kind: str | None = None,
        code: str | None = None,
        client: str | None = None,
        device: str | None = None,
        session: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        before: str | None = None,
    ):
        flt = _filter(kind, code, client, device, session, since, until, q)
        try:
            items, next_before = journal.list(flt, limit=limit, before=before)
        except ValueError:
            raise HTTPException(status_code=422, detail="malformed 'before' cursor")
        return {"incidents": items, "next_before": next_before}

    # Declared before /incidents/{id} so "summary" is not read as an id.
    @r.get("/incidents/summary")
    async def summary(
        kind: str | None = None,
        code: str | None = None,
        client: str | None = None,
        device: str | None = None,
        session: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
    ):
        flt = _filter(kind, code, client, device, session, since, until, q)
        return {"codes": journal.summary(flt)}

    @r.get("/incidents/{incident_id}")
    async def detail(incident_id: int):
        row = journal.get(incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no incident {incident_id}")
        return row

    @r.get("/incident-codes")
    async def codes():
        return {"codes": catalogue.catalogue_payload()}

    return r
