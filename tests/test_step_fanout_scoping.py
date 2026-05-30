# tests/test_step_fanout_scoping.py
import time

import pytest

from trail_simulator.api.ws_steps import StepClient, StepFanout


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class _FakeRegistry:
    def __init__(self, mapping):
        self._m = mapping

    def resolve_client(self, client_uuid):
        return self._m.get(client_uuid)


def _client(ws, client_uuid):
    now = time.time()
    return StepClient(
        ws=ws,
        label=client_uuid,
        client_uuid=client_uuid,
        udid=None,
        connected_at=now,
        last_heartbeat_at=now,
        total_acked=0,
    )


def _fanout():
    f = StepFanout()
    f.set_registry(_FakeRegistry({"jack": "UDID-A", "anna": "UDID-B"}))
    return f


@pytest.mark.asyncio
async def test_send_only_reaches_matching_udid():
    f = _fanout()
    jack_ws, anna_ws = _FakeWS(), _FakeWS()
    f._register("c1", _client(jack_ws, "jack"))
    f._register("c2", _client(anna_ws, "anna"))

    await f.send({"type": "steps", "steps": 3}, udid="UDID-A")

    assert jack_ws.sent == [{"type": "steps", "steps": 3}]
    assert anna_ws.sent == []


def test_snapshot_is_scoped_by_udid():
    f = _fanout()
    f._register("c1", _client(_FakeWS(), "jack"))
    f._register("c2", _client(_FakeWS(), "anna"))

    labels = [c["label"] for c in f.snapshot(udid="UDID-A")]
    assert labels == ["jack"]


def test_has_clients_scoped_by_udid():
    f = _fanout()
    f._register("c1", _client(_FakeWS(), "jack"))
    assert f.has_clients(udid="UDID-A") is True
    assert f.has_clients(udid="UDID-B") is False


def test_unbound_companion_receives_nothing():
    f = _fanout()  # "ghost" is not in the registry mapping
    ghost_ws = _FakeWS()
    f._register("c1", _client(ghost_ws, "ghost"))
    assert f.has_clients(udid="UDID-A") is False
