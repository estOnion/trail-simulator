from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterator

from geographiclib.geodesic import Geodesic

GEOD = Geodesic.WGS84


@dataclass(frozen=True)
class Waypoint:
    lat: float
    lon: float
    seq: int
    t_offset_s: float


@dataclass(frozen=True)
class GaitParams:
    """Controls how 'human' the walk looks.

    - gait_sigma: std-dev of per-tick speed multiplier around 1.0 (smoothed).
    - gait_clip:  hard clip around 1.0; we also clip so nominal * factor
                  never exceeds the user-chosen speed (safety).
    - pause_probability_per_tick: chance per tick to start a brief stop.
    - pause_ticks_range: inclusive min..max duration of a stop, in ticks.
    - perpendicular_jitter_m: small side-to-side wobble, Gaussian-truncated.
    """
    gait_sigma: float = 0.08
    gait_clip: float = 0.25           # ±25 % around nominal
    pause_probability_per_tick: float = 0.008
    pause_ticks_range: tuple[int, int] = (2, 6)
    perpendicular_jitter_m: float = 0.6


def _segment_length_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return GEOD.Inverse(p1[0], p1[1], p2[0], p2[1])["s12"]


def _point_on_segment(
    p1: tuple[float, float],
    p2: tuple[float, float],
    distance_m: float,
) -> tuple[tuple[float, float], float]:
    """Return (lat, lon) at `distance_m` from p1 along great-circle toward p2,
    and the forward azimuth at that point."""
    g = GEOD.Inverse(p1[0], p1[1], p2[0], p2[1])
    out = GEOD.Direct(p1[0], p1[1], g["azi1"], distance_m)
    return (out["lat2"], out["lon2"]), g["azi1"]


def interpolate_route(
    polyline: list[tuple[float, float]],
    speed_kmh: float,
    tick_hz: float,
    jitter_m: float = 0.0,   # retained for backward-compat; ignored
    rng: random.Random | None = None,
    gait: GaitParams | None = None,
) -> Iterator[Waypoint]:
    """Yield Waypoints along `polyline` that look like a real walker:

    - gait varies smoothly around the nominal speed
    - occasional brief pauses (e.g. traffic lights)
    - slight perpendicular wobble (gait sway, not GPS noise)

    Never emits a step whose implied speed exceeds `speed_kmh`, so downstream
    safety gates stay satisfied.
    """
    if len(polyline) < 2:
        raise ValueError("polyline must have at least 2 points")
    if speed_kmh <= 0 or tick_hz <= 0:
        raise ValueError("speed_kmh and tick_hz must be positive")

    rng = rng or random.Random()
    g = gait or GaitParams()

    speed_mps = speed_kmh * 1000.0 / 3600.0
    base_step = speed_mps / tick_hz
    # Hard ceiling so factor*base_step never exceeds the nominal step
    # (interpolator must stay below user's max speed & the tick-cap gate).
    max_factor = 1.0
    min_factor = max(0.1, 1.0 - g.gait_clip)

    seg_lens = [
        _segment_length_m(polyline[i], polyline[i + 1])
        for i in range(len(polyline) - 1)
    ]
    total = sum(seg_lens)
    if total <= 0:
        return

    # Emit start.
    seq = 0
    t = 0.0
    yield Waypoint(polyline[0][0], polyline[0][1], seq, t)
    seq += 1
    t += 1.0 / tick_hz

    gait_factor = 1.0
    idx = 0
    seg_consumed = 0.0
    travelled = 0.0
    pause_remaining = 0

    while travelled < total:
        # --- pause ticks: stand still (emit current position again) ---
        if pause_remaining > 0:
            into_seg = travelled - seg_consumed
            (lat, lon), _ = _point_on_segment(polyline[idx], polyline[idx + 1], into_seg)
            if g.perpendicular_jitter_m > 0:
                lat, lon = _wobble(lat, lon, rng, g.perpendicular_jitter_m * 0.4)
            yield Waypoint(lat, lon, seq, t)
            seq += 1
            t += 1.0 / tick_hz
            pause_remaining -= 1
            continue

        # --- update smoothed gait factor (mean-reverting random walk) ---
        gait_factor += rng.gauss(0.0, g.gait_sigma)
        gait_factor = 0.85 * gait_factor + 0.15 * 1.0  # pull toward 1.0
        gait_factor = max(min_factor, min(max_factor, gait_factor))

        # --- maybe start a pause ---
        if rng.random() < g.pause_probability_per_tick:
            pause_remaining = rng.randint(*g.pause_ticks_range)
            continue  # the next loop iter emits the pause tick

        step = base_step * gait_factor
        target = travelled + step
        if target >= total:
            break

        # advance segment index
        while idx < len(seg_lens) and seg_consumed + seg_lens[idx] < target:
            seg_consumed += seg_lens[idx]
            idx += 1
        if idx >= len(seg_lens):
            break

        into_seg = target - seg_consumed
        (lat, lon), bearing = _point_on_segment(
            polyline[idx], polyline[idx + 1], into_seg
        )

        # perpendicular (side-to-side) wobble only — feels like gait sway, not teleport
        if g.perpendicular_jitter_m > 0:
            # truncated Gaussian: |d| <= jitter_m
            d = rng.gauss(0.0, g.perpendicular_jitter_m / 2.0)
            if d > g.perpendicular_jitter_m:
                d = g.perpendicular_jitter_m
            if d < -g.perpendicular_jitter_m:
                d = -g.perpendicular_jitter_m
            perp_bearing = bearing + (90.0 if d >= 0 else -90.0)
            out = GEOD.Direct(lat, lon, perp_bearing, abs(d))
            lat, lon = out["lat2"], out["lon2"]

        yield Waypoint(lat, lon, seq, t)
        seq += 1
        t += 1.0 / tick_hz
        travelled = target

    # Emit final destination exactly.
    yield Waypoint(polyline[-1][0], polyline[-1][1], seq, t)


def _wobble(
    lat: float, lon: float, rng: random.Random, max_m: float
) -> tuple[float, float]:
    bearing = rng.uniform(0, 360)
    d = abs(rng.gauss(0, max_m / 2.0))
    if d > max_m:
        d = max_m
    out = GEOD.Direct(lat, lon, bearing, d)
    return out["lat2"], out["lon2"]
