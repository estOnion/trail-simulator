"""The incident journal (OBS-05..09): SQLite tables beside the session store.

All writes happen on the event-loop thread as small single-row statements. A
failure to record never propagates (OBS-08): ``record`` logs it and returns
None, which callers put in the client-facing ``incident`` field.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import catalogue
from .availability import SCHEMA as AVAILABILITY_SCHEMA, Availability
from .logbuffer import LogRingBuffer
from .version import backend_version

log = logging.getLogger(__name__)

COLLAPSE_WINDOW_S = 10 * 60
RETENTION_S = 30 * 86400
MAX_LOG_LINES = 100

# Bounds on stored text so one incident cannot grow the journal without limit.
MAX_MESSAGE = 2000
MAX_TRACEBACK = 20000
MAX_DETAIL = 4000
MAX_PATH = 500
MAX_QUERY = 1000
MAX_SHORT = 200
MAX_LOG_LINE = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    code            TEXT NOT NULL,
    remedy          TEXT,
    source          TEXT NOT NULL,
    message         TEXT NOT NULL,
    first_seen      REAL NOT NULL,
    last_seen       REAL NOT NULL,
    count           INTEGER NOT NULL DEFAULT 1,
    client_id       TEXT,
    device_udid     TEXT,
    device_name     TEXT,
    session_id      INTEGER,
    session_state   TEXT,
    backend_version TEXT,
    request_method  TEXT,
    request_path    TEXT,
    request_query   TEXT,
    response_status INTEGER,
    response_detail TEXT,
    exception_type  TEXT,
    traceback       TEXT,
    log_lines       TEXT,
    attempts        INTEGER,
    app_build       TEXT,
    os_version      TEXT,
    report_id       TEXT,
    context         TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_last_seen ON incidents (last_seen);
CREATE INDEX IF NOT EXISTS idx_incidents_code ON incidents (code);
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_report
    ON incidents (report_id) WHERE report_id IS NOT NULL;
"""


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _cut(value, limit: int):
    if value is None:
        return None
    s = value if isinstance(value, str) else str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class IncidentFilter:
    kinds: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)  # "device.*" matches a prefix
    client: str | None = None
    device: str | None = None
    session: int | None = None
    since: float | None = None
    until: float | None = None
    q: str | None = None

    def where(self) -> tuple[str, list]:
        clauses: list[str] = []
        args: list = []
        if self.kinds:
            clauses.append("kind IN (%s)" % ",".join("?" * len(self.kinds)))
            args += self.kinds
        if self.codes:
            parts = []
            for c in self.codes:
                if c.endswith(".*"):
                    prefix = c[:-1]  # keep the dot
                    parts.append("substr(code, 1, ?) = ?")
                    args += [len(prefix), prefix]
                else:
                    parts.append("code = ?")
                    args.append(c)
            clauses.append("(" + " OR ".join(parts) + ")")
        if self.client:
            clauses.append("client_id = ?")
            args.append(self.client)
        if self.device:
            clauses.append("(device_name = ? OR device_udid = ?)")
            args += [self.device, self.device]
        if self.session is not None:
            clauses.append("session_id = ?")
            args.append(self.session)
        if self.since is not None:
            clauses.append("last_seen >= ?")
            args.append(self.since)
        if self.until is not None:
            clauses.append("last_seen <= ?")
            args.append(self.until)
        if self.q:
            clauses.append("message LIKE ? ESCAPE '\\'")
            args.append(f"%{_like_escape(self.q)}%")
        return (" AND ".join(clauses) or "1=1"), args


_LIST_COLS = (
    "id, kind, code, remedy, source, message, first_seen, last_seen, count, "
    "client_id, device_name, session_id"
)


def _list_item(r: tuple) -> dict:
    code = r[2]
    return {
        "id": r[0],
        "kind": r[1],
        "code": code,
        "remedy": catalogue.remedy_for(code) if catalogue.is_known(code) else r[3],
        "source": r[4],
        "message": r[5],
        "first_seen": iso(r[6]),
        "last_seen": iso(r[7]),
        "count": r[8],
        "client_id": r[9],
        "device_name": r[10],
        "session_id": r[11],
    }


