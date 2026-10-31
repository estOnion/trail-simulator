"""Rejections are recorded and answered with an incident reference
(OBS-02, API-03, API-29)."""
from __future__ import annotations

import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import trail_simulator.session.controller as controller_mod
from trail_simulator.api.ws import build_ws_router
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.main import build_app
from trail_simulator.observatory.journal import Journal
from trail_simulator.observatory.logbuffer import LogRingBuffer
from trail_simulator.routing.osrm import RouteError
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store

HEADERS = {"X-Client-Id": "uuid-1"}
FAR_START = {"start_lat": 35.9, "start_lon": 139.0}
DESTS = [{"lat": 36.0, "lon": 139.0}]


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass
    async def reachable(self): return True


def _make(tmp_path, devices=(("UDID-A", "Jack"),), buffer=None):
    store = Store(path=tmp_path / "s.db")
    store.set_last_fix(35.0, 139.0)
    registry = DeviceRegistry()
    for udid, name in devices:
        registry.register(udid=udid, name=name)
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    journal = Journal(tmp_path / "s.db", log_buffer=buffer, version="test")
    app = build_app(manager, registry, journal=journal)

    @app.get("/api/boom")
    async def boom():
        raise ValueError("kaboom")

    @app.get("/boom")
    async def boom_outside_api():
        raise ValueError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    return client, journal, manager, registry


def _start(client, **extra):
    return client.post(
        "/api/session",
        json={**FAR_START, "destinations": DESTS, "speed_kmh": 5.0, **extra},
        headers=HEADERS,
    )


def _all(journal):
    return journal.list()[0]


def test_cooldown_refusal_records_one_rejection_referenced_by_body_and_snapshot(tmp_path):
    client, journal, _, _ = _make(tmp_path)

    r = _start(client)

    assert r.status_code == 429
    body = r.json()
    assert body["detail"]["cooldown"] is True            # object shape kept
    ref = body["incident"]
    assert ref["code"] == "safety.cooldown"
    assert ref["remedy"]
    items = _all(journal)
    assert [(i["id"], i["code"], i["kind"]) for i in items] == [
        (ref["id"], "safety.cooldown", "rejection")
    ]
    snap = client.get("/api/status", headers=HEADERS).json()
    assert snap["last_incident"] == ref

    client.post("/api/reset", headers=HEADERS)
    assert client.get("/api/status", headers=HEADERS).json()["last_incident"] is None


def test_rejection_stores_request_response_and_client(tmp_path):
    client, journal, _, _ = _make(tmp_path)
    ref = _start(client).json()["incident"]

    row = journal.get(ref["id"])

    assert row["request"]["method"] == "POST"
    assert row["request"]["path"] == "/api/session"
    assert row["request"]["status"] == 429
    assert '"cooldown": true' in row["request"]["detail"]
    assert row["client_id"] == "uuid-1"
    assert row["device_name"] == "Jack"
    assert row["message"].startswith("cooldown") or "km" in row["message"]


def test_string_detail_keeps_its_text_and_gains_incident(tmp_path):
    client, journal, _, _ = _make(tmp_path, devices=())

    r = client.get("/api/status")

    assert r.status_code == 400
    body = r.json()
    assert "no devices registered" in body["detail"]
    assert body["incident"]["code"] == "addressing.no_devices"
    assert _all(journal)[0]["message"] == body["detail"]


def test_conflict_start_while_active_is_coded(tmp_path):
    client, journal, _, _ = _make(tmp_path)
    with client:  # one event loop for the whole test, so the session task lives
        client.post("/api/reset", headers=HEADERS)
        assert _start(client).status_code == 200
        try:
            r = _start(client)
            assert r.status_code == 409
            assert r.json()["incident"]["code"] == "session.already_active"
        finally:
            client.post("/api/stop", headers=HEADERS)


def test_validation_failure_is_recorded_and_keeps_the_error_list(tmp_path):
    client, journal, _, _ = _make(tmp_path)

    r = client.post(
        "/api/speed", json={"speed_kmh": 99}, headers=HEADERS
    )

    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], list)
    assert body["incident"]["code"] == "request.invalid"
    row = journal.get(body["incident"]["id"])
    assert "speed_kmh" in row["message"]


def test_unknown_api_path_is_recorded_as_not_found(tmp_path):
    client, journal, _, _ = _make(tmp_path)

    r = client.get("/api/nope")

    assert r.status_code == 404
    assert r.json()["incident"]["code"] == "request.not_found"
    assert len(_all(journal)) == 1


def test_asset_misses_record_nothing(tmp_path):
    client, journal, _, _ = _make(tmp_path)

    assert client.get("/favicon.ico").status_code == 404
    assert client.get("/static/missing.js").status_code == 404

    assert _all(journal) == []


def test_incident_endpoint_failures_record_nothing_and_carry_null_incident(tmp_path):
    client, journal, _, _ = _make(tmp_path)
    client.get("/api/nope")  # one real rejection to compare against

    r = client.get("/api/incidents/99999")

    assert r.status_code == 404
    assert r.json()["incident"] is None
    assert len(_all(journal)) == 1


