from __future__ import annotations

import httpx

from .config import SETTINGS


class GeocodeError(RuntimeError):
    pass


async def search(
    q: str,
    limit: int = 8,
    base: str | None = None,
    user_agent: str | None = None,
    timeout_s: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict]:
    """Call Nominatim /search and return a list of {display_name, lat, lon, type}.

    The `transport` kwarg lets tests inject `httpx.MockTransport`.
    """
    url = f"{(base or SETTINGS.nominatim_base).rstrip('/')}/search"
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": str(limit),
        "addressdetails": "0",
    }
    headers = {"User-Agent": user_agent or SETTINGS.user_agent}
    async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise GeocodeError(f"Nominatim request failed: {e}") from e

    raw = r.json()
    if not isinstance(raw, list):
        raise GeocodeError("Nominatim returned non-list payload")

    results: list[dict] = []
    for item in raw:
        try:
            results.append(
                {
                    "display_name": item["display_name"],
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "type": item.get("type", ""),
                }
            )
        except (KeyError, ValueError, TypeError):
            continue
    return results
