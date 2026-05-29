# tests/test_registry_clientid.py
import pytest
from trail_simulator.device.registry import DeviceRegistry, DuplicateClientIdError


def _reg(*pairs):
    r = DeviceRegistry()
    for udid, name in pairs:
        r.register(udid=udid, name=name)
    return r


def test_bind_and_resolve_client():
    r = _reg(("UDID-A", "Jack"))
    r.bind("uuid-1", "UDID-A")
    assert r.resolve_client("uuid-1") == "UDID-A"
    assert r.client_for("UDID-A") == "uuid-1"
    assert r.resolve_client("nope") is None


def test_bind_same_client_same_udid_idempotent():
    r = _reg(("UDID-A", "Jack"))
    r.bind("uuid-1", "UDID-A")
    r.bind("uuid-1", "UDID-A")  # no raise
    assert r.resolve_client("uuid-1") == "UDID-A"


def test_duplicate_client_id_on_other_udid_raises():
    r = _reg(("UDID-A", "Jack"), ("UDID-B", "Spare"))
    r.bind("uuid-1", "UDID-A")
    with pytest.raises(DuplicateClientIdError):
        r.bind("uuid-1", "UDID-B")


def test_rebinding_udid_releases_old_client():
    r = _reg(("UDID-A", "Jack"))
    r.bind("old", "UDID-A")
    r.bind("new", "UDID-A")
    assert r.resolve_client("old") is None
    assert r.resolve_client("new") == "UDID-A"
    assert r.client_for("UDID-A") == "new"


def test_auto_bind_single():
    r = _reg(("UDID-A", "Jack"))
    assert r.auto_bind_single("uuid-x") == "UDID-A"
    assert r.resolve_client("uuid-x") == "UDID-A"


def test_auto_bind_single_none_when_multiple():
    r = _reg(("UDID-A", "Jack"), ("UDID-B", "Spare"))
    assert r.auto_bind_single("uuid-x") is None


def test_auto_bind_single_none_when_already_bound_to_other():
    r = _reg(("UDID-A", "Jack"))
    r.bind("owner", "UDID-A")
    assert r.auto_bind_single("intruder") is None


def test_list_clients():
    r = _reg(("UDID-A", "Jack"), ("UDID-B", "Spare"))
    r.bind("uuid-1", "UDID-A")
    assert r.list_clients() == [("uuid-1", "UDID-A", "Jack")]
