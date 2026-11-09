"""Faults and cap trips recorded by the session controller (OBS-01, OBS-03)."""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging

import httpx
import polyline as polyline_lib
import pytest

import trail_simulator.session.controller as controller_mod
from trail_simulator.device.injector import DeviceUnavailable
from trail_simulator.observatory.journal import Journal
from trail_simulator.observatory.logbuffer import LogRingBuffer
from trail_simulator.routing import osrm
from trail_simulator.routing.osrm import RouteError
from trail_simulator.session.controller import SessionController, SessionState
from trail_simulator.session.store import Store

POLY = [(0.0, 0.0), (0.0, 0.00001), (0.0, 0.00002)]


class FakeDevice:
    def __init__(self, fail_on_set=None):
        self.set_calls = 0
        self.fail_on_set = fail_on_set
        self.clear_count = 0

    async def open(self): pass

    async def set(self, lat, lon):
        self.set_calls += 1
        if self.fail_on_set is not None and self.set_calls >= 2:
            raise self.fail_on_set

    async def clear(self):
        self.clear_count += 1

    async def reachable(self):
        return True


class FakeIdentity:
    def for_udid(self, udid, client_id=None):
        return {
            "client_id": "uuid-1", "device_udid": udid, "device_name": "Jack",
            "session_id": None, "session_state": None,
        }


@pytest.fixture
def rig(tmp_path, monkeypatch):
    fast = dataclasses.replace(controller_mod.SETTINGS, tick_hz=40.0)
    monkeypatch.setattr(controller_mod, "SETTINGS", fast)

    async def route(a, b, c, d):
        return list(POLY)

    monkeypatch.setattr(controller_mod, "fetch_walking_route", route)

    buf = LogRingBuffer()
    lg = logging.getLogger("trail_simulator")
    lg.addHandler(buf)
    store = Store(tmp_path / "t.db")
    journal = Journal(tmp_path / "t.db", log_buffer=buf, version="test")

    def make(device):
        return SessionController(
            device, store, udid="UDID-A", journal=journal, identity=FakeIdentity()
        )

    yield make, journal
    lg.removeHandler(buf)


async def _run_to_end(c):
    await asyncio.wait_for(c._task, timeout=3.0)


def _only(journal, kind):
    items = [i for i in journal.list()[0] if i["kind"] == kind]
    assert len(items) == 1, items
    return journal.get(items[0]["id"])


@pytest.mark.asyncio
async def test_no_route_records_one_fault_with_context(rig, monkeypatch):
    make, journal = rig

    async def no_route(a, b, c, d):
        raise RouteError("no walking route (OSRM: NoRoute)", code="route.no_route")

    monkeypatch.setattr(controller_mod, "fetch_walking_route", no_route)
    logging.getLogger("trail_simulator.test").warning("planning the walk")
    c = make(FakeDevice())
    c._store.set_last_fix(1.0, 2.0)

    await c.start(0.0, 0.0, [(0.0, 0.001), (0.0, 0.002)], speed_kmh=4.0, loop=True, skip_cooldown=True)
    await _run_to_end(c)

    assert c._state == SessionState.error
    row = _only(journal, "fault")
    assert row["code"] == "route.no_route"
    assert row["source"] == "backend"
    assert row["message"] == c._last_error and row["message"].startswith("route: ")
    assert row["client_id"] == "uuid-1" and row["device_name"] == "Jack"
    assert row["session_id"] == c._session_id and row["session_state"] == "error"
    assert row["session"]["origin"] == [0.0, 0.0]
    assert row["session"]["destinations"] == [[0.0, 0.001], [0.0, 0.002]]
    assert row["session"]["speed_kmh"] == 4.0
    assert row["session"]["loop"] is True
    assert row["session"]["last_fix"][:2] == [1.0, 2.0]
    assert row["traceback"] is None
    assert any("planning the walk" in l for l in row["log"])  # lead-up log
    snap = c.status()
    assert snap.last_incident == {
        "id": row["id"], "code": "route.no_route", "remedy": row["remedy"],
    }
    assert snap.last_error == row["message"]


@pytest.mark.asyncio
async def test_router_failing_twice_records_one_service_down_fault(rig, monkeypatch):
    """RTE-13: both attempts fail, the session sees one RouteError, one incident."""
    make, journal = rig
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        osrm.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(
        controller_mod, "fetch_walking_route",
        functools.partial(osrm.fetch_walking_route, base="http://osrm", retry_delay_s=0),
    )
    c = make(FakeDevice())

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0, skip_cooldown=True)
    await _run_to_end(c)

    assert len(requests) == 2
    assert c._state == SessionState.error
    row = _only(journal, "fault")
    assert row["code"] == "route.service_down"
    assert "timed out after 15 s" in row["message"] and "tried twice" in row["message"]
    assert c.status().last_incident["code"] == "route.service_down"
    assert c.status().last_incident["id"] == row["id"]


_OK_BODY = {
    "code": "Ok",
    "routes": [{"geometry": polyline_lib.encode([(0.0, 0.0), (0.0, 0.001), (0.0, 0.002)])}],
}


@pytest.mark.asyncio
async def test_router_blip_walks_and_records_no_incident(rig, monkeypatch):
    """RTE-13 blip: first request times out, second answers Ok; the walk starts."""
    make, journal = rig
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("")
        return httpx.Response(200, json=_OK_BODY)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        osrm.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(
        controller_mod, "fetch_walking_route",
        functools.partial(osrm.fetch_walking_route, base="http://osrm", retry_delay_s=0),
    )
    c = make(FakeDevice())

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0, skip_cooldown=True)
    for _ in range(100):
        if c._state == SessionState.running:
            break
        await asyncio.sleep(0.02)

    assert c._state == SessionState.running
    assert len(requests) == 2
    assert journal.list()[0] == []
    assert c.status().last_incident is None
    await c.stop()


