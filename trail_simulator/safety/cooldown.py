from __future__ import annotations

import time
from dataclasses import dataclass

from ..config import cooldown_minutes_for_distance
from .speed_cap import distance_m


@dataclass(frozen=True)
class CooldownDecision:
    allowed: bool
    required_wait_s: float
    jump_km: float
    reason: str


def evaluate_cooldown(
    last_lat: float | None,
    last_lon: float | None,
    last_fix_ts: float | None,
    next_lat: float,
    next_lon: float,
    now_ts: float | None = None,
) -> CooldownDecision:
    """Decide if an instantaneous reposition to (next_lat, next_lon) is allowed
    given the last known fix. Only applied at the *start* of a session — not
    every tick — since within a walking session each tick is sub-5m."""
    now = now_ts if now_ts is not None else time.time()

    if last_lat is None or last_lon is None or last_fix_ts is None:
        return CooldownDecision(True, 0.0, 0.0, "no prior fix")

    m = distance_m(last_lat, last_lon, next_lat, next_lon)
    km = m / 1000.0
    needed_min = cooldown_minutes_for_distance(km)
    needed_s = needed_min * 60.0
    elapsed_s = max(0.0, now - last_fix_ts)

    if elapsed_s >= needed_s:
        return CooldownDecision(
            True, 0.0, km, f"{km:.2f}km jump, cooldown satisfied"
        )

    remaining = needed_s - elapsed_s
    mm = int(remaining // 60)
    ss = int(remaining % 60)
    return CooldownDecision(
        False,
        remaining,
        km,
        f"{km:.1f}km jump needs {needed_min:.0f}min cooldown — wait {mm}m{ss}s",
    )
