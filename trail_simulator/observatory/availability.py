"""Host availability spans (OBS-10, OBS-11, ADR-0047).

A span opens at startup; its ``last_alive`` is refreshed about once a minute;
a gap of more than ``GAP_S`` since the last refresh starts a new span (the host
slept or froze); a clean shutdown marks the span ended cleanly.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Callable

HEARTBEAT_S = 60.0
GAP_S = 180.0
# An unclean span's last_alive can lag the real end by up to a heartbeat, so
# credit that much when judging whether the host was up.
GRACE_S = HEARTBEAT_S

SCHEMA = """
CREATE TABLE IF NOT EXISTS availability_spans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     REAL NOT NULL,
    last_alive     REAL NOT NULL,
    ended_cleanly  INTEGER NOT NULL DEFAULT 0
);
"""


class Availability:
    def __init__(self, conn: Callable[[], sqlite3.Connection], clock: Callable[[], float] = time.time):
        self._conn_fn = conn
        self._clock = clock
        self._current: int | None = None

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._conn_fn()

    def start(self) -> int:
        """Open a new span now (startup, or after a gap)."""
        now = self._clock()
        cur = self._conn.execute(
            "INSERT INTO availability_spans (started_at, last_alive, ended_cleanly) "
            "VALUES (?, ?, 0)",
            (now, now),
        )
        self._current = cur.lastrowid
        return self._current

    def beat(self) -> None:
        """Refresh the open span, or split on a gap of more than GAP_S."""
        now = self._clock()
        if self._current is None:
            self.start()
            return
        row = self._conn.execute(
            "SELECT last_alive FROM availability_spans WHERE id = ?", (self._current,)
        ).fetchone()
        if row is None or now - row[0] > GAP_S:
            self.start()
            return
        self._conn.execute(
            "UPDATE availability_spans SET last_alive = ? WHERE id = ?",
            (now, self._current),
        )

    def shutdown(self) -> None:
        """Mark the open span as ended cleanly."""
        if self._current is None:
            return
        self._conn.execute(
            "UPDATE availability_spans SET last_alive = ?, ended_cleanly = 1 WHERE id = ?",
            (self._clock(), self._current),
        )
        self._current = None

    def prune(self, cutoff: float) -> int:
        cur = self._conn.execute(
            "DELETE FROM availability_spans WHERE last_alive < ?", (cutoff,)
        )
        return cur.rowcount

    def spans(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, started_at, last_alive, ended_cleanly "
            "FROM availability_spans ORDER BY started_at, id"
        ).fetchall()
        return [
            {"id": r[0], "started_at": r[1], "last_alive": r[2], "ended_cleanly": bool(r[3])}
            for r in rows
        ]

    def host_during(self, start: float, end: float) -> str:
        """'up' if the host was running for the whole interval, 'down' if for
        none of it, else 'partly'. Judged from the spans (OBS-11)."""
        if end < start:
            start, end = end, start
        now = self._clock()
        covers: list[tuple[float, float]] = []
        spans = self.spans()
        for i, s in enumerate(spans):
            if s["id"] == self._current:
                hi = max(now, s["last_alive"])
            elif s["ended_cleanly"]:
                hi = s["last_alive"]
            else:
                hi = s["last_alive"] + GRACE_S
                if i + 1 < len(spans):
                    hi = min(hi, spans[i + 1]["started_at"])
            covers.append((s["started_at"], hi))
        covers.sort()
        merged: list[list[float]] = []
        for lo, hi in covers:
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        if end == start:
            return "up" if any(lo <= start <= hi for lo, hi in merged) else "down"
        overlap = sum(max(0.0, min(end, hi) - max(start, lo)) for lo, hi in merged)
        if overlap <= 0:
            return "down"
        if overlap >= (end - start) - 1e-6:
            return "up"
        return "partly"
