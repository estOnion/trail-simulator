"""In-memory ring buffer of the backend's recent log lines (ADR-0046)."""
from __future__ import annotations

import logging
from collections import deque

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MAX_LINE = 2000


class LogRingBuffer(logging.Handler):
    """A logging handler that remembers the newest ``capacity`` formatted
    lines. It sees exactly what the configured log level lets through."""

    def __init__(self, capacity: int = 100) -> None:
        super().__init__(level=logging.NOTSET)
        self._lines: deque[str] = deque(maxlen=capacity)
        self.setFormatter(logging.Formatter(_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            return
        self._lines.append(line[:_MAX_LINE])

    def lines(self) -> list[str]:
        return list(self._lines)

    def install(self, logger: logging.Logger | None = None) -> "LogRingBuffer":
        target = logger or logging.getLogger()
        if self not in target.handlers:
            target.addHandler(self)
        return self
