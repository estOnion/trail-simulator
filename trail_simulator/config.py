from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "static"
DB_PATH = PROJECT_ROOT / "trail-simulator.db"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    # NOTE: 8787 can collide with the iOS device tunnel (pymobiledevice3/RSD),
    # causing tunneld stream resets (error_code=5) and silent GPS-spoof failure.
    # Override with --port (e.g. 8080) if a real-device session won't spoof.
    port: int = 8787

    tick_hz: float = 1.0
    max_speed_kmh: float = 20.0
    # 20 km/h at 1 Hz = 5.55 m/tick; cap sits above with small headroom for
    # perpendicular wobble. Stays well below the "teleport" threshold.
    max_tick_jump_m: float = 6.5
    jitter_m: float = 0.6  # perpendicular wobble amplitude (not used directly)

    osrm_base: str = "https://router.project-osrm.org"

    nominatim_base: str = "https://nominatim.openstreetmap.org"
    user_agent: str = "trail-simulator/0.1 (https://github.com/estOnion/trail-simulator)"

    tunneld_cmd: tuple[str, ...] = ("pymobiledevice3", "remote", "tunneld")
    tunneld_startup_s: float = 3.0

    reconnect_max_backoff_s: float = 30.0
    # DTX simulate_location awaits a device reply with no built-in timeout.
    # Cap each set() so a stalled tunnel triggers reconnect instead of
    # hanging the tick loop forever.
    device_set_timeout_s: float = 5.0

    step_companion_enabled: bool = True
    stride_length_m: float = 0.7

    # Cooldown after a long-distance reposition = realistic travel time to
    # cover the jump. The settle time is distance ÷ this assumed transit speed
    # (≈ driving). A 60 km jump → 60 min wait, 600 km → 10 h.
    cooldown_transit_kmh: float = 60.0


SETTINGS = Settings()


def cooldown_seconds_for_distance(m: float, transit_kmh: float | None = None) -> float:
    """Settle time after a teleport, in seconds: the time it would realistically
    take to physically travel the jumped distance at `transit_kmh`. Enforces a
    plausible gap so the simulated trail never makes an instant long jump."""
    if m <= 0:
        return 0.0
    kmh = transit_kmh if transit_kmh is not None else SETTINGS.cooldown_transit_kmh
    if kmh <= 0:
        return 0.0
    return m / (kmh * 1000.0 / 3600.0)
