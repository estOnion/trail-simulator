from __future__ import annotations

import httpx
import pytest

from trail_simulator.routing import osrm
from trail_simulator.routing.osrm import RouteError, fetch_walking_route


def _mock_client(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(osrm.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_no_route_names_the_pins_not_the_server(monkeypatch):
    def handler(request):
        return httpx.Response(
            400, json={"code": "NoRoute", "message": "Impossible route between points"}
        )

    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(37.6, 126.9, 22.8, 120.3, base="http://osrm")
    msg = str(ei.value)
    assert "no walking route" in msg
    assert "NoRoute" in msg
    assert "reset the pins" in msg


@pytest.mark.asyncio
async def test_other_osrm_rejection_includes_code_and_message(monkeypatch):
    def handler(request):
        return httpx.Response(
            400, json={"code": "InvalidQuery", "message": "Query string malformed"}
        )

    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm")
    assert "InvalidQuery" in str(ei.value)
    assert "Query string malformed" in str(ei.value)


@pytest.mark.asyncio
async def test_non_json_http_error_falls_back_to_generic(monkeypatch):
    def handler(request):
        return httpx.Response(502, text="bad gateway")

    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm")
    assert "OSRM request failed" in str(ei.value)


@pytest.mark.asyncio
async def test_transport_failure_says_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm")
    assert "routing service unreachable" in str(ei.value)
