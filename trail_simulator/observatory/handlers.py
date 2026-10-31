"""App-level exception handlers: the single seam where rejections are
recorded and ``incident`` is added to error bodies (OBS-02, API-03)."""
from __future__ import annotations

import inspect
import json
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import catalogue
from .identity import Identity
from .journal import Journal

log = logging.getLogger(__name__)


def is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def is_incident_endpoint(path: str) -> bool:
    return path.startswith("/api/incidents") or path.startswith("/api/incident-codes")


def _recordable(path: str) -> bool:
    return is_api(path) and not is_incident_endpoint(path)


def _message(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("reason"), str):
        return detail["reason"]
    return json.dumps(jsonable_encoder(detail), default=str)


def _code_for(exc: StarletteHTTPException) -> str:
    code = getattr(exc, "code", None)
    if code:
        return code
    if exc.status_code == 404:
        return "request.not_found"
    if exc.status_code >= 500:
        return catalogue.UNEXPECTED
    return "request.invalid"


def _validation_message(errors: list) -> str:
    parts = []
    for e in errors:
        loc = ".".join(str(x) for x in e.get("loc", ()) if x != "body")
        parts.append(f"{loc}: {e.get('msg', '')}" if loc else str(e.get("msg", "")))
    return "request validation failed: " + "; ".join(parts)


def install(app: FastAPI, journal: Journal, identity: Identity) -> None:
    def _record(request: Request, status: int, code: str, detail, message: str, **extra):
        ctx = identity.for_request(request)
        return journal.record(
            extra.pop("kind", catalogue.REJECTION),
            code,
            message,
            request={
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "status": status,
                "detail": detail,
            },
            **ctx,
            **extra,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        headers = getattr(exc, "headers", None)
        if not is_api(path):
            body = {"detail": exc.detail}
            return JSONResponse(body, status_code=exc.status_code, headers=headers)
        ref = None
        if _recordable(path):
            ref = _record(
                request, exc.status_code, _code_for(exc), exc.detail, _message(exc.detail)
            )
            hook = getattr(exc, "after_record", None)
            if hook is not None:
                try:
                    res = hook(ref)
                    if inspect.isawaitable(res):
                        await res
                except Exception:  # noqa: BLE001
                    log.exception("after-record hook failed")
        return JSONResponse(
            {"detail": exc.detail, "incident": ref},
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = jsonable_encoder(exc.errors())
        path = request.url.path
        ref = None
        if _recordable(path):
            ref = _record(
                request, 422, "request.invalid", errors, _validation_message(errors)
            )
        body: dict = {"detail": errors}
        if is_api(path):
            body["incident"] = ref
        return JSONResponse(body, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        path = request.url.path
        text = f"unexpected server error: {type(exc).__name__}: {exc}"
        log.error(
            "unhandled error on %s %s: %s", request.method, path, text,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        if not is_api(path):
            return PlainTextResponse("Internal Server Error", status_code=500)
        ref = None
        if _recordable(path):
            ref = _record(
                request, 500, catalogue.UNEXPECTED, text, text,
                exception_type=type(exc).__name__,
                traceback="".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
                with_log=True,
            )
        return JSONResponse({"detail": text, "incident": ref}, status_code=500)
