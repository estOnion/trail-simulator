from fastapi.testclient import TestClient

from trail_simulator.main import _make_device_factory, build_app
from trail_simulator.device.android_location import AndroidLocationClient
from trail_simulator.device.location import LocationClient
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store


def test_factory_android_serial_returns_android_client():
    f = _make_device_factory({"SER-1"})
    assert isinstance(f("SER-1"), AndroidLocationClient)


def test_factory_udid_returns_ios_client():
    f = _make_device_factory({"SER-1"})
    assert isinstance(f("UDID-A"), LocationClient)


def test_build_app_devices_endpoint_uses_discover(tmp_path):
    registry = DeviceRegistry()  # empty at launch
    manager = SessionManager(device_factory=lambda u: object(), store=Store(tmp_path / "s.db"))

    async def discover():
        return [("UDID-A", "Jack", "ios")]

    app = build_app(manager, registry, discover=discover)
    body = TestClient(app).get("/api/devices").json()
    assert [d["name"] for d in body["devices"]] == ["Jack"]
