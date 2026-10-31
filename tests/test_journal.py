"""The journal: recording, collapse, retention, bounds, catalogue (OBS-05..09)."""
from __future__ import annotations

import ast
import logging
import re
import sqlite3
from pathlib import Path

import pytest

from trail_simulator.observatory import catalogue
from trail_simulator.observatory.journal import Journal
from trail_simulator.observatory.logbuffer import LogRingBuffer
from trail_simulator.observatory.version import backend_version

DAY = 86400.0


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal(tmp_path, clock):
    return Journal(tmp_path / "j.db", clock=clock, version="test")


def _rejection(journal, code="safety.cooldown", **kw):
    return journal.record("rejection", code, "msg", **kw)


# ---- recording and context (OBS-05) -----------------------------------------
def test_record_returns_reference_with_code_and_remedy(journal):
    ref = _rejection(journal)
    assert ref["code"] == "safety.cooldown"
    assert ref["remedy"] == catalogue.remedy_for("safety.cooldown")
    assert isinstance(ref["id"], int)


def test_record_stores_the_common_context(journal, clock):
    ref = journal.record(
        "fault", "device.tunnel_down", "device: tunnel gone",
        client_id="c1", device_udid="U1", device_name="Jack",
        session_id=7, session_state="error",
    )
    row = journal.get(ref["id"])
    assert row["kind"] == "fault"
    assert row["source"] == "backend"
    assert row["message"] == "device: tunnel gone"
    assert row["client_id"] == "c1"
    assert row["device_udid"] == "U1" and row["device_name"] == "Jack"
    assert row["session_id"] == 7 and row["session_state"] == "error"
    assert row["backend_version"] == "test"
    assert row["count"] == 1
    assert row["first_seen"] == row["last_seen"]


def test_rejection_stores_the_request_and_response(journal):
    ref = journal.record(
        "rejection", "session.already_active", "session already active",
        request={"method": "POST", "path": "/api/session", "query": "client=x",
                 "status": 409, "detail": "session already active"},
    )
    row = journal.get(ref["id"])
    assert row["request"] == {
        "method": "POST", "path": "/api/session", "query": "client=x",
        "status": 409, "detail": "session already active",
    }


def test_exception_type_and_traceback_are_stored(journal):
    ref = journal.record(
        "fault", "unexpected", "unexpected: boom",
        exception_type="ValueError", traceback="Traceback...\nValueError: boom",
    )
    row = journal.get(ref["id"])
    assert row["exception_type"] == "ValueError"
    assert "ValueError: boom" in row["traceback"]


def test_fault_carries_lead_up_log_lines_at_most_100(tmp_path, clock):
    buf = LogRingBuffer(capacity=100)
    lg = logging.getLogger("test_journal_leadup")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.addHandler(buf)
    try:
        for i in range(150):
            lg.info("line %d", i)
        j = Journal(tmp_path / "j.db", clock=clock, log_buffer=buf, version="t")
        ref = j.record("fault", "device.connection_lost", "m", with_log=True)
        row = j.get(ref["id"])
        assert len(row["log"]) == 100
        assert row["log"][-1].endswith("line 149")
        assert row["log"][0].endswith("line 50")
        # A rejection does not ask for the log.
        ref2 = j.record("rejection", "safety.cooldown", "m")
        assert j.get(ref2["id"])["log"] is None
    finally:
        lg.removeHandler(buf)


def test_text_fields_are_bounded(journal):
    ref = journal.record(
        "fault", "unexpected", "m" * 50_000,
        exception_type="E" * 5000, traceback="t" * 500_000,
        request={"method": "GET", "path": "/" + "p" * 9000, "query": "q" * 9000,
                 "status": 500, "detail": "d" * 100_000},
    )
    row = journal.get(ref["id"])
    assert len(row["message"]) <= 2100
    assert len(row["traceback"]) <= 20_100
    assert len(row["exception_type"]) <= 200
    assert len(row["request"]["detail"]) <= 4100
    assert len(row["request"]["path"]) <= 600
    assert len(row["request"]["query"]) <= 1100


def test_unknown_code_is_recorded_as_unexpected(journal):
    ref = journal.record("fault", "made.up", "m")
    assert ref["code"] == "unexpected"
    assert ref["remedy"] is None


# ---- collapse (OBS-06) -------------------------------------------------------
def test_repeats_within_ten_minutes_collapse(journal, clock):
    first = _rejection(journal, client_id="ghost")
    for _ in range(359):
        clock.advance(10)
        again = _rejection(journal, client_id="ghost")
        assert again["id"] == first["id"]
    row = journal.get(first["id"])
    assert row["count"] == 360
    assert row["last_seen"] > row["first_seen"]
    assert len(journal.list()[0]) == 1


def test_collapse_keeps_the_first_occurrences_context(journal, clock):
    first = journal.record("rejection", "safety.cooldown", "first message", client_id="c")
    clock.advance(5)
    journal.record("rejection", "safety.cooldown", "second message", client_id="c")
    assert journal.get(first["id"])["message"] == "first message"


def test_an_eleven_minute_gap_starts_a_new_incident(journal, clock):
    first = _rejection(journal, client_id="c")
    clock.advance(11 * 60)
    second = _rejection(journal, client_id="c")
    assert second["id"] != first["id"]


def test_different_client_or_device_does_not_collapse(journal):
    a = _rejection(journal, client_id="a", device_udid="U1")
    b = _rejection(journal, client_id="b", device_udid="U1")
    c = _rejection(journal, client_id="a", device_udid="U2")
    assert len({a["id"], b["id"], c["id"]}) == 3