class Journal:
    def __init__(
        self,
        path: Path | str,
        clock: Callable[[], float] = time.time,
        log_buffer: LogRingBuffer | None = None,
        version: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        self._log_buffer = log_buffer
        # Resolved once here, at startup, so recording never shells out to git
        # on the event loop.
        self._version = version if version is not None else backend_version()
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self._conn.execute("PRAGMA busy_timeout = 5000")
        try:
            # WAL lets an on-demand Datasette read alongside the running backend.
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError:
            pass
        self._conn.executescript(SCHEMA)
        self._conn.executescript(AVAILABILITY_SCHEMA)
        self.availability = Availability(lambda: self._conn, clock)

    @property
    def version(self) -> str:
        return self._version

    # ------------------------------------------------------------------ #
    # Recording
    # ------------------------------------------------------------------ #
    def record(
        self,
        kind: str,
        code: str,
        message: str,
        *,
        client_id: str | None = None,
        device_udid: str | None = None,
        device_name: str | None = None,
        session_id: int | None = None,
        session_state: str | None = None,
        request: dict | None = None,
        context: dict | None = None,
        exception_type: str | None = None,
        traceback: str | None = None,
        with_log: bool = False,
    ) -> dict | None:
        """Record a fault, rejection or cap trip; returns ``{id, code, remedy}``
        or None when recording failed (OBS-08)."""
        try:
            return self._record(
                kind, code, message, client_id, device_udid, device_name,
                session_id, session_state, request, context, exception_type,
                traceback, with_log,
            )
        except Exception:  # noqa: BLE001
            log.exception("could not record incident %s (%s)", code, kind)
            return None

    def _record(
        self, kind, code, message, client_id, device_udid, device_name,
        session_id, session_state, request, context, exception_type,
        traceback, with_log,
    ) -> dict:
        if not catalogue.is_known(code):
            log.warning("unknown incident code %r; recording as unexpected", code)
            code = catalogue.UNEXPECTED
        now = self.clock()
        exception_type = _cut(exception_type, MAX_SHORT)

        # Collapse (OBS-06): same kind, code, client and device, seen < 10 min ago.
        sql = (
            "SELECT id FROM incidents WHERE source = 'backend' AND kind = ? "
            "AND code = ? AND client_id IS ? AND device_udid IS ? AND last_seen > ?"
        )
        args: list = [kind, code, client_id, device_udid, now - COLLAPSE_WINDOW_S]
        if code == catalogue.UNEXPECTED:
            sql += " AND exception_type IS ?"
            args.append(exception_type)
        sql += " ORDER BY last_seen DESC, id DESC LIMIT 1"
        row = self._conn.execute(sql, args).fetchone()
        if row is not None:
            self._conn.execute(
                "UPDATE incidents SET count = count + 1, last_seen = ? WHERE id = ?",
                (now, row[0]),
            )
            return self._ref(row[0], code)

        remedy = catalogue.remedy_for(code)
        req = request or {}
        lines = None
        if with_log and self._log_buffer is not None:
            lines = json.dumps(
                [_cut(l, MAX_LOG_LINE) for l in self._log_buffer.lines()[-MAX_LOG_LINES:]]
            )
        detail = req.get("detail")
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, default=str)
        cur = self._conn.execute(
            "INSERT INTO incidents (kind, code, remedy, source, message, first_seen, "
            "last_seen, count, client_id, device_udid, device_name, session_id, "
            "session_state, backend_version, request_method, request_path, "
            "request_query, response_status, response_detail, exception_type, "
            "traceback, log_lines, context) "
            "VALUES (?, ?, ?, 'backend', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind, code, remedy, _cut(message, MAX_MESSAGE), now, now,
                client_id, device_udid, device_name, session_id, session_state,
                self.version, req.get("method"), _cut(req.get("path"), MAX_PATH),
                _cut(req.get("query"), MAX_QUERY), req.get("status"),
                _cut(detail, MAX_DETAIL), exception_type,
                _cut(traceback, MAX_TRACEBACK), lines,
                json.dumps(context, default=str) if context else None,
            ),
        )
        return self._ref(cur.lastrowid, code)

    def add_client_failure(
        self,
        *,
        report_id: str,
        code: str,
        message: str,
        started_at: float,
        ended_at: float,
        attempts: int,
        app_build: str,
        os_version: str,
        client_id: str | None,
        device_udid: str | None,
        device_name: str | None,
        offset_s: float,
        client_times: tuple[str, str],
        sent_at: str,
    ) -> dict:
        """Store one reported client failure (OBS-04). ``started_at`` and
        ``ended_at`` are already on the host's clock. Raises on a storage error
        so the client keeps the report queued."""
        now = self.clock()
        context = {
            "client_started_at": client_times[0],
            "client_ended_at": client_times[1],
            "sent_at": sent_at,
            "received_at": iso(now),
            "clock_offset_s": round(offset_s, 3),
        }
        cur = self._conn.execute(
            "INSERT INTO incidents (kind, code, remedy, source, message, first_seen, "
            "last_seen, count, client_id, device_udid, device_name, backend_version, "
            "attempts, app_build, os_version, report_id, context) "
            "VALUES ('client_failure', ?, ?, 'client', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code, catalogue.remedy_for(code), _cut(message, MAX_MESSAGE),
                started_at, ended_at, client_id, device_udid, device_name,
                self.version, attempts, _cut(app_build, MAX_SHORT),
                _cut(os_version, MAX_SHORT), report_id, json.dumps(context),
            ),
        )
        return self._ref(cur.lastrowid, code)

    def has_report(self, report_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM incidents WHERE report_id = ?", (report_id,)
        ).fetchone() is not None

    @staticmethod
    def _ref(incident_id: int, code: str) -> dict:
        return {"id": incident_id, "code": code, "remedy": catalogue.remedy_for(code)}

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def get(self, incident_id: int) -> dict | None:
        cur = self._conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        row = cur.fetchone()
        if row is None:
            return None
        r = dict(zip([d[0] for d in cur.description], row))
        code = r["code"]
        ctx = json.loads(r["context"]) if r["context"] else {}
        out = {
            "id": r["id"],
            "kind": r["kind"],
            "code": code,
            "remedy": catalogue.remedy_for(code) if catalogue.is_known(code) else r["remedy"],
            "source": r["source"],
            "message": r["message"],
            "first_seen": iso(r["first_seen"]),
            "last_seen": iso(r["last_seen"]),
            "count": r["count"],
            "client_id": r["client_id"],
            "device_udid": r["device_udid"],
            "device_name": r["device_name"],
            "session_id": r["session_id"],
            "session_state": r["session_state"],
            "backend_version": r["backend_version"],
            "request": None,
            "session": None,
            "exception_type": r["exception_type"],
            "traceback": r["traceback"],
            "log": json.loads(r["log_lines"]) if r["log_lines"] else None,
            "client_failure": None,
            "host_during_outage": None,
        }
        if r["request_method"] is not None:
            out["request"] = {
                "method": r["request_method"],
                "path": r["request_path"],
                "query": r["request_query"],
                "status": r["response_status"],
                "detail": r["response_detail"],
            }
        if r["kind"] in (catalogue.FAULT, catalogue.CAP_TRIP) and ctx:
            out["session"] = ctx
        if r["kind"] == catalogue.CLIENT_FAILURE:
            out["client_failure"] = {
                "started_at": iso(r["first_seen"]),
                "ended_at": iso(r["last_seen"]),
                "attempts": r["attempts"],
                "app_build": r["app_build"],
                "os_version": r["os_version"],
                **ctx,
            }
            out["host_during_outage"] = self.availability.host_during(
                r["first_seen"], r["last_seen"]
            )
        return out

    def list(
        self,
        flt: IncidentFilter | None = None,
        limit: int = 100,
        before: str | None = None,
    ) -> tuple[list[dict], str | None]:
        where, args = (flt or IncidentFilter()).where()
        if before:
            ts, _, iid = before.partition(":")
            where += " AND (last_seen < ? OR (last_seen = ? AND id < ?))"
            args += [float(ts), float(ts), int(iid)]
        rows = self._conn.execute(
            f"SELECT {_LIST_COLS} FROM incidents WHERE {where} "
            "ORDER BY last_seen DESC, id DESC LIMIT ?",
            [*args, limit + 1],
        ).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        next_before = f"{rows[-1][7]!r}:{rows[-1][0]}" if more and rows else None
        return [_list_item(r) for r in rows], next_before

    def summary(self, flt: IncidentFilter | None = None) -> list[dict]:
        where, args = (flt or IncidentFilter()).where()
        rows = self._conn.execute(
            "SELECT code, COUNT(*), SUM(count), MAX(last_seen) FROM incidents "
            f"WHERE {where} GROUP BY code ORDER BY SUM(count) DESC, code",
            args,
        ).fetchall()
        return [
            {
                "code": r[0],
                "remedy": catalogue.remedy_for(r[0]),
                "incidents": r[1],
                "occurrences": r[2],
                "last_seen": iso(r[3]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # Retention (OBS-09)
    # ------------------------------------------------------------------ #
    def prune(self) -> int:
        """Delete incidents and availability spans last seen > 30 days ago."""
        cutoff = self.clock() - RETENTION_S
        n = self._conn.execute(
            "DELETE FROM incidents WHERE last_seen < ?", (cutoff,)
        ).rowcount
        self.availability.prune(cutoff)
        return n
