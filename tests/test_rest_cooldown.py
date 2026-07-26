# tests/test_rest_cooldown.py
"""Feature-level cover for the travel-time cooldown as a client sees it:
a blocked start over HTTP, a status endpoint that counts down, and the
release path that clears the stale fix."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trail_simulator.api.rest import build_router
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store

HEADERS = {"X-Client-Id": "uuid-1"}
# ~100 km north of the last fix — far beyond what 60 km/h covers in seconds.
FAR_START = {"start_lat": 35.9, "start_lon": 139.0}
DESTS = [{"lat": 36.0, "lon": 139.0}]


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


def _make(tmp_path):
    store = Store(path=tmp_path / "s.db")
    store.set_last_fix(35.0, 139.0)  # phone last spoofed here, just now
    registry = DeviceRegistry()
    registry.register(udid="UDID-A", name="Jack")
    manager = SessionManager(device_factory=lambda u: _StubDevice(), store=store)
    app = FastAPI()
    app.include_router(build_router(manager, registry), prefix="/api")
    return TestClient(app), store, manager


def _start(client, **extra):
    return client.post("/api/session", json={**FAR_START, "destinations": DESTS,
                                             "speed_kmh": 5.0, **extra}, headers=HEADERS)


def test_far_jump_start_is_rejected_with_429_and_wait_time(tmp_path):
    client, _, _ = _make(tmp_path)

    r = _start(client)

    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["cooldown"] is True
    assert detail["required_wait_s"] > 0
    assert detail["jump_km"] >= 90


def test_status_reports_cooldown_after_a_blocked_start(tmp_path):
    client, _, _ = _make(tmp_path)
    _start(client)

    body = client.get("/api/status", headers=HEADERS).json()

    assert body["state"] == "idle"
    assert body["cooldown_remaining_s"] > 0


def test_status_cooldown_counts_down_over_time(tmp_path):
    """The reported remaining is measured against a fixed expiry instant, so it
    shrinks as the clock advances rather than resetting on every poll."""
    client, _, manager = _make(tmp_path)
    _start(client)
    first = client.get("/api/status", headers=HEADERS).json()["cooldown_remaining_s"]

    # Rewind the expiry rather than sleeping, so the test stays fast.
    manager.get("UDID-A")._cooldown_until -= 120.0

    second = client.get("/api/status", headers=HEADERS).json()["cooldown_remaining_s"]
    assert second < first
    assert abs((first - second) - 120.0) < 1.0


def test_no_cooldown_when_there_is_no_prior_fix(tmp_path):
    client, store, _ = _make(tmp_path)
    store.clear_last_fix()

    r = _start(client)

    assert r.status_code == 200
    client.post("/api/stop", headers=HEADERS)


def test_skip_cooldown_lets_the_far_jump_through(tmp_path):
    client, _, _ = _make(tmp_path)
    assert _start(client).status_code == 429

    r = _start(client, skip_cooldown=True)

    assert r.status_code == 200
    assert client.get("/api/status", headers=HEADERS).json()["cooldown_remaining_s"] == 0.0
    client.post("/api/stop", headers=HEADERS)


def test_reset_drops_the_stale_fix_so_the_next_start_is_unblocked(tmp_path):
    client, store, _ = _make(tmp_path)
    assert _start(client).status_code == 429

    client.post("/api/reset", headers=HEADERS)

    assert store.get_last_fix() is None
    assert client.get("/api/status", headers=HEADERS).json()["cooldown_remaining_s"] == 0.0
    assert _start(client).status_code == 200
    client.post("/api/stop", headers=HEADERS)