def test_fault_and_rejection_with_the_same_code_do_not_collapse(journal):
    a = journal.record("fault", "route.no_route", "m")
    b = journal.record("rejection", "route.no_route", "m")
    assert a["id"] != b["id"]


def test_unexpected_collapses_only_on_the_same_exception_type(journal):
    a = journal.record("fault", "unexpected", "m", exception_type="ValueError")
    b = journal.record("fault", "unexpected", "m", exception_type="KeyError")
    c = journal.record("fault", "unexpected", "m", exception_type="ValueError")
    assert a["id"] != b["id"]
    assert c["id"] == a["id"]


def test_client_failures_never_collapse(journal):
    for i in range(3):
        journal.add_client_failure(
            report_id=f"r{i}", code="client.unreachable", message="m",
            started_at=1_799_999_000.0, ended_at=1_799_999_100.0, attempts=3,
            app_build="1", os_version="18", client_id="c", device_udid=None,
            device_name=None, offset_s=0.0, client_times=("a", "b"), sent_at="s",
        )
    items, _ = journal.list()
    assert len(items) == 3


# ---- OBS-08 ------------------------------------------------------------------
class _BrokenConn:
    def execute(self, *a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    executescript = execute


def test_recording_failure_is_swallowed_and_returns_none(journal):
    journal._conn = _BrokenConn()
    assert _rejection(journal) is None
    assert journal.record("fault", "unexpected", "m") is None


# ---- retention (OBS-09) ------------------------------------------------------
def test_prune_deletes_incidents_not_seen_for_30_days(journal, clock):
    old = _rejection(journal, client_id="old")
    clock.advance(29 * DAY)
    recent = _rejection(journal, client_id="recent")
    clock.advance(2 * DAY)  # old is now 31 days old, recent is 2
    assert journal.prune() >= 1
    ids = {i["id"] for i in journal.list()[0]}
    assert ids == {recent["id"]}
    assert old["id"] not in ids


def test_incidents_survive_reopening_the_file(tmp_path, clock):
    j1 = Journal(tmp_path / "j.db", clock=clock, version="t")
    ref = _rejection(j1)
    j2 = Journal(tmp_path / "j.db", clock=clock, version="t")
    assert j2.get(ref["id"]) is not None


def test_prune_also_drops_old_availability_spans(journal, clock):
    journal.availability.start()
    clock.advance(40 * DAY)
    journal.availability.start()
    journal.prune()
    spans = journal.availability.spans()
    assert len(spans) == 1


# ---- catalogue (OBS-07) ------------------------------------------------------
def test_every_code_except_unexpected_has_a_remedy():
    for code, entry in catalogue.CATALOGUE.items():
        if code == "unexpected":
            assert entry.remedy is None
        else:
            assert entry.remedy, code


def test_every_code_in_the_source_is_in_the_catalogue():
    """Any string literal in the backend that looks like an incident code
    (prefix.name with a catalogue prefix) must be a catalogue code."""
    prefixes = {c.split(".")[0] for c in catalogue.CATALOGUE if "." in c}
    pat = re.compile(r"^(%s)\.[a-z_]+$" % "|".join(sorted(prefixes)))
    root = Path(__file__).resolve().parent.parent / "trail_simulator"
    found: set[str] = set()
    for path in root.rglob("*.py"):
        if path.name == "catalogue.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and pat.match(node.value):
                found.add(node.value)
    assert found <= set(catalogue.CATALOGUE), found - set(catalogue.CATALOGUE)


def test_client_codes_are_the_client_failure_ones():
    assert catalogue.is_client_code("client.unreachable")
    assert not catalogue.is_client_code("route.no_route")
    assert not catalogue.is_client_code("nope")


# ---- log buffer and version (T2) --------------------------------------------
def test_log_buffer_keeps_only_the_newest_lines():
    buf = LogRingBuffer(capacity=3)
    lg = logging.getLogger("test_logbuf")
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    lg.addHandler(buf)
    try:
        for i in range(5):
            lg.warning("n%d", i)
    finally:
        lg.removeHandler(buf)
    lines = buf.lines()
    assert len(lines) == 3
    assert lines[0].endswith("n2") and lines[-1].endswith("n4")
    assert "WARNING" in lines[0] and "test_logbuf" in lines[0]


def test_log_buffer_respects_the_logger_level():
    buf = LogRingBuffer(capacity=10)
    lg = logging.getLogger("test_logbuf_level")
    lg.setLevel(logging.WARNING)
    lg.propagate = False
    lg.addHandler(buf)
    try:
        lg.info("hidden")
        lg.warning("shown")
    finally:
        lg.removeHandler(buf)
    assert [l.split()[-1] for l in buf.lines()] == ["shown"]


def test_backend_version_has_package_version_and_a_suffix():
    v = backend_version()
    assert v.startswith("0.1.0")
    assert "+" in v


def test_version_is_resolved_at_startup_not_on_the_first_record(tmp_path, monkeypatch):
    import trail_simulator.observatory.journal as journal_mod

    calls = []

    def fake_version():
        calls.append(1)
        return "9.9+test"

    monkeypatch.setattr(journal_mod, "backend_version", fake_version)
    j = Journal(tmp_path / "j.db")
    assert calls == [1]                    # resolved by the constructor

    ref = j.record("rejection", "safety.cooldown", "m")
    j.record("fault", "unexpected", "m")
    assert calls == [1]                    # recording never resolves it again
    assert j.get(ref["id"])["backend_version"] == "9.9+test"
