from __future__ import annotations

import time

import pytest

from trail_simulator.config import cooldown_seconds_for_distance
from trail_simulator.safety.cooldown import evaluate_cooldown
from trail_simulator.session.controller import SessionController
from trail_simulator.session.store import Store


def test_travel_time_seconds():
    # Settle time = distance ÷ transit speed. 60 km/h = 16.667 m/s.
    assert cooldown_seconds_for_distance(0) == 0.0
    assert cooldown_seconds_for_distance(-5) == 0.0
    assert abs(cooldown_seconds_for_distance(60_000, 60.0) - 3600.0) < 1e-6   # 60 km = 1 h
    assert abs(cooldown_seconds_for_distance(100_000, 60.0) - 6000.0) < 1e-6
    assert abs(cooldown_seconds_for_distance(60_000, 120.0) - 1800.0) < 1e-6  # 2x speed = ½ time
    assert cooldown_seconds_for_distance(1000, 0) == 0.0               # guard: no speed


def test_no_prior_fix_allows():
    d = evaluate_cooldown(None, None, None, 35.0, 139.0)
    assert d.allowed
    assert d.required_wait_s == 0


def test_small_jump_clears_quickly():
    now = 1_000_000.0
    # ~14 m jump → sub-second travel time; 10 s elapsed clears it.
    d = evaluate_cooldown(35.0, 139.0, now - 10.0, 35.0001, 139.0001, now_ts=now)
    assert d.allowed
    assert d.jump_km < 0.1


def test_large_jump_requires_cooldown():
    now = 1_000_000.0
    # ~100 km north, only 60 s elapsed → blocked.
    d = evaluate_cooldown(35.0, 139.0, now - 60.0, 35.9, 139.0, now_ts=now)
    assert not d.allowed
    assert d.required_wait_s > 0
    assert d.jump_km >= 90


def test_large_jump_cooldown_expires():
    now = 1_000_000.0
    # 100 km at 60 km/h ≈ 6000 s; waiting 2 h clears it.
    d = evaluate_cooldown(35.0, 139.0, now - 7200.0, 35.9, 139.0, now_ts=now)
    assert d.allowed


def test_transit_speed_override():
    now = 1_000_000.0
    # 10 s elapsed: at 60 km/h a 100 km jump needs ~6000 s → still blocked;
    # at 100000 km/h it needs ~3.6 s → already cleared.
    slow = evaluate_cooldown(35.0, 139.0, now - 10.0, 35.9, 139.0, now_ts=now, transit_kmh=60.0)
    assert not slow.allowed
    fast = evaluate_cooldown(35.0, 139.0, now - 10.0, 35.9, 139.0, now_ts=now, transit_kmh=100_000.0)
    assert fast.allowed


class _FakeDevice:
    async def open(self): ...
    async def set(self, lat, lon): ...
    async def clear(self): ...


@pytest.mark.asyncio
async def test_blocked_start_sets_counting_down_cooldown(tmp_path):
    """A blocked start arms a live cooldown that status() reports decreasing
    against wall-clock — the bug was it never counted down."""
    store = Store(tmp_path / "t.db")
    store.set_last_fix(35.0, 139.0)  # phone "currently" at last spoof point
    c = SessionController(_FakeDevice(), store)

    # 100 km jump → blocked, required_wait_s > 0.
    decision = await c.start(35.9, 139.0, [(36.0, 139.0)], speed_kmh=5.0)
    assert not decision.allowed
    first = c.status().cooldown_remaining_s
    assert first > 0

    # Rewind the expiry instant → remaining must shrink (it counts down).
    c._cooldown_until -= 30.0
    assert c.status().cooldown_remaining_s < first


@pytest.mark.asyncio
async def test_successful_start_clears_pending_cooldown(tmp_path):
    """An armed cooldown must not outlive the start that overrides it."""
    store = Store(tmp_path / "t.db")
    store.set_last_fix(35.0, 139.0)
    c = SessionController(_FakeDevice(), store)

    assert not (await c.start(35.9, 139.0, [(36.0, 139.0)], speed_kmh=5.0)).allowed
    assert c.status().cooldown_remaining_s > 0

    decision = await c.start(
        35.9, 139.0, [(36.0, 139.0)], speed_kmh=5.0, skip_cooldown=True
    )
    try:
        assert decision.allowed
        assert c.status().cooldown_remaining_s == 0.0
    finally:
        c._task.cancel()  # don't let the run loop reach the router


@pytest.mark.asyncio
async def test_skip_cooldown_reports_the_jump_it_waved_through(tmp_path):
    store = Store(tmp_path / "t.db")
    store.set_last_fix(35.0, 139.0)
    c = SessionController(_FakeDevice(), store)

    decision = await c.start(
        35.9, 139.0, [(36.0, 139.0)], speed_kmh=5.0, skip_cooldown=True
    )
    try:
        assert decision.allowed
        assert decision.required_wait_s == 0.0
        assert decision.jump_km >= 90  # the override still measures the distance
    finally:
        c._task.cancel()


@pytest.mark.asyncio
async def test_expired_cooldown_reports_zero_not_negative(tmp_path):
    """Once the instant passes, remaining clamps at 0 — it must not go negative."""
    c = SessionController(_FakeDevice(), Store(tmp_path / "t.db"))
    c._cooldown_until = time.time() - 500.0

    assert c.status().cooldown_remaining_s == 0.0


def test_clear_last_fix_removes_the_stored_point(tmp_path):
    store = Store(tmp_path / "t.db")
    store.set_last_fix(35.0, 139.0)
    assert store.get_last_fix() is not None

    store.clear_last_fix()
    assert store.get_last_fix() is None

    store.clear_last_fix()  # idempotent: clearing an empty table is fine
    assert store.get_last_fix() is None


@pytest.mark.asyncio
async def test_reset_clears_last_fix(tmp_path):
    """Releasing to real GPS drops the stale spoof point so the next start
    isn't measured against a phantom position."""
    store = Store(tmp_path / "t.db")
    store.set_last_fix(35.0, 139.0)
    c = SessionController(_FakeDevice(), store)
    c._cooldown_until = 9_999_999_999.0

    await c.reset_device()

    assert store.get_last_fix() is None
    assert c.status().cooldown_remaining_s == 0.0
