# tests/test_registry_sync.py
from trail_simulator.device.registry import DeviceRegistry


def test_sync_adds_new_devices():
    r = DeviceRegistry()
    r.sync([("UDID-A", "Jack", "ios"), ("SER-1", "Pixel", "android")])
    assert sorted(n for _, n in r.list_devices()) == ["Jack", "Pixel"]
    assert r.type_for("UDID-A") == "ios"
    assert r.type_for("SER-1") == "android"


def test_sync_preserves_binding_for_present_device():
    r = DeviceRegistry()
    r.sync([("UDID-A", "Jack", "ios")])
    r.bind("jack", "UDID-A")
    # Same device still present on the next discovery — binding survives.
    r.sync([("UDID-A", "Jack", "ios"), ("UDID-B", "Anna", "ios")])
    assert r.resolve_client("jack") == "UDID-A"


def test_sync_drops_disconnected_device_and_its_binding():
    r = DeviceRegistry()
    r.sync([("UDID-A", "Jack", "ios")])
    r.bind("jack", "UDID-A")
    # Jack's phone unplugged — gone from discovery.
    r.sync([("UDID-B", "Anna", "ios")])
    assert r.resolve_client("jack") is None
    assert r.client_for("UDID-A") is None
    assert r.name_for("UDID-A") is None
    assert [n for _, n in r.list_devices()] == ["Anna"]


def test_sync_updates_renamed_device():
    r = DeviceRegistry()
    r.sync([("UDID-A", "Jack", "ios")])
    r.sync([("UDID-A", "Jack's iPhone", "ios")])
    assert r.name_for("UDID-A") == "Jack's iPhone"
    assert r.resolve("Jack") is None
    assert r.resolve("Jack's iPhone") == "UDID-A"
