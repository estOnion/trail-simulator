from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ..config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    start_lat    REAL NOT NULL,
    start_lon    REAL NOT NULL,
    end_lat      REAL NOT NULL,
    end_lon      REAL NOT NULL,
    speed_kmh    REAL NOT NULL,
    status       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS last_fix (
    id     INTEGER PRIMARY KEY CHECK (id = 1),
    lat    REAL NOT NULL,
    lon    REAL NOT NULL,
    ts     REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path = DB_PATH):
        self._path = path
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.executescript(SCHEMA)

    # ---- last fix (for cooldown) ----
    def get_last_fix(self) -> tuple[float, float, float] | None:
        row = self._conn.execute("SELECT lat, lon, ts FROM last_fix WHERE id = 1").fetchone()
        return row if row else None

    def set_last_fix(self, lat: float, lon: float, ts: float | None = None) -> None:
        ts = ts if ts is not None else time.time()
        self._conn.execute(
            "INSERT INTO last_fix (id, lat, lon, ts) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, ts=excluded.ts",
            (lat, lon, ts),
        )

    # ---- session rows ----
    def session_start(
        self,
        start_lat: float, start_lon: float,
        end_lat: float, end_lon: float,
        speed_kmh: float,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, start_lat, start_lon, end_lat, end_lon, speed_kmh, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'running')",
            (time.time(), start_lat, start_lon, end_lat, end_lon, speed_kmh),
        )
        return cur.lastrowid or 0

    def session_end(self, session_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at = ?, status = ? WHERE id = ?",
            (time.time(), status, session_id),
        )
