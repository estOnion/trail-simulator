"""Client failure reports (OBS-04, API-34)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.main import build_app
from trail_simulator.observatory.journal import Journal
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store

HOST_NOW = datetime(2026, 10, 31, 10, 10, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path):
    clock = Clock(HOST_NOW.timestamp())
    store = Store(path=tmp_path / "s.db")
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    registry.bind("uuid-1", "UDID-A")
    journal = Journal(tmp_path / "s.db", clock=clock, version="t")
    manager = SessionManager(device_factory=lambda u: object(), store=store)
    app = build_app(manager, registry, journal=journal)
    return TestClient(app, raise_server_exceptions=False), journal, clock


def _report(**over):
    base = {
        "report_id": str(uuid.uuid4()),
        "code": "client.unreachable",
        "message": "Could not connect to the backend",
        "started_at": "2026-10-31T10:00:00+00:00",
        "ended_at": "2026-10-31T10:05:00+00:00",
        "attempts": 7,
        "app_build": "42",
        "os_version": "iOS 18.1",
    }
    base.update(over)
    return base


def _post(client, reports, sent_at=HOST_NOW, headers=None):
    return client.post(
        "/api/incidents",
        json={"sent_at": sent_at.isoformat(), "reports": reports},
        headers=headers or {},
    )


def test_reports_are_stored_one_incident_each(rig):
    client, journal, _ = rig
    reports = [_report(), _report(code="client.timeout")]

    r = _post(client, reports, headers={"X-Client-Id": "uuid-1"})

    assert r.status_code == 200
    body = r.json()
    assert [a["report_id"] for a in body["accepted"]] == [x["report_id"] for x in reports]
    assert body["duplicates"] == []
    items = journal.list()[0]
    assert {i["code"] for i in items} == {"client.unreachable", "client.timeout"}
    row = journal.get(body["accepted"][0]["id"])
    assert row["kind"] == "client_failure" and row["source"] == "client"
    assert row["message"] == "Could not connect to the backend"
    assert row["client_id"] == "uuid-1" and row["device_name"] == "Jack"
    cf = row["client_failure"]
    assert cf["attempts"] == 7
    assert cf["app_build"] == "42" and cf["os_version"] == "iOS 18.1"
    assert cf["client_started_at"] == "2026-10-31T10:00:00+00:00"
    assert row["remedy"]


def test_repeated_upload_creates_nothing_new_and_lists_duplicates(rig):
    client, journal, _ = rig
    batch = [_report(), _report()]
    first = _post(client, batch).json()

    again = _post(client, batch).json()

    assert again["accepted"] == []
    assert again["duplicates"] == [b["report_id"] for b in batch]
    assert len(journal.list()[0]) == 2
    assert {a["id"] for a in first["accepted"]} == {i["id"] for i in journal.list()[0]}


def test_partly_new_batch_accepts_only_the_new_reports(rig):
    client, journal, _ = rig
    old, new = _report(), _report()
    _post(client, [old])

    body = _post(client, [old, new]).json()

    assert [a["report_id"] for a in body["accepted"]] == [new["report_id"]]
    assert body["duplicates"] == [old["report_id"]]


def test_fast_phone_clock_is_corrected_onto_the_host_clock(rig):
    client, journal, _ = rig
    phone_sent = HOST_NOW + timedelta(seconds=90)      # phone runs 90 s fast
    rep = _report(started_at="2026-10-31T10:00:00+00:00",
                  ended_at="2026-10-31T10:05:00+00:00")

    body = _post(client, [rep], sent_at=phone_sent).json()

    row = journal.get(body["accepted"][0]["id"])
    assert row["first_seen"] == "2026-10-31T09:58:30.000Z"
    assert row["last_seen"] == "2026-10-31T10:03:30.000Z"
    assert row["client_failure"]["client_started_at"] == "2026-10-31T10:00:00+00:00"
    assert row["client_failure"]["clock_offset_s"] == -90.0


def test_times_with_a_non_utc_offset_are_handled(rig):
    client, journal, _ = rig
    rep = _report(started_at="2026-10-31T19:00:00+09:00",
                  ended_at="2026-10-31T19:05:00+09:00")
    sent = HOST_NOW.astimezone(timezone(timedelta(hours=9)))

    body = _post(client, [rep], sent_at=sent).json()

    assert journal.get(body["accepted"][0]["id"])["first_seen"] == "2026-10-31T10:00:00.000Z"


def test_no_addressing_needed_even_with_unknown_client_and_many_devices(rig):
    client, journal, _ = rig
    # An unbound client ID, and no headers at all, are both accepted.
    assert _post(client, [_report()], headers={"X-Client-Id": "nobody"}).status_code == 200
    assert _post(client, [_report()]).status_code == 200
    rows = [journal.get(i["id"]) for i in journal.list()[0]]
    assert {r["client_id"] for r in rows} == {"nobody", None}


@pytest.mark.parametrize("code", ["route.no_route", "unexpected", "made.up"])
def test_non_client_codes_are_refused_with_422(rig, code):
    client, journal, _ = rig

    r = _post(client, [_report(), _report(code=code)])

    assert r.status_code == 422
    assert r.json()["incident"] is None
    assert journal.list()[0] == []          # nothing from the batch was stored


def test_malformed_bodies_are_refused_with_422_and_not_journaled(rig):
    client, journal, _ = rig
    cases = [
        {"reports": [_report()]},                                    # no sent_at
        {"sent_at": HOST_NOW.isoformat(), "reports": [_report(report_id="nope")]},
        {"sent_at": HOST_NOW.isoformat(), "reports": [_report(attempts=-1)]},
        {"sent_at": "2026-10-31T10:00:00", "reports": [_report()]},  # no offset
        {"sent_at": HOST_NOW.isoformat(),
         "reports": [_report(started_at="2026-10-31T10:00:00")]},
    ]
    for body in cases:
        r = client.post("/api/incidents", json=body)
        assert r.status_code == 422, body
        assert r.json()["incident"] is None
    assert journal.list()[0] == []


def test_more_than_200_reports_is_refused(rig):
    client, journal, _ = rig
    assert _post(client, [_report() for _ in range(200)]).status_code == 200
    assert _post(client, [_report() for _ in range(201)]).status_code == 422
    assert len(journal.list(limit=500)[0]) == 200


def test_report_for_an_outage_is_explained_against_availability(rig):
    client, journal, clock = rig
    # Host started 09:00, last alive 09:30, nothing since until now (10:10),
    # when it started again.
    clock.t = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc).timestamp()
    journal.availability.start()
    clock.t += 30 * 60
    journal.availability.beat()
    clock.t = HOST_NOW.timestamp()
    journal.availability.start()

    body = _post(client, [_report(started_at="2026-10-31T09:20:00+00:00",
                                  ended_at="2026-10-31T09:50:00+00:00")]).json()

    row = journal.get(body["accepted"][0]["id"])
    assert row["host_during_outage"] == "partly"


def test_report_id_is_echoed_as_sent_and_compared_as_a_uuid(rig):
    client, journal, _ = rig
    rid = str(uuid.uuid4())
    upper = rid.upper()

    first = _post(client, [_report(report_id=upper)]).json()
    assert [a["report_id"] for a in first["accepted"]] == [upper]      # echoed as sent

    again_lower = _post(client, [_report(report_id=rid)]).json()
    assert again_lower["accepted"] == []
    assert again_lower["duplicates"] == [rid]                          # echoed as sent
    again_upper = _post(client, [_report(report_id=upper)]).json()
    assert again_upper["duplicates"] == [upper]
    assert len(journal.list()[0]) == 1


def test_lowercase_upload_then_uppercase_is_one_report(rig):
    client, journal, _ = rig
    rid = str(uuid.uuid4())
    _post(client, [_report(report_id=rid)])

    body = _post(client, [_report(report_id=rid.upper())]).json()

    assert body["accepted"] == [] and body["duplicates"] == [rid.upper()]
    assert len(journal.list()[0]) == 1
