from trail_simulator.device.registry import DeviceRegistry


def test_register_defaults_type_ios():
    r = DeviceRegistry()
    r.register(udid="UDID-A", name="Jack iPhone")
    assert r.type_for("UDID-A") == "ios"


def test_register_records_android_type():
    r = DeviceRegistry()
    r.register(udid="SER-1", name="Pixel 7", device_type="android")
    assert r.type_for("SER-1") == "android"


def test_type_for_unknown_defaults_ios():
    r = DeviceRegistry()
    assert r.type_for("missing") == "ios"
