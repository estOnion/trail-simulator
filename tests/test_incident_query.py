"""Incident list, detail, summary and catalogue endpoints (API-35..38)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.main import build_app
from trail_simulator.observatory import catalogue
from trail_simulator.observatory.journal import Journal
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store

T0 = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path):
    clock = Clock(T0.timestamp())
    store = Store(path=tmp_path / "s.db")
    journal = Journal(tmp_path / "s.db", clock=clock, version="t")
    manager = SessionManager(device_factory=lambda u: object(), store=store)
    app = build_app(manager, DeviceRegistry(), journal=journal)
    return TestClient(app), journal, clock


def _seed(journal, clock):
    """Five incidents, one minute apart, oldest first."""
    rows = []

    def rec(kind, code, message, **kw):
        rows.append(journal.record(kind, code, message, **kw))
        clock.t += 60

    rec("rejection", "safety.cooldown", "cooldown: wait 30 min",
        client_id="c1", device_udid="U1", device_name="Jack", session_id=1)
    rec("fault", "device.tunnel_down", "device: tunnel is not running",
        client_id="c1", device_udid="U1", device_name="Jack", session_id=2)
    rec("fault", "device.not_reachable", "device: phone not on tunnel",
        client_id="c2", device_udid="U2", device_name="Spare", session_id=3)
    rec("cap_trip", "safety.speed_cap", "speed gate: 25.0 km/h",
        client_id="c2", device_udid="U2", device_name="Spare", session_id=3)
    journal.add_client_failure(
        report_id="r1", code="client.unreachable", message="no route to backend",
        started_at=clock.t - 500, ended_at=clock.t - 400, attempts=3,
        app_build="1", os_version="18", client_id="c1", device_udid="U1",
        device_name="Jack", offset_s=0.0, client_times=("a", "b"), sent_at="s",
    )
    return rows


def _codes(r):
    return [i["code"] for i in r.json()["incidents"]]


def test_list_is_newest_first_with_the_documented_fields(rig):
    client, journal, clock = rig
    _seed(journal, clock)

    r = client.get("/api/incidents")

    assert r.status_code == 200
    body = r.json()
    assert body["next_before"] is None
    assert _codes(r)[:2] == ["safety.speed_cap", "device.not_reachable"]
    last_seens = [i["last_seen"] for i in body["incidents"]]
    assert last_seens == sorted(last_seens, reverse=True)
    item = next(i for i in body["incidents"] if i["code"] == "safety.cooldown")
    assert set(item) == {
        "id", "kind", "code", "remedy", "source", "message", "first_seen",
        "last_seen", "count", "client_id", "device_name", "session_id",
    }
    assert item["code"] == "safety.cooldown" and item["remedy"]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("kind=fault", {"device.tunnel_down", "device.not_reachable"}),
        ("kind=fault,cap_trip", {"device.tunnel_down", "device.not_reachable", "safety.speed_cap"}),
        ("code=safety.cooldown", {"safety.cooldown"}),
        ("code=device.*", {"device.tunnel_down", "device.not_reachable"}),
        ("code=device.*,safety.cooldown", {"device.tunnel_down", "device.not_reachable", "safety.cooldown"}),
        ("client=c2", {"device.not_reachable", "safety.speed_cap"}),
        ("device=Jack", {"safety.cooldown", "device.tunnel_down", "client.unreachable"}),
        ("device=U2", {"device.not_reachable", "safety.speed_cap"}),
        ("session=3", {"device.not_reachable", "safety.speed_cap"}),
        ("q=not running", {"device.tunnel_down"}),
        ("q=NOT RUNNING", {"device.tunnel_down"}),
    ],
)
def test_filters(rig, query, expected):
    client, journal, clock = rig
    _seed(journal, clock)

    r = client.get(f"/api/incidents?{query}")

    assert set(_codes(r)) == expected


def test_prefix_does_not_treat_underscore_as_a_wildcard(rig):
    client, journal, clock = rig
    _seed(journal, clock)
    assert _codes(client.get("/api/incidents?code=safety.*")) == ["safety.speed_cap", "safety.cooldown"]
    assert _codes(client.get("/api/incidents?code=dev.*")) == []


def test_q_treats_percent_literally(rig):
    client, journal, clock = rig
    journal.record("rejection", "request.invalid", "100% wrong")
    journal.record("rejection", "request.not_found", "other")
    assert _codes(client.get("/api/incidents?q=%25")) == ["request.invalid"]


def test_time_range_filters_on_last_seen(rig):
    client, journal, clock = rig
    _seed(journal, clock)
    since = (T0 + timedelta(minutes=1, seconds=30)).isoformat().replace("+00:00", "Z")
    until = (T0 + timedelta(minutes=2, seconds=30)).isoformat().replace("+00:00", "Z")

    r = client.get("/api/incidents", params={"since": since, "until": until})

    assert _codes(r) == ["device.not_reachable"]


def test_paging_with_limit_and_before(rig):
    client, journal, clock = rig
    _seed(journal, clock)
    everything = _codes(client.get("/api/incidents"))

    p1 = client.get("/api/incidents?limit=2").json()
    assert len(p1["incidents"]) == 2 and p1["next_before"]
    p2 = client.get(f"/api/incidents?limit=2&before={p1['next_before']}").json()
    p3 = client.get(f"/api/incidents?limit=2&before={p2['next_before']}").json()

    paged = [i["code"] for p in (p1, p2, p3) for i in p["incidents"]]
    assert paged == everything
    assert p3["next_before"] is None


def test_limit_defaults_and_bounds(rig):
    client, journal, clock = rig
    assert client.get("/api/incidents?limit=0").status_code == 422
    assert client.get("/api/incidents?limit=501").status_code == 422
    for i in range(120):
        journal.record("rejection", "request.invalid", "m", client_id=f"c{i}")
    assert len(client.get("/api/incidents").json()["incidents"]) == 100
    assert len(client.get("/api/incidents?limit=500").json()["incidents"]) == 120


def test_detail_returns_the_full_record(rig):
    client, journal, clock = rig
    rows = _seed(journal, clock)

    r = client.get(f"/api/incidents/{rows[0]['id']}")

    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "safety.cooldown"
    assert body["session_state"] is None and body["backend_version"] == "t"
    assert body["device_udid"] == "U1" and body["session_id"] == 1
    assert body["host_during_outage"] is None


def test_detail_of_a_client_failure_explains_the_outage(rig):
    client, journal, clock = rig
    _seed(journal, clock)
    cf = next(i for i in client.get("/api/incidents?kind=client_failure").json()["incidents"])

    body = client.get(f"/api/incidents/{cf['id']}").json()

    assert body["host_during_outage"] in {"up", "down", "partly"}
    assert body["client_failure"]["attempts"] == 3


def test_detail_404_for_a_missing_incident(rig):
    client, _, _ = rig
    r = client.get("/api/incidents/12345")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_summary_groups_by_code_ordered_by_occurrences(rig):
    client, journal, clock = rig
    for _ in range(4):
        journal.record("fault", "device.tunnel_down", "m")
    journal.record("rejection", "safety.cooldown", "m", client_id="a")
    journal.record("rejection", "safety.cooldown", "m", client_id="b")

    r = client.get("/api/incidents/summary")

    assert r.status_code == 200
    codes = r.json()["codes"]
    assert [c["code"] for c in codes] == ["device.tunnel_down", "safety.cooldown"]
    top = codes[0]
    assert top["incidents"] == 1 and top["occurrences"] == 4
    assert top["remedy"] == catalogue.remedy_for("device.tunnel_down")
    assert codes[1]["incidents"] == 2 and codes[1]["occurrences"] == 2
    assert top["last_seen"].endswith("Z")


def test_summary_takes_the_same_filters(rig):
    client, journal, clock = rig
    _seed(journal, clock)
    r = client.get("/api/incidents/summary?kind=fault&device=Jack")
    assert [c["code"] for c in r.json()["codes"]] == ["device.tunnel_down"]


def test_catalogue_endpoint_lists_every_code(rig):
    client, _, _ = rig

    body = client.get("/api/incident-codes").json()

    by_code = {c["code"]: c for c in body["codes"]}
    assert set(by_code) == set(catalogue.CATALOGUE)
    assert by_code["unexpected"]["remedy"] is None
    assert by_code["route.no_route"]["kinds"] == ["fault", "rejection"]
    assert all(c["remedy"] for code, c in by_code.items() if code != "unexpected")


def test_service_down_remedy_mentions_retry_and_the_clients_link(rig):
    client, _, _ = rig

    by_code = {c["code"]: c for c in client.get("/api/incident-codes").json()["codes"]}

    remedy = by_code["route.service_down"]["remedy"]
    assert remedy == catalogue.remedy_for("route.service_down")
    assert remedy == (
        "The host could not reach the public OSRM router, even after a retry; "
        "your device's connection to the host is fine. Check the host's internet "
        "connection, then walk again."
    )


def test_endpoints_ignore_the_addressing_headers(rig):
    client, journal, clock = rig
    _seed(journal, clock)
    r = client.get("/api/incidents", headers={"X-Client-Id": "zzz", "X-Device-Name": "nope"})
    assert r.status_code == 200 and len(r.json()["incidents"]) == 5
