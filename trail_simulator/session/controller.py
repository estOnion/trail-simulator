from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable

from ..config import SETTINGS
from ..device.location import DeviceUnavailable, LocationClient
from ..routing.interpolator import GaitParams, Waypoint, interpolate_route
from ..routing.osrm import RouteError, fetch_walking_route
from ..safety.cooldown import CooldownDecision, evaluate_cooldown
from ..safety.speed_cap import check_speed, distance_m
from ..safety.tick_cap import check_tick_jump
from .store import Store

log = logging.getLogger(__name__)


class SessionState(str, Enum):
    idle = "idle"
    starting = "starting"
    running = "running"
    paused = "paused"
    stopping = "stopping"
    reconnecting = "reconnecting"
    error = "error"


@dataclass
class StatusSnapshot:
    state: SessionState
    session_id: int | None
    current_lat: float | None
    current_lon: float | None
    target_lat: float | None
    target_lon: float | None
    speed_kmh: float
    progress_m: float
    total_m: float
    last_error: str | None
    cooldown_remaining_s: float
    steps_sent: int
    step_companions: list[dict]


# Listeners get snapshots pushed to them (WebSocket fan-out lives in api/ws.py).
Listener = Callable[[StatusSnapshot], Awaitable[None]]


class SessionController:
    def __init__(self, device: LocationClient, store: Store):
        self._device = device
        self._store = store
        self._state = SessionState.idle
        self._task: asyncio.Task | None = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused by default
        self._stop_flag = False

        self._session_id: int | None = None
        self._current: tuple[float, float] | None = None
        self._speed_kmh: float = 0.0
        self._progress_m: float = 0.0
        self._total_m: float = 0.0
        self._last_error: str | None = None
        self._listeners: list[Listener] = []
        self._steps_sent: int = 0
        self._step_remainder: float = 0.0

        # Saved params for auto-resume after DeviceUnavailable.
        self._last_start_params: dict | None = None
        self._reconnect_task: asyncio.Task | None = None

        # Leg queue — the in-flight leg's target is _current_leg_target;
        # upcoming legs live in _destinations. _full_destinations + _origin
        # are kept so loop laps can re-seed the queue.
        self._current_leg_target: tuple[float, float] | None = None
        self._destinations: list[tuple[float, float]] = []
        self._full_destinations: list[tuple[float, float]] = []
        self._origin: tuple[float, float] | None = None
        self._loop: bool = False

        # Mutable loop plan — retarget / change_speed / begin-leg swap
        # these between ticks.
        self._waypoints: list[Waypoint] = []
        self._wp_idx: int = 0
        self._current_leg_polyline: list[tuple[float, float]] = []
        self._retarget_lock: asyncio.Lock = asyncio.Lock()

        # Serializes start/stop so the state machine is observed settled
        # from outside. Without this, a stop in-flight can race a new
        # start and the caller hits a spurious "session already active".
        self._lifecycle_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Listener plumbing
    # ------------------------------------------------------------------ #
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    async def _broadcast(self) -> None:
        snap = self.status()
        stale: list[Listener] = []
        for fn in list(self._listeners):
            try:
                await fn(snap)
            except Exception:  # noqa: BLE001
                stale.append(fn)
        for fn in stale:
            self.remove_listener(fn)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def status(self) -> StatusSnapshot:
        cd = 0.0
        last = self._store.get_last_fix()
        if last and self._current_leg_target:
            decision = evaluate_cooldown(
                last[0], last[1], last[2],
                self._current_leg_target[0], self._current_leg_target[1],
            )
            cd = decision.required_wait_s
        from ..api.ws_steps import broadcaster as _step_broadcaster
        return StatusSnapshot(
            state=self._state,
            session_id=self._session_id,
            current_lat=self._current[0] if self._current else None,
            current_lon=self._current[1] if self._current else None,
            target_lat=self._current_leg_target[0] if self._current_leg_target else None,
            target_lon=self._current_leg_target[1] if self._current_leg_target else None,
            speed_kmh=self._speed_kmh,
            progress_m=self._progress_m,
            total_m=self._total_m,
            last_error=self._last_error,
            cooldown_remaining_s=cd,
            steps_sent=self._steps_sent,
            step_companions=_step_broadcaster.snapshot(),
        )

    async def start(
        self,
        start_lat: float,
        start_lon: float,
        destinations: list[tuple[float, float]],
        speed_kmh: float,
        loop: bool = False,
        skip_cooldown: bool = False,
    ) -> CooldownDecision:
        async with self._lifecycle_lock:
            if self._state in (
                SessionState.running,
                SessionState.starting,
                SessionState.stopping,
                SessionState.paused,
                SessionState.reconnecting,
            ):
                raise RuntimeError("session already active")
            if not destinations:
                raise RuntimeError("destinations must not be empty")

            # Cancel any pending auto-reconnect so it doesn't start a duplicate session.
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()

            speed_kmh = max(0.1, min(speed_kmh, SETTINGS.max_speed_kmh))

            # Cooldown check — only against the initial teleport (last fix → start).
            last = self._store.get_last_fix()
            last_lat = last[0] if last else None
            last_lon = last[1] if last else None
            last_ts = last[2] if last else None
            if skip_cooldown:
                km = 0.0
                if last_lat is not None and last_lon is not None:
                    km = distance_m(last_lat, last_lon, start_lat, start_lon) / 1000.0
                log.warning("cooldown override: %.1fkm jump", km)
                decision = CooldownDecision(True, 0.0, km, f"cooldown skipped ({km:.1f}km jump)")
            else:
                decision = evaluate_cooldown(
                    last_lat, last_lon, last_ts, start_lat, start_lon
                )
                if not decision.allowed:
                    self._last_error = decision.reason
                    await self._broadcast()
                    return decision

            self._state = SessionState.starting
            self._last_error = None
            self._origin = (start_lat, start_lon)
            self._full_destinations = list(destinations)
            self._destinations = list(destinations[1:])
            self._current_leg_target = destinations[0]
            self._loop = loop
            self._speed_kmh = speed_kmh
            self._current = (start_lat, start_lon)
            self._progress_m = 0.0
            self._steps_sent = 0
            self._step_remainder = 0.0
            self._stop_flag = False
            self._pause_event.set()
            # SQLite audit row — end point = last destination of the journey.
            final = destinations[-1]
            self._session_id = self._store.session_start(
                start_lat, start_lon, final[0], final[1], speed_kmh
            )

            self._last_start_params = {
                "start_lat": start_lat,
                "start_lon": start_lon,
                "destinations": list(destinations),
                "speed_kmh": speed_kmh,
                "loop": loop,
            }
            self._task = asyncio.create_task(self._run(start_lat, start_lon, speed_kmh))
            return decision

    async def pause(self) -> None:
        if self._state == SessionState.running:
            self._state = SessionState.paused
            self._pause_event.clear()
            await self._broadcast()

    async def resume(self) -> None:
        if self._state == SessionState.paused:
            self._state = SessionState.running
            self._pause_event.set()
            await self._broadcast()

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            # Idempotent — stop() when already settled is mostly a no-op,
            # but a pending auto-resume task from a prior device-error
            # session still has to be cancelled here.
            if self._state in (SessionState.idle, SessionState.error):
                self._stop_flag = True
                if self._reconnect_task and not self._reconnect_task.done():
                    self._reconnect_task.cancel()
                    try:
                        await self._reconnect_task
                    except (Exception, asyncio.CancelledError):
                        pass
                    self._reconnect_task = None
                return

            self._state = SessionState.stopping
            await self._broadcast()
            self._stop_flag = True
            self._pause_event.set()

            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except (Exception, asyncio.CancelledError):
                    pass
            self._reconnect_task = None

            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except (Exception, asyncio.CancelledError):
                    pass

            # _run's finally normally lands at idle. Defensive: ensure
            # callers waiting on /api/stop always see a settled state.
            if self._state != SessionState.idle:
                self._state = SessionState.idle
                await self._broadcast()

    async def reset_device(self) -> None:
        """Release the phone back to real GPS (full clear + disconnect).
        Only valid when settled — the UI must stop an active session first."""
        async with self._lifecycle_lock:
            if self._state not in (SessionState.idle, SessionState.error):
                raise RuntimeError("stop the session before resetting")
            try:
                await self._device.clear()
            except Exception:  # noqa: BLE001
                pass
            self._current = None
            self._current_leg_target = None
            self._last_error = None
            self._session_id = None
            self._last_start_params = None
            self._state = SessionState.idle
            await self._broadcast()

    async def update_destinations(
        self,
        destinations: list[tuple[float, float]],
        loop: bool | None = None,
    ) -> None:
        """Replace the in-flight leg target + upcoming queue mid-session.
        destinations[0] becomes the current leg's new target; destinations[1:]
        becomes the upcoming queue. If destinations[0] equals the existing
        current-leg target, no re-fetch — only the queue and loop flag mutate."""
        if self._state not in (SessionState.running, SessionState.paused):
            raise RuntimeError("no active session to update")
        if self._current is None:
            raise RuntimeError("no current position")
        if not destinations:
            raise RuntimeError("destinations must not be empty")

        async with self._retarget_lock:
            if loop is not None:
                self._loop = loop
            self._full_destinations = list(destinations)

            new_target = destinations[0]
            if new_target == self._current_leg_target:
                # Active leg unchanged — just mutate the upcoming queue.
                self._destinations = list(destinations[1:])
                if self._last_start_params is not None:
                    self._last_start_params["destinations"] = list(destinations)
                    if loop is not None:
                        self._last_start_params["loop"] = self._loop
                log.info(
                    "destinations updated (%d upcoming, loop=%s)",
                    len(self._destinations), self._loop,
                )
                await self._broadcast()
                return

            # Active target changed — hot-swap waypoints (same as retarget).
            cur_lat, cur_lon = self._current
            polyline = await fetch_walking_route(
                cur_lat, cur_lon, new_target[0], new_target[1]
            )
            now = self._current or (cur_lat, cur_lon)
            if not polyline or distance_m(
                now[0], now[1], polyline[0][0], polyline[0][1]
            ) > 0.5:
                polyline = [now, *polyline]

            self._current_leg_polyline = polyline
            self._waypoints = list(
                interpolate_route(
                    polyline,
                    speed_kmh=self._speed_kmh,
                    tick_hz=SETTINGS.tick_hz,
                    rng=random.Random(),
                    gait=GaitParams(perpendicular_jitter_m=SETTINGS.jitter_m),
                )
            )
            self._wp_idx = 1
            self._current_leg_target = new_target
            self._destinations = list(destinations[1:])
            self._total_m = _polyline_length_m(polyline)
            self._progress_m = 0.0
            log.info(
                "retargeted mid-session to %.5f,%.5f (%d wps, %d upcoming, loop=%s)",
                new_target[0], new_target[1],
                len(self._waypoints), len(self._destinations), self._loop,
            )
            if self._last_start_params is not None:
                self._last_start_params["destinations"] = list(destinations)
                if loop is not None:
                    self._last_start_params["loop"] = self._loop
        await self._broadcast()

    async def change_speed(self, speed_kmh: float) -> None:
        """Adjust commanded speed. If idle, just updates the stored value.
        If active, re-interpolates the remaining polyline from current
        position at the new cadence — no OSRM round-trip in the common
        case (polyline-trim fast path)."""
        speed_kmh = max(0.1, min(speed_kmh, SETTINGS.max_speed_kmh))

        if self._state not in (SessionState.running, SessionState.paused):
            self._speed_kmh = speed_kmh
            return

        if self._current is None or self._current_leg_target is None:
            self._speed_kmh = speed_kmh
            return

        async with self._retarget_lock:
            cur = self._current
            trimmed = _trim_polyline_from(self._current_leg_polyline, cur)
            if trimmed is None:
                # Drift too large (or no polyline on record) — re-fetch.
                trimmed = await fetch_walking_route(
                    cur[0], cur[1],
                    self._current_leg_target[0], self._current_leg_target[1],
                )
                if not trimmed or distance_m(
                    cur[0], cur[1], trimmed[0][0], trimmed[0][1]
                ) > 0.5:
                    trimmed = [cur, *trimmed]

            self._current_leg_polyline = trimmed
            self._speed_kmh = speed_kmh
            self._waypoints = list(
                interpolate_route(
                    trimmed,
                    speed_kmh=self._speed_kmh,
                    tick_hz=SETTINGS.tick_hz,
                    rng=random.Random(),
                    gait=GaitParams(perpendicular_jitter_m=SETTINGS.jitter_m),
                )
            )
            self._wp_idx = 1
            self._total_m = _polyline_length_m(trimmed)
            self._progress_m = 0.0
            log.info("speed change to %.1f km/h mid-leg", speed_kmh)
            if self._last_start_params is not None:
                self._last_start_params["speed_kmh"] = speed_kmh
        await self._broadcast()

    # ------------------------------------------------------------------ #
    # Inner loop
    # ------------------------------------------------------------------ #
    async def _run(
        self,
        start_lat: float,
        start_lon: float,
        speed_kmh: float,
    ) -> None:
        try:
            await self._device.open()

            prev_lat, prev_lon = start_lat, start_lon
            first_leg = True

            while True:
                if self._stop_flag:
                    break

                async with self._retarget_lock:
                    target = self._current_leg_target
                    if target is None:
                        break
                    src = self._current or (start_lat, start_lon)
                    polyline = await fetch_walking_route(
                        src[0], src[1], target[0], target[1]
                    )
                    # Leg continuation: prepend current so the first
                    # interpolated step is small (same guard as retarget).
                    # First leg: use OSRM-snapped origin so the iPhone
                    # teleports to the nearest road, not the raw click.
                    if not first_leg:
                        if not polyline or distance_m(
                            src[0], src[1], polyline[0][0], polyline[0][1]
                        ) > 0.5:
                            polyline = [src, *polyline]
                    self._current_leg_polyline = polyline
                    self._waypoints = list(
                        interpolate_route(
                            polyline,
                            speed_kmh=self._speed_kmh,
                            tick_hz=SETTINGS.tick_hz,
                            rng=random.Random(),
                            gait=GaitParams(perpendicular_jitter_m=SETTINGS.jitter_m),
                        )
                    )
                    self._wp_idx = 1
                    self._total_m = _polyline_length_m(polyline)
                    self._progress_m = 0.0
                    prev_lat, prev_lon = polyline[0][0], polyline[0][1]

                if first_leg:
                    # Initial teleport → OSRM-snapped origin.
                    await self._device.set(prev_lat, prev_lon)
                    self._current = (prev_lat, prev_lon)
                    self._store.set_last_fix(prev_lat, prev_lon)
                    first_leg = False

                self._state = SessionState.running
                await self._broadcast()

                prev_lat, prev_lon = await self._tick_leg(prev_lat, prev_lon)

                if self._stop_flag or self._state == SessionState.error:
                    break

                nxt = self._pop_next_leg_target()
                if nxt is None:
                    break
                self._current_leg_target = nxt

        except asyncio.CancelledError:
            pass  # stop() requested; finally block will clean up
        except RouteError as e:
            self._last_error = f"route: {e}"
            self._state = SessionState.error
        except (DeviceUnavailable, TimeoutError) as e:
            self._last_error = f"device: {e}"
            self._state = SessionState.error
        except Exception as e:  # noqa: BLE001
            self._last_error = f"unexpected: {e}"
            self._state = SessionState.error
            log.exception("session loop crashed")
        finally:
            # Ensure a clean state — covers CancelledError path where state wasn't set.
            if self._state not in (SessionState.idle, SessionState.error):
                self._state = SessionState.idle
            # Freeze: on normal stop/completion (idle) keep the DVT session open
            # holding the last spoofed point. Only release the device on error.
            if self._state == SessionState.error:
                try:
                    await self._device.clear()
                except Exception:
                    pass
            if self._session_id is not None:
                self._store.session_end(
                    self._session_id,
                    "completed" if self._state == SessionState.idle else self._state.value,
                )
            await self._broadcast()

        # If the session ended due to a device error and was not user-stopped,
        # kick off a background task to auto-resume once tunneld comes back.
        if (
            self._state == SessionState.error
            and self._last_error
            and self._last_error.startswith("device:")
            and not self._stop_flag
            and self._last_start_params is not None
        ):
            self._reconnect_task = asyncio.create_task(self._auto_resume())

    async def _auto_resume(self) -> None:
        """Poll tunneld until reachable, then restart the session from the last fix."""
        from ..device.tunneld import tunneld_reachable

        self._state = SessionState.reconnecting
        await self._broadcast()

        try:
            while True:
                await asyncio.sleep(5.0)
                if tunneld_reachable():
                    break
        except asyncio.CancelledError:
            self._state = SessionState.idle
            await self._broadcast()
            return

        # Tunneld is back — restart from the last recorded position if available.
        params = self._last_start_params
        if params is None:
            self._state = SessionState.idle
            await self._broadcast()
            return

        last = self._store.get_last_fix()
        resume_lat = last[0] if last else params["start_lat"]
        resume_lon = last[1] if last else params["start_lon"]

        self._state = SessionState.idle  # allow start() to proceed
        self._reconnect_task = None  # clear so stop() won't cancel mid-start
        try:
            await self.start(
                resume_lat,
                resume_lon,
                params["destinations"],
                params["speed_kmh"],
                loop=params["loop"],
                skip_cooldown=True,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("auto-resume failed: %s", e)
            self._state = SessionState.error
            self._last_error = f"auto-resume failed: {e}"
            await self._broadcast()

    async def _tick_leg(
        self, prev_lat: float, prev_lon: float
    ) -> tuple[float, float]:
        """Run through the current leg's waypoints. Returns final
        (prev_lat, prev_lon) when the leg completes, is stopped, or errors."""
        tick = 1.0 / SETTINGS.tick_hz
        dt_nominal = 1.0 / SETTINGS.tick_hz

        while True:
            if self._stop_flag:
                return (prev_lat, prev_lon)
            await self._pause_event.wait()
            if self._stop_flag:
                return (prev_lat, prev_lon)

            await asyncio.sleep(tick)

            # Snapshot list + index together — retarget/change_speed may
            # swap them during the sleep above. Reading both without
            # awaiting keeps them consistent for this iteration.
            wps = self._waypoints
            idx = self._wp_idx
            if idx >= len(wps):
                return (prev_lat, prev_lon)
            wp = wps[idx]

            ok_speed, kmh = check_speed(
                prev_lat, prev_lon, wp.lat, wp.lon, dt_nominal, SETTINGS.max_speed_kmh
            )
            ok_tick, jump_m = check_tick_jump(
                prev_lat, prev_lon, wp.lat, wp.lon, SETTINGS.max_tick_jump_m
            )
            if not ok_speed or not ok_tick:
                self._last_error = (
                    f"speed gate: {kmh:.1f} km/h" if not ok_speed
                    else f"tick gate: {jump_m:.1f} m jump"
                )
                log.warning(self._last_error)
                prev_lat, prev_lon = wp.lat, wp.lon
                if self._wp_idx == idx:
                    self._wp_idx = idx + 1
                continue

            try:
                await self._device.set(wp.lat, wp.lon)
            except (DeviceUnavailable, TimeoutError) as e:
                self._last_error = f"device: {e}"
                self._state = SessionState.error
                return (prev_lat, prev_lon)

            self._current = (wp.lat, wp.lon)
            self._progress_m += jump_m
            self._store.set_last_fix(wp.lat, wp.lon)
            if SETTINGS.step_companion_enabled:
                await self._emit_steps(jump_m)
            prev_lat, prev_lon = wp.lat, wp.lon
            if self._wp_idx == idx:
                self._wp_idx = idx + 1
            await self._broadcast()

    async def _emit_steps(self, delta_m: float) -> None:
        from ..api.ws_steps import broadcaster as _step_broadcaster
        if not _step_broadcaster.has_clients():
            return
        total = delta_m / SETTINGS.stride_length_m + self._step_remainder
        n = math.floor(total)
        self._step_remainder = total - n
        if n <= 0:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        n_clients = len(_step_broadcaster._clients)
        await _step_broadcaster.send({"type": "steps", "steps": n, "distance_m": delta_m, "ts": ts})
        self._steps_sent += n
        log.info("steps emitted: %d (delta %.2fm) -> %d companion(s)", n, delta_m, n_clients)

    def _pop_next_leg_target(self) -> tuple[float, float] | None:
        if self._destinations:
            return self._destinations.pop(0)
        if self._loop and self._origin is not None and self._full_destinations:
            # Lap shape: …dN → origin → d1 → d2 → … → dN → origin → …
            self._destinations = [self._origin, *self._full_destinations]
            return self._destinations.pop(0)
        return None


def _polyline_length_m(polyline: list[tuple[float, float]]) -> float:
    from geographiclib.geodesic import Geodesic
    g = Geodesic.WGS84
    return sum(
        g.Inverse(polyline[i][0], polyline[i][1], polyline[i + 1][0], polyline[i + 1][1])["s12"]
        for i in range(len(polyline) - 1)
    )


def _trim_polyline_from(
    polyline: list[tuple[float, float]],
    current: tuple[float, float],
    max_drift_m: float = 20.0,
) -> list[tuple[float, float]] | None:
    """Return a polyline rooted at `current`, dropping vertices we've
    already passed. Picks the nearest vertex and takes everything after
    it, prepended with current. Returns None if the polyline is empty or
    drift exceeds `max_drift_m` — caller should re-fetch OSRM in that case."""
    if len(polyline) < 1:
        return None
    min_i = 0
    min_d = float("inf")
    for i, p in enumerate(polyline):
        d = distance_m(current[0], current[1], p[0], p[1])
        if d < min_d:
            min_d = d
            min_i = i
    if min_d > max_drift_m:
        return None
    tail = polyline[min_i + 1:]
    if not tail:
        tail = [polyline[-1]]
    return [current, *tail]
