"""Host availability spans and outage explanation (OBS-10, OBS-11, HST-36)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.main import build_app
from trail_simulator.observatory import lifecycle
from trail_simulator.observatory.journal import Journal
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store

T0 = 1_800_000_000.0
HOUR = 3600.0


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal(tmp_path, clock):
    return Journal(tmp_path / "j.db", clock=clock, version="t")


def test_a_span_opens_at_startup_and_is_refreshed(journal, clock):
    av = journal.availability
    av.start()
    clock.t += 60
    av.beat()
    clock.t += 60
    av.beat()

    [span] = av.spans()
    assert span["started_at"] == T0
    assert span["last_alive"] == T0 + 120
    assert span["ended_cleanly"] is False


def test_a_gap_over_three_minutes_starts_a_new_span(journal, clock):
    av = journal.availability
    av.start()
    clock.t += 60
    av.beat()                      # last refresh at 02:01-ish
    last_refresh = clock.t
    clock.t += 4 * HOUR            # laptop slept
    av.beat()

    old, new = av.spans()
    assert old["last_alive"] == last_refresh and old["ended_cleanly"] is False
    assert new["started_at"] == last_refresh + 4 * HOUR


def test_a_gap_of_exactly_three_minutes_does_not_split(journal, clock):
    av = journal.availability
    av.start()
    clock.t += 180
    av.beat()
    assert len(av.spans()) == 1


def test_clean_shutdown_marks_the_span(journal, clock):
    av = journal.availability
    av.start()
    clock.t += 90
    av.shutdown()
    [span] = av.spans()
    assert span["ended_cleanly"] is True
    assert span["last_alive"] == T0 + 90


def test_restart_opens_a_new_span_after_a_crash(tmp_path, clock):
    j1 = Journal(tmp_path / "j.db", clock=clock, version="t")
    j1.availability.start()
    clock.t += 30
    j2 = Journal(tmp_path / "j.db", clock=clock, version="t")
    j2.availability.start()
    spans = j2.availability.spans()
    assert [s["ended_cleanly"] for s in spans] == [False, False]


def _slept(journal, clock):
    """Up 00:00-02:00, asleep until 06:00, up since."""
    av = journal.availability
    av.start()
    for minute in range(1, 121):   # refreshed every minute until 02:00
        clock.t = T0 + minute * 60
        av.beat()
    clock.t = T0 + 6 * HOUR
    av.beat()                      # new span begins at ~06:00
    for minute in range(1, 61):
        clock.t = T0 + 6 * HOUR + minute * 60
        av.beat()
    return av


def test_outage_with_host_up_throughout(journal, clock):
    av = _slept(journal, clock)
    assert av.host_during(T0 + 30 * 60, T0 + 35 * 60) == "up"
    assert av.host_during(T0 + 6.5 * HOUR, T0 + 6.6 * HOUR) == "up"


def test_outage_while_the_host_slept(journal, clock):
    av = _slept(journal, clock)
    assert av.host_during(T0 + 3 * HOUR, T0 + 5 * HOUR) == "down"


def test_outage_spanning_the_wake_up(journal, clock):
    av = _slept(journal, clock)
    assert av.host_during(T0 + 5 * HOUR, T0 + 6.2 * HOUR) == "partly"


def test_open_span_counts_as_up_until_now(journal, clock):
    journal.availability.start()
    clock.t += 10 * 60               # no heartbeat yet, but the host is running
    assert journal.availability.host_during(T0 + 60, T0 + 9 * 60) == "up"


def test_client_failure_incident_carries_the_explanation(journal, clock):
    av = _slept(journal, clock)
    ref = journal.add_client_failure(
        report_id="r1", code="client.unreachable", message="m",
        started_at=T0 + 3 * HOUR, ended_at=T0 + 4 * HOUR, attempts=5,
        app_build="1", os_version="18", client_id=None, device_udid=None,
        device_name=None, offset_s=0.0, client_times=("a", "b"), sent_at="s",
    )
    assert journal.get(ref["id"])["host_during_outage"] == "down"
    ref2 = journal.add_client_failure(
        report_id="r2", code="client.unreachable", message="m",
        started_at=T0 + 30 * 60, ended_at=T0 + 35 * 60, attempts=5,
        app_build="1", os_version="18", client_id=None, device_udid=None,
        device_name=None, offset_s=0.0, client_times=("a", "b"), sent_at="s",
    )
    assert journal.get(ref2["id"])["host_during_outage"] == "up"
    rej = journal.record("rejection", "safety.cooldown", "m")
    assert journal.get(rej["id"])["host_during_outage"] is None


# ---- background loops (HST-36) ----------------------------------------------
@pytest.mark.asyncio
async def test_heartbeat_loop_refreshes_the_span(journal, clock):
    journal.availability.start()
    calls = 0

    async def fake_sleep(s):
        nonlocal calls
        calls += 1
        if calls > 3:
            raise asyncio.CancelledError
        clock.t += s

    with pytest.raises(asyncio.CancelledError):
        await lifecycle.run_heartbeat(journal, 60.0, sleep=fake_sleep)

    [span] = journal.availability.spans()
    assert span["last_alive"] == T0 + 180


@pytest.mark.asyncio
async def test_sweep_loop_prunes_old_incidents(journal, clock):
    old = journal.record("rejection", "safety.cooldown", "m", client_id="old")
    clock.t += 31 * 86400
    calls = 0

    async def fake_sleep(s):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await lifecycle.run_sweep(journal, 86400.0, sleep=fake_sleep)

    assert journal.get(old["id"]) is None


def test_server_lifespan_opens_a_span_prunes_and_closes_cleanly(tmp_path, clock):
    store = Store(path=tmp_path / "s.db")
    journal = Journal(tmp_path / "s.db", clock=clock, version="t")
    old = journal.record("rejection", "safety.cooldown", "m")
    clock.t += 40 * 86400
    manager = SessionManager(device_factory=lambda u: object(), store=store)
    app = build_app(manager, DeviceRegistry(), journal=journal)

    with TestClient(app):
        spans = journal.availability.spans()
        assert len(spans) == 1 and spans[0]["ended_cleanly"] is False
        assert journal.get(old["id"]) is None          # pruned at startup
        clock.t += 30

    [span] = journal.availability.spans()
    assert span["ended_cleanly"] is True
    assert span["last_alive"] == clock.t
