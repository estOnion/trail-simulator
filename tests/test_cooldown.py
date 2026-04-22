from __future__ import annotations

import time

from trail_simulator.config import cooldown_minutes_for_distance
from trail_simulator.safety.cooldown import evaluate_cooldown


def test_table_lookup():
    assert cooldown_minutes_for_distance(0) == 0.0
    assert cooldown_minutes_for_distance(0.5) == 0.0       # below 1km tier
    assert cooldown_minutes_for_distance(1.0) == 0.5
    assert cooldown_minutes_for_distance(10.0) == 8.0
    assert cooldown_minutes_for_distance(99.9) == 18.0      # still in 50km tier
    assert cooldown_minutes_for_distance(100.0) == 28.0
    assert cooldown_minutes_for_distance(1500.0) == 120.0
    assert cooldown_minutes_for_distance(99999.0) == 120.0  # capped at highest tier


def test_no_prior_fix_allows():
    d = evaluate_cooldown(None, None, None, 35.0, 139.0)
    assert d.allowed
    assert d.required_wait_s == 0


def test_small_jump_no_cooldown():
    now = 1_000_000.0
    d = evaluate_cooldown(35.0, 139.0, now - 10.0, 35.0001, 139.0001, now_ts=now)
    assert d.allowed
    assert d.jump_km < 0.1


def test_large_jump_requires_cooldown():
    now = 1_000_000.0
    # 100 km north
    d = evaluate_cooldown(35.0, 139.0, now - 60.0, 35.9, 139.0, now_ts=now)
    assert not d.allowed
    assert d.required_wait_s > 0
    assert d.jump_km >= 90


def test_large_jump_cooldown_expires():
    now = 1_000_000.0
    # 100 km tier = 28 min cooldown
    d = evaluate_cooldown(35.0, 139.0, now - 30 * 60, 35.9, 139.0, now_ts=now)
    assert d.allowed
