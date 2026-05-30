# tests/test_controller_step_scoping.py
import time

import pytest

from trail_simulator.api import ws_steps
from trail_simulator.api.ws_steps import StepClient, StepFanout
from trail_simulator.session.controller import SessionController
from trail_simulator.session.store import Store


class _Dev:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


class _FakeRegistry:
    def __init__(self, mapping):
        self._m = mapping

    def resolve_client(self, client_uuid):
        return self._m.get(client_uuid)


class _FakeWS:
    async def send_json(self, payload): pass


def _client(client_uuid):
    now = time.time()
    return StepClient(
        ws=_FakeWS(), label=client_uuid, client_uuid=client_uuid, udid=None,
        connected_at=now, last_heartbeat_at=now, total_acked=0,
    )


@pytest.fixture
def scoped_broadcaster(monkeypatch):
    f = StepFanout()
    f.set_registry(_FakeRegistry({"jack": "UDID-A", "anna": "UDID-B"}))
    f._register("c1", _client("jack"))
    f._register("c2", _client("anna"))
    monkeypatch.setattr(ws_steps, "broadcaster", f)
    return f


def test_status_step_companions_scoped_to_controller_udid(tmp_path, scoped_broadcaster):
    c = SessionController(_Dev(), Store(tmp_path / "t.db"), udid="UDID-A")
    labels = [sc["label"] for sc in c.status().step_companions]
    assert labels == ["jack"]
