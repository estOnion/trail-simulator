from __future__ import annotations

import asyncio

import httpx
import polyline as polyline_lib

from ..config import SETTINGS


class RouteError(RuntimeError):
    """A route could not be planned. ``code`` is the incident code (ADR-0048)."""

    def __init__(self, message: str = "", code: str = "route.service_down") -> None:
        super().__init__(message)
        self.code = code


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
            "then reset the pins",
            code="route.no_route",
        )
    if code:
        return RouteError(
            f"routing service rejected the request (OSRM: {code}: {message}); "
            f"check the pins",
            code="route.rejected",
        )
    return RouteError(f"OSRM request failed: {e}", code="route.service_down")


def _has_osrm_code(e: httpx.HTTPStatusError) -> bool:
    try:
        return bool(e.response.json().get("code"))
    except (ValueError, AttributeError):
        return False


def _reason(e: Exception, timeout_s: float) -> str:
    """A non-empty, human-readable reason for a transport failure. httpx
    timeouts stringify as empty, so name them in words."""
    if isinstance(e, httpx.TimeoutException):
        return f"timed out after {timeout_s:g} s"
    return str(e) or type(e).__name__


async def fetch_walking_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    base: str = SETTINGS.osrm_base,
    timeout_s: float = 15.0,
    retry_delay_s: float = 1.0,
) -> list[tuple[float, float]]:
    """Return a list of (lat, lon) points along the walking route.

    A request that gets no answer, or a 5xx without an OSRM code, is sent once
    more after ``retry_delay_s`` (router retry, ADR-0052). Coded rejections,
    other 4xx answers and bad success bodies are final.
    """
    url = (
        f"{base}/route/v1/foot/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=full&geometries=polyline"
    )
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in (1, 2):
            try:
                r = await client.get(url)
                r.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                retryable = e.response.status_code >= 500 and not _has_osrm_code(e)
                if retryable and attempt == 1:
                    await asyncio.sleep(retry_delay_s)
                    continue
                raise _status_error(e) from e
            except httpx.TransportError as e:
                if attempt == 1:
                    await asyncio.sleep(retry_delay_s)
                    continue
                raise RouteError(
                    f"routing service unreachable ({_reason(e, timeout_s)}; "
                    f"tried twice): the backend could not reach OSRM, while "
                    f"the app's connection to the backend is fine; check the "
                    f"host's internet connection",
                    code="route.service_down",
                ) from e
            except httpx.HTTPError as e:
                raise RouteError(
                    f"routing service unreachable ({_reason(e, timeout_s)}; "
                    f"tried once): the backend could not reach OSRM, while "
                    f"the app's connection to the backend is fine; check the "
                    f"host's internet connection",
                    code="route.service_down",
                ) from e

    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteError(
            f"OSRM returned no route: {data.get('code')}", code="route.service_down"
        )

    encoded = data["routes"][0]["geometry"]
    return polyline_lib.decode(encoded)  # (lat, lon) pairs
