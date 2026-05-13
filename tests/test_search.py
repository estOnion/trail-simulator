from __future__ import annotations

import httpx
import pytest

from trail_simulator.geocode import GeocodeError, search


NOMINATIM_SAMPLE = [
    {
        "place_id": 12345,
        "display_name": "Taipei 101, Xinyi District, Taipei City, Taiwan",
        "lat": "25.0330",
        "lon": "121.5654",
        "type": "attraction",
        "importance": 0.82,
    },
    {
        "place_id": 67890,
        "display_name": "Taipei 101/World Trade Center MRT Station, Taipei City, Taiwan",
        "lat": "25.0329",
        "lon": "121.5678",
        "type": "station",
    },
]


@pytest.mark.asyncio
async def test_normalizes_nominatim_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=NOMINATIM_SAMPLE)

    results = await search("Taipei 101", transport=httpx.MockTransport(handler))

    assert len(results) == 2
    first = results[0]
    assert set(first.keys()) == {"display_name", "lat", "lon", "type"}
    assert first["display_name"].startswith("Taipei 101")
    assert isinstance(first["lat"], float)
    assert isinstance(first["lon"], float)
    assert abs(first["lat"] - 25.0330) < 1e-4
    assert abs(first["lon"] - 121.5654) < 1e-4
    assert first["type"] == "attraction"


@pytest.mark.asyncio
async def test_forwards_user_agent_and_query_params():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers.get("user-agent", "")
        captured["q"] = request.url.params.get("q")
        captured["limit"] = request.url.params.get("limit")
        captured["format"] = request.url.params.get("format")
        return httpx.Response(200, json=[])

    await search(
        "Starbucks Xinyi",
        limit=5,
        user_agent="trail-simulator-test/9.9",
        transport=httpx.MockTransport(handler),
    )

    assert captured["user_agent"] == "trail-simulator-test/9.9"
    assert captured["q"] == "Starbucks Xinyi"
    assert captured["limit"] == "5"
    assert captured["format"] == "jsonv2"


@pytest.mark.asyncio
async def test_http_error_raises_geocode_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(GeocodeError):
        await search("foo", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_skips_malformed_items_without_failing():
    payload = [
        {"display_name": "good", "lat": "1.0", "lon": "2.0", "type": "x"},
        {"display_name": "no-coords"},
        {"display_name": "bad-lat", "lat": "abc", "lon": "2.0"},
        {"display_name": "typeless", "lat": "3.0", "lon": "4.0"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    results = await search("foo", transport=httpx.MockTransport(handler))

    assert [r["display_name"] for r in results] == ["good", "typeless"]
    assert results[1]["type"] == ""
