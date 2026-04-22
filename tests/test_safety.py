from __future__ import annotations

from geographiclib.geodesic import Geodesic

from trail_simulator.safety.speed_cap import check_speed, implied_kmh
from trail_simulator.safety.tick_cap import check_tick_jump

GEOD = Geodesic.WGS84


def _east_of(lat, lon, meters):
    d = GEOD.Direct(lat, lon, 90, meters)
    return d["lat2"], d["lon2"]


def test_speed_cap_rejects_over_20():
    a = (35.0, 139.0)
    b = _east_of(*a, 10)  # 10 m in 1 s = 36 km/h
    ok, kmh = check_speed(a[0], a[1], b[0], b[1], dt_s=1.0, max_kmh=20.0)
    assert not ok
    assert 35.0 < kmh < 37.0


def test_speed_cap_accepts_under_20():
    a = (35.0, 139.0)
    b = _east_of(*a, 5)  # 5 m / 1 s = 18 km/h
    ok, kmh = check_speed(a[0], a[1], b[0], b[1], dt_s=1.0, max_kmh=20.0)
    assert ok
    assert 17 < kmh < 19


def test_tick_jump_rejects_over_5m():
    a = (35.0, 139.0)
    b = _east_of(*a, 5.5)
    ok, m = check_tick_jump(a[0], a[1], b[0], b[1], max_m=5.0)
    assert not ok
    assert 5.4 < m < 5.6


def test_tick_jump_accepts_4m():
    a = (35.0, 139.0)
    b = _east_of(*a, 4.0)
    ok, m = check_tick_jump(a[0], a[1], b[0], b[1], max_m=5.0)
    assert ok
