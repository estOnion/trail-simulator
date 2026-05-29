import pytest
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.controller import SessionController
from trail_simulator.session.store import Store


class _StubDevice:
    async def open(self): pass
    async def set(self, lat, lon): pass
    async def clear(self): pass


def _factory(udid):
    return _StubDevice()


def test_get_or_create_caches_per_udid(tmp_path):
    store = Store(path=tmp_path / "s.db")
    m = SessionManager(device_factory=_factory, store=store)
    c1 = m.get_or_create("UDID-A")
    c2 = m.get_or_create("UDID-A")
    c3 = m.get_or_create("UDID-B")
    assert isinstance(c1, SessionController)
    assert c1 is c2
    assert c3 is not c1


def test_list_active_returns_all(tmp_path):
    store = Store(path=tmp_path / "s.db")
    m = SessionManager(device_factory=_factory, store=store)
    m.get_or_create("UDID-A")
    m.get_or_create("UDID-B")
    assert sorted(u for u, _ in m.list_active()) == ["UDID-A", "UDID-B"]


@pytest.mark.asyncio
async def test_stop_all_stops_each(tmp_path):
    store = Store(path=tmp_path / "s.db")
    m = SessionManager(device_factory=_factory, store=store)
    m.get_or_create("UDID-A")
    m.get_or_create("UDID-B")
    await m.stop_all()  # must not raise even with no running sessions
