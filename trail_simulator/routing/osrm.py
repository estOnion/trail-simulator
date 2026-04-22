from __future__ import annotations

import httpx
import polyline as polyline_lib

from ..config import SETTINGS


class RouteError(RuntimeError):
    pass


async def fetch_walking_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    base: str = SETTINGS.osrm_base,
    timeout_s: float = 15.0,
) -> list[tuple[float, float]]:
    """Return a list of (lat, lon) points along the walking route."""
    url = (
        f"{base}/route/v1/foot/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=full&geometries=polyline"
    )
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise RouteError(f"OSRM request failed: {e}") from e

    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteError(f"OSRM returned no route: {data.get('code')}")

    encoded = data["routes"][0]["geometry"]
    return polyline_lib.decode(encoded)  # (lat, lon) pairs
