import pytest
from trail_simulator.device.registry import DeviceRegistry, DuplicateDeviceNameError


def test_register_and_resolve_by_name():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    assert r.resolve("Jack iPhone") == "UDID-A"
    assert r.resolve("Unknown") is None


def test_list_devices_returns_all_pairs():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    r.register(udid="UDID-B", name="Spare iPhone")
    pairs = sorted(r.list_devices())
    assert pairs == [("UDID-A", "Jack iPhone"), ("UDID-B", "Spare iPhone")]


def test_duplicate_name_raises():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="iPhone")
    with pytest.raises(DuplicateDeviceNameError):
        r.register(udid="UDID-B", name="iPhone")


def test_default_udid_when_single_device():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    assert r.default_udid() == "UDID-A"


def test_default_udid_none_when_multi_or_empty():
    r = DeviceRegistry()
    assert r.default_udid() is None
    r.register(udid="UDID-A", name="A")
    r.register(udid="UDID-B", name="B")
    assert r.default_udid() is None