@pytest.mark.asyncio
async def test_reset_clears_the_incident_reference(rig, monkeypatch):
    make, journal = rig

    async def no_route(a, b, c, d):
        raise RouteError("x", code="route.no_route")

    monkeypatch.setattr(controller_mod, "fetch_walking_route", no_route)
    c = make(FakeDevice())
    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)
    assert c.status().last_incident is not None

    await c.reset_device()

    snap = c.status()
    assert snap.last_error is None and snap.last_incident is None


@pytest.mark.asyncio
async def test_device_lost_mid_walk_records_a_device_fault(rig):
    make, journal = rig
    c = make(FakeDevice(fail_on_set=DeviceUnavailable("tunnel gone", code="device.tunnel_down")))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)
    await c.stop()  # cancels the auto-resume poll

    row = _only(journal, "fault")
    assert row["code"] == "device.tunnel_down"
    assert row["message"] == "device: tunnel gone"
    assert row["log"] is not None


@pytest.mark.asyncio
async def test_bare_transport_error_maps_to_connection_lost(rig):
    make, journal = rig
    c = make(FakeDevice(fail_on_set=OSError(49, "can't assign requested address")))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)
    await c.stop()

    assert _only(journal, "fault")["code"] == "device.connection_lost"


@pytest.mark.asyncio
async def test_uncoded_device_unavailable_maps_to_connection_lost(rig):
    make, journal = rig
    c = make(FakeDevice(fail_on_set=DeviceUnavailable("lost")))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)
    await c.stop()

    assert _only(journal, "fault")["code"] == "device.connection_lost"


@pytest.mark.asyncio
async def test_unclassified_crash_records_unexpected_with_traceback(rig):
    make, journal = rig
    c = make(FakeDevice(fail_on_set=ZeroDivisionError("boom")))

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)

    row = _only(journal, "fault")
    assert row["code"] == "unexpected"
    assert row["remedy"] is None
    assert row["exception_type"] == "ZeroDivisionError"
    assert "Traceback" in row["traceback"] and "boom" in row["traceback"]
    assert row["log"]


@pytest.mark.asyncio
async def test_failed_auto_resume_records_a_fault(rig, monkeypatch):
    make, journal = rig
    c = make(FakeDevice())
    real_sleep = asyncio.sleep

    async def quick(_s):
        await real_sleep(0)

    monkeypatch.setattr(controller_mod.asyncio, "sleep", quick)
    c._last_start_params = {
        "start_lat": 0.0, "start_lon": 0.0, "destinations": [(0.0, 0.001)],
        "speed_kmh": 4.0, "loop": False,
    }

    async def refuse(*a, **k):
        raise RuntimeError("cannot restart")

    monkeypatch.setattr(c, "start", refuse)

    await c._auto_resume()

    row = _only(journal, "fault")
    assert row["code"] == "session.auto_resume_failed"
    assert row["message"] == "auto-resume failed: cannot restart"
    assert c.status().last_incident["id"] == row["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patched,result,code",
    [
        ("check_speed", (False, 99.0), "safety.speed_cap"),
        ("check_tick_jump", (False, 9.0), "safety.jump_cap"),
    ],
)
async def test_cap_trips_are_recorded_while_the_walk_carries_on(rig, monkeypatch, patched, result, code):
    make, journal = rig
    if patched == "check_speed":
        monkeypatch.setattr(controller_mod, "check_speed", lambda *a, **k: result)
    else:
        # Only the jump cap should trip; let the speed check pass.
        monkeypatch.setattr(controller_mod, "check_speed", lambda *a, **k: (True, 1.0))
        monkeypatch.setattr(controller_mod, "check_tick_jump", lambda *a, **k: result)
    c = make(FakeDevice())

    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=20.0)
    await _run_to_end(c)

    assert c._state == SessionState.idle      # the walk finished, no error state
    row = _only(journal, "cap_trip")
    assert row["code"] == code
    assert row["count"] >= 2                  # repeated trips collapse into one
    assert row["log"] is None                 # ADR-0046: cap trips carry no lead-up log
    assert c.status().last_incident["code"] == code


@pytest.mark.asyncio
async def test_a_broken_journal_does_not_disturb_the_session(rig, monkeypatch):
    make, journal = rig

    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("disk full")

    journal._conn = Broken()

    async def no_route(a, b, c, d):
        raise RouteError("x", code="route.no_route")

    monkeypatch.setattr(controller_mod, "fetch_walking_route", no_route)
    c = make(FakeDevice())
    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)

    assert c._state == SessionState.error
    snap = c.status()
    assert snap.last_error.startswith("route: ") and snap.last_incident is None


@pytest.mark.asyncio
async def test_refused_start_never_pairs_the_cooldown_text_with_an_older_incident(rig, monkeypatch):
    make, journal = rig

    async def no_route(a, b, c, d):
        raise RouteError("x", code="route.no_route")

    monkeypatch.setattr(controller_mod, "fetch_walking_route", no_route)
    c = make(FakeDevice())
    await c.start(0.0, 0.0, [(0.0, 0.001)], speed_kmh=4.0)
    await _run_to_end(c)
    assert c.status().last_incident["code"] == "route.no_route"   # the older incident

    seen = []

    async def listener(snap):
        seen.append(snap)

    c.add_listener(listener)
    c._store.set_last_fix(0.0, 0.0)          # a far start now trips the cooldown
    decision = await c.start(50.0, 50.0, [(50.0, 50.001)], speed_kmh=4.0)

    assert not decision.allowed
    assert seen, "the refusal broadcasts a snapshot"
    first = seen[0]
    assert first.last_error == decision.reason
    assert first.last_incident is None        # not the stale route.no_route one
