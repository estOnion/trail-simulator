from __future__ import annotations

import httpx
import polyline as polyline_lib

from ..config import SETTINGS


class RouteError(RuntimeError):
    pass


def _status_error(e: httpx.HTTPStatusError) -> RouteError:
    """Translate an OSRM error response into a message that tells the user
    whether the problem is their pins or the service.

    OSRM answers 400 with a JSON body such as
    ``{"code": "NoRoute", "message": "Impossible route between points"}``.
    Without reading it, every failure looks like a generic HTTP error and
    users assume the server is down.
    """
    try:
        body = e.response.json()
        code = body.get("code")
        message = body.get("message", "")
    except ValueError:
        code, message = None, ""

    if code == "NoRoute":
        return RouteError(
            "no walking route between the selected points (OSRM: NoRoute); "
            "check that origin and destination are on the same landmass, "
            "then reset the pins"
        )
    if code:
        return RouteError(
            f"routing service rejected the request (OSRM: {code}: {message}); "
            f"check the pins"
        )
    return RouteError(f"OSRM request failed: {e}")


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
        except httpx.HTTPStatusError as e:
            raise _status_error(e) from e
        except httpx.HTTPError as e:
            raise RouteError(
                f"routing service unreachable ({e}); the backend could not "
                f"reach OSRM — check its internet connection"
            ) from e

    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteError(f"OSRM returned no route: {data.get('code')}")

    encoded = data["routes"][0]["geometry"]
    return polyline_lib.decode(encoded)  # (lat, lon) pairs