def test_unmapped_failure_answers_a_json_500_with_traceback_and_lead_up_log(tmp_path):
    buf = LogRingBuffer()
    lg = logging.getLogger("trail_simulator")
    lg.addHandler(buf)
    try:
        client, journal, _, _ = _make(tmp_path, buffer=buf)
        logging.getLogger("trail_simulator.test").warning("lead-up line")

        r = client.get("/api/boom")
    finally:
        lg.removeHandler(buf)

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["detail"] == "unexpected server error: ValueError: kaboom"
    assert body["incident"]["code"] == "unexpected"
    assert body["incident"]["remedy"] is None
    row = journal.get(body["incident"]["id"])
    assert row["exception_type"] == "ValueError"
    assert "kaboom" in row["traceback"]
    assert any("lead-up line" in l for l in row["log"])
    assert row["request"]["status"] == 500


def test_unmapped_failure_outside_api_stays_plain_and_unrecorded(tmp_path):
    client, journal, _, _ = _make(tmp_path)

    r = client.get("/boom")

    assert r.status_code == 500
    assert r.text == "Internal Server Error"
    assert _all(journal) == []


def test_retarget_planning_failure_keeps_409_with_the_route_code(tmp_path, monkeypatch):
    async def route(a, b, c, d):
        return [(35.0, 139.0), (35.01, 139.0)]

    monkeypatch.setattr(controller_mod, "fetch_walking_route", route)
    client, _, _, _ = _make(tmp_path)
    with client:
        client.post("/api/reset", headers=HEADERS)
        assert client.post(
            "/api/session",
            json={"start_lat": 35.0, "start_lon": 139.0, "destinations": DESTS,
                  "speed_kmh": 5},
            headers=HEADERS,
        ).status_code == 200
        for _ in range(50):  # wait for the loop to leave "starting"
            if client.get("/api/status", headers=HEADERS).json()["state"] == "running":
                break
            time.sleep(0.02)

        async def no_route(a, b, c, d):
            raise RouteError("no walking route", code="route.no_route")

        monkeypatch.setattr(controller_mod, "fetch_walking_route", no_route)
        try:
            r = client.post(
                "/api/retarget",
                json={"destinations": [{"lat": 36.5, "lon": 139.5}]},
                headers=HEADERS,
            )
            assert r.status_code == 409
            assert r.json()["detail"] == "no walking route"
            assert r.json()["incident"]["code"] == "route.no_route"
        finally:
            client.post("/api/stop", headers=HEADERS)


def test_broken_journal_leaves_the_429_untouched_with_null_incident(tmp_path):
    client, journal, _, _ = _make(tmp_path)

    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("disk full")

    journal._conn = Broken()

    r = _start(client)

    assert r.status_code == 429
    body = r.json()
    assert body["detail"]["cooldown"] is True
    assert body["incident"] is None
    assert client.get("/api/status", headers=HEADERS).json()["last_incident"] is None


# ---- /ws/live (API-29) -------------------------------------------------------
def _ws_client(tmp_path, devices):
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    for udid, name in devices:
        registry.register(udid=udid, name=name)
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    journal = Journal(tmp_path / "s.db", version="test")
    app = FastAPI()
    app.include_router(build_ws_router(manager, registry, journal=journal))
    return TestClient(app), journal


def test_refused_live_stream_records_one_addressing_rejection(tmp_path):
    client, journal = _ws_client(tmp_path, [("A", "Jack"), ("B", "Spare")])

    reason = None
    try:
        with client.websocket_connect("/ws/live?client=ghost"):
            pass
    except Exception as e:  # noqa: BLE001
        reason = getattr(e, "reason", None)

    items = journal.list()[0]
    assert len(items) == 1
    assert items[0]["code"] == "addressing.client_unmatched"
    assert items[0]["kind"] == "rejection"
    assert items[0]["client_id"] == "ghost"
    row = journal.get(items[0]["id"])
    assert row["request"]["method"] == "WEBSOCKET"
    assert row["request"]["path"] == "/ws/live"
    assert row["message"].startswith(reason)
    assert "'ghost' does not match any device name" in row["message"]


def test_redialling_live_stream_collapses_into_one_incident(tmp_path):
    client, journal = _ws_client(tmp_path, [("A", "Jack"), ("B", "Spare")])

    for _ in range(5):
        try:
            with client.websocket_connect("/ws/live?client=ghost"):
                pass
        except Exception:  # noqa: BLE001
            pass

    items = journal.list()[0]
    assert len(items) == 1 and items[0]["count"] == 5


def test_accepted_live_stream_records_nothing(tmp_path):
    client, journal = _ws_client(tmp_path, [("A", "Jack")])

    with client.websocket_connect("/ws/live?client=Jack") as ws:
        ws.receive_text()

    assert journal.list()[0] == []
