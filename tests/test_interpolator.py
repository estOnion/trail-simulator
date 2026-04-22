from __future__ import annotations

import random

from geographiclib.geodesic import Geodesic

from trail_simulator.routing.interpolator import GaitParams, interpolate_route


GEOD = Geodesic.WGS84


def _dist(a, b):
    return GEOD.Inverse(a[0], a[1], b[0], b[1])["s12"]


# Params that disable the stochastic features for deterministic pacing tests.
DET = GaitParams(
    gait_sigma=0.0,
    gait_clip=0.0,
    pause_probability_per_tick=0.0,
    pause_ticks_range=(0, 0),
    perpendicular_jitter_m=0.0,
)


def test_pacing_roughly_matches_speed_deterministic():
    start = (25.0375, 121.5637)  # Taipei
    d = GEOD.Direct(start[0], start[1], 90, 1000)  # 1 km east
    end = (d["lat2"], d["lon2"])
    polyline = [start, end]

    waypoints = list(
        interpolate_route(polyline, speed_kmh=5.0, tick_hz=1.0, gait=DET)
    )
    # 5 km/h = 1.388 m/s → ≈720 ticks over 1 km, plus start/end
    assert 710 <= len(waypoints) <= 740

    for i in range(1, len(waypoints) - 1):
        seg = _dist(
            (waypoints[i - 1].lat, waypoints[i - 1].lon),
            (waypoints[i].lat, waypoints[i].lon),
        )
        assert seg <= 1.8, f"step {i} too long: {seg}"


def test_implied_speed_never_exceeds_nominal():
    """With gait capped at max_factor=1.0, no step should imply > speed_kmh."""
    start = (25.0375, 121.5637)
    d = GEOD.Direct(start[0], start[1], 45, 600)
    end = (d["lat2"], d["lon2"])

    waypoints = list(
        interpolate_route(
            [start, end],
            speed_kmh=20.0,
            tick_hz=1.0,
            rng=random.Random(1),
            gait=GaitParams(perpendicular_jitter_m=0.6),
        )
    )
    tick_s = 1.0
    for i in range(1, len(waypoints) - 1):
        seg_m = _dist(
            (waypoints[i - 1].lat, waypoints[i - 1].lon),
            (waypoints[i].lat, waypoints[i].lon),
        )
        implied_kmh = seg_m / tick_s * 3.6
        # small headroom for wobble geometry
        assert implied_kmh <= 21.0, f"tick {i} implies {implied_kmh} km/h"


def test_pauses_are_produced():
    start = (25.0375, 121.5637)
    d = GEOD.Direct(start[0], start[1], 90, 500)
    end = (d["lat2"], d["lon2"])

    # high pause probability → at least a few pause ticks in 500m
    gait = GaitParams(
        gait_sigma=0.0, gait_clip=0.0,
        pause_probability_per_tick=0.1,
        pause_ticks_range=(2, 4),
        perpendicular_jitter_m=0.0,
    )
    wps = list(interpolate_route([start, end], 5.0, 1.0, rng=random.Random(42), gait=gait))

    # Count ticks whose distance from the previous tick is near-zero (pause).
    zero_steps = 0
    for i in range(1, len(wps)):
        seg = _dist((wps[i - 1].lat, wps[i - 1].lon), (wps[i].lat, wps[i].lon))
        if seg < 0.1:
            zero_steps += 1
    assert zero_steps >= 5, f"expected several pause ticks, got {zero_steps}"


def test_gait_variation_produces_varied_step_sizes():
    start = (25.0375, 121.5637)
    d = GEOD.Direct(start[0], start[1], 0, 500)
    end = (d["lat2"], d["lon2"])

    gait = GaitParams(
        gait_sigma=0.12, gait_clip=0.25,
        pause_probability_per_tick=0.0,
        perpendicular_jitter_m=0.0,
    )
    wps = list(interpolate_route([start, end], 5.0, 1.0, rng=random.Random(7), gait=gait))

    dists = [
        _dist((wps[i - 1].lat, wps[i - 1].lon), (wps[i].lat, wps[i].lon))
        for i in range(1, len(wps) - 1)
    ]
    # should have meaningful spread, not a flat ribbon of identical steps
    spread = max(dists) - min(dists)
    assert spread > 0.2, f"gait variation too tight: spread={spread}"
