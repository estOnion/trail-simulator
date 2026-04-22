from __future__ import annotations

from geographiclib.geodesic import Geodesic

GEOD = Geodesic.WGS84


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return GEOD.Inverse(lat1, lon1, lat2, lon2)["s12"]


def implied_kmh(
    lat1: float, lon1: float, lat2: float, lon2: float, dt_s: float
) -> float:
    if dt_s <= 0:
        return float("inf")
    m = distance_m(lat1, lon1, lat2, lon2)
    return (m / dt_s) * 3.6


def check_speed(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    dt_s: float,
    max_kmh: float,
) -> tuple[bool, float]:
    kmh = implied_kmh(lat1, lon1, lat2, lon2, dt_s)
    return (kmh <= max_kmh, kmh)
