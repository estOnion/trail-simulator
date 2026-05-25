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


SETTINGS = Settings()


# Distance-based cooldown table (distance km -> minutes).
# Enforces a settle time after long-distance repositions so the simulated
# trail never makes an implausible instant jump. A lookup returns the
# cooldown of the largest tier <= the distance travelled.
COOLDOWN_TABLE: list[tuple[float, float]] = [
    (1.0, 0.5),
    (2.0, 1.0),
    (4.0, 2.0),
    (10.0, 8.0),
    (25.0, 12.0),
    (50.0, 18.0),
    (100.0, 28.0),
    (250.0, 40.0),
    (500.0, 50.0),
    (750.0, 60.0),
    (1000.0, 70.0),
    (1500.0, 120.0),
]


def cooldown_minutes_for_distance(km: float) -> float:
    if km <= 0:
        return 0.0
    chosen = 0.0
    for threshold_km, minutes in COOLDOWN_TABLE:
        if km >= threshold_km:
            chosen = minutes
        else:
            break
    return chosen
