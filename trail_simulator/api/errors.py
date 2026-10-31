"""REST failures that carry an incident code (ADR-0048)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import HTTPException

# Called by the exception handler with the incident reference it recorded for
# this answer (or None), so the session can point its snapshot at that incident.
AfterRecord = Callable[[dict | None], Awaitable[None] | None]


class CodedHTTPException(HTTPException):
    """An ``HTTPException`` whose rejection is recorded under ``code``."""

    def __init__(
        self,
        status_code: int,
        detail: Any,
        code: str,
        after_record: AfterRecord | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.after_record = after_record
