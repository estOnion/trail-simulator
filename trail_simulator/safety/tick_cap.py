from __future__ import annotations

from .speed_cap import distance_m


def check_tick_jump(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    max_m: float,
) -> tuple[bool, float]:
    m = distance_m(lat1, lon1, lat2, lon2)
    return (m <= max_m, m)
