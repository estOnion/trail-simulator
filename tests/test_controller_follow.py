# tests/test_controller_follow.py
import pytest
from trail_simulator.session.controller import SessionController, SessionState
from trail_simulator.session.store import Store


class _RecordingDevice:
    def __init__(self):
        self.points = []
        self.opened = False
    async def open(self):
        self.opened = True
    async def set(self, lat, lon):
        self.points.append((lat, lon))
    async def clear(self):
        pass


def _controller(tmp_path, name):
    return SessionController(_RecordingDevice(), Store(path=tmp_path / f"{name}.db"))


@pytest.mark.asyncio
async def test_follow_mirrors_leader_position(tmp_path):
    leader = _controller(tmp_path, "leader")
    follower = _controller(tmp_path, "follower")

    await follower.follow(leader, "Leader iPhone")
    assert follower.status().state == SessionState.following
    assert follower.status().following_leader == "Leader iPhone"

    leader._current = (35.0, 139.0)
    await leader._broadcast()

    assert follower._device.points[-1] == (35.0, 139.0)


@pytest.mark.asyncio
async def test_unfollow_stops_mirroring(tmp_path):
    leader = _controller(tmp_path, "leader2")
    follower = _controller(tmp_path, "follower2")
    await follower.follow(leader, "Leader iPhone")
    await follower.unfollow()
    assert follower.status().state == SessionState.idle
    assert follower.status().following_leader is None

    before = len(follower._device.points)
    leader._current = (1.0, 2.0)
    await leader._broadcast()
    assert len(follower._device.points) == before


@pytest.mark.asyncio
async def test_cannot_follow_self(tmp_path):
    c = _controller(tmp_path, "selfc")
    with pytest.raises(RuntimeError):
        await c.follow(c, "Me")
