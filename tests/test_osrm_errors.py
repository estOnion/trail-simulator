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
    assert ei.value.code == "route.no_route"


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
    assert ei.value.code == "route.rejected"


@pytest.mark.asyncio
async def test_non_json_http_error_falls_back_to_generic(monkeypatch):
    def handler(request):
        return httpx.Response(502, text="bad gateway")

    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert "OSRM request failed" in str(ei.value)
    assert ei.value.code == "route.service_down"


@pytest.mark.asyncio
async def test_transport_failure_says_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert "routing service unreachable" in str(ei.value)
    assert "tried twice" in str(ei.value)
    assert ei.value.code == "route.service_down"


_OK_BODY = {
    "code": "Ok",
    "routes": [{"geometry": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"}],
}


def _counting_handler(responses):
    """Handler returning/raising items of ``responses`` in order (last repeats)."""
    calls = []

    def handler(request):
        item = responses[min(len(calls), len(responses) - 1)]
        calls.append(request)
        if isinstance(item, Exception):
            raise item
        return item

    handler.calls = calls
    return handler


@pytest.mark.asyncio
async def test_retry_then_success(monkeypatch):
    handler = _counting_handler(
        [httpx.ReadTimeout(""), httpx.Response(200, json=_OK_BODY)]
    )
    _mock_client(monkeypatch, handler)
    pts = await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 2
    assert len(pts) >= 2


@pytest.mark.asyncio
async def test_two_connect_errors_send_two_requests_and_say_so(monkeypatch):
    handler = _counting_handler([httpx.ConnectError("connection refused")])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 2
    msg = str(ei.value)
    assert ei.value.code == "route.service_down"
    assert "routing service unreachable" in msg
    assert "connection refused" in msg
    assert "tried twice" in msg
    assert "connection to the backend is fine" in msg


@pytest.mark.asyncio
async def test_non_transport_http_error_is_not_retried_and_says_tried_once(monkeypatch):
    handler = _counting_handler([httpx.DecodingError("bad gzip")])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 1
    assert ei.value.code == "route.service_down"
    assert "tried once" in str(ei.value)
    assert "tried twice" not in str(ei.value)


@pytest.mark.asyncio
async def test_timeout_with_empty_text_is_named_in_words(monkeypatch):
    handler = _counting_handler([httpx.ReadTimeout("")])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    msg = str(ei.value)
    assert "timed out after 15 s" in msg
    assert "()" not in msg


@pytest.mark.asyncio
async def test_empty_non_timeout_error_falls_back_to_type_name(monkeypatch):
    handler = _counting_handler([httpx.ConnectError("")])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert "ConnectError" in str(ei.value)
    assert "()" not in str(ei.value)


@pytest.mark.asyncio
async def test_5xx_without_code_is_retried(monkeypatch):
    handler = _counting_handler([httpx.Response(503, text="busy")])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError) as ei:
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 2
    assert "OSRM request failed" in str(ei.value)
    assert ei.value.code == "route.service_down"


@pytest.mark.asyncio
async def test_5xx_then_success_returns_route(monkeypatch):
    handler = _counting_handler(
        [httpx.Response(503, text="busy"), httpx.Response(200, json=_OK_BODY)]
    )
    _mock_client(monkeypatch, handler)
    pts = await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 2 and pts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"code": "NoRoute", "message": "x"}),
        httpx.Response(400, json={"code": "InvalidQuery", "message": "x"}),
        httpx.Response(429, json={"code": "TooBig", "message": "x"}),
        httpx.Response(429, text="slow down"),
        httpx.Response(500, json={"code": "InternalError", "message": "x"}),
    ],
    ids=["noroute", "coded-400", "coded-429", "bare-429", "coded-500"],
)
async def test_final_answers_are_not_retried(monkeypatch, response):
    handler = _counting_handler([response])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError):
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 1


@pytest.mark.asyncio
async def test_success_without_usable_route_is_not_retried(monkeypatch):
    handler = _counting_handler([httpx.Response(200, json={"code": "NoSegment"})])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError):
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm", retry_delay_s=0)
    assert len(handler.calls) == 1


@pytest.mark.asyncio
async def test_retry_waits_the_configured_delay(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(osrm.asyncio, "sleep", fake_sleep)
    handler = _counting_handler([httpx.ConnectError("x")])
    _mock_client(monkeypatch, handler)
    with pytest.raises(RouteError):
        await fetch_walking_route(0, 0, 1, 1, base="http://osrm")
    assert sleeps == [1.0]
