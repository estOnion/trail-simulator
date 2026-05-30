from trail_simulator.main import _make_device_factory
from trail_simulator.device.android_location import AndroidLocationClient
from trail_simulator.device.location import LocationClient


def test_factory_android_serial_returns_android_client():
    f = _make_device_factory({"SER-1"})
    assert isinstance(f("SER-1"), AndroidLocationClient)


def test_factory_udid_returns_ios_client():
    f = _make_device_factory({"SER-1"})
    assert isinstance(f("UDID-A"), LocationClient)
