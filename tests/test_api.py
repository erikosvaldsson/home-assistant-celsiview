"""Unit tests for the Celsiview API client."""

from __future__ import annotations

import json

import aiohttp
import pytest
from aiohttp import web
from api import (
    CELSIVIEW_EPOCH,
    HISTORY_CHUNK_SECONDS,
    CelsiviewApiError,
    CelsiviewAuthError,
    CelsiviewClient,
    Location,
    Sample,
    _as_float,
    _as_int,
    _extract_locations,
    _parse_history_response,
    _refstr,
)

SAMPLE_LOCATION = {
    "zid": "e53f2dc011da633a1f94ff8273688c1d",
    "name": "Dilatation 1a watercontent",
    "last_value": 9.94,
    "last_unit": "g/m³",
    "last_stype": "AAH",
    "last_value_time": 1777022015,
    "account_zid": "38f6ca5b8898c89e129cf16cf412da19",
    "group_zid": None,
}


# --- helpers ---------------------------------------------------------------


def test_refstr_string() -> None:
    assert _refstr("plain") == "plain"


def test_refstr_list_form() -> None:
    # Celsiview ``refstr`` may be a ["ref", "display name"] pair
    assert _refstr(["ref:xyz", "Display"]) == "Display"


def test_refstr_none() -> None:
    assert _refstr(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("1.5", 1.5), (1, 1.0), ("nan", float("nan"))],
)
def test_as_float(value, expected) -> None:
    result = _as_float(value)
    if expected is None:
        assert result is None
    elif isinstance(expected, float) and expected != expected:  # NaN
        assert result != result
    else:
        assert result == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("7", 7), (3, 3), ("not-an-int", None)],
)
def test_as_int(value, expected) -> None:
    assert _as_int(value) == expected


def test_extract_locations_envelope() -> None:
    data = {"truncated": False, "locations": [SAMPLE_LOCATION, {"zid": "other"}]}
    assert _extract_locations(data) == [SAMPLE_LOCATION, {"zid": "other"}]


def test_extract_locations_bare_list() -> None:
    data = [SAMPLE_LOCATION]
    assert _extract_locations(data) == [SAMPLE_LOCATION]


def test_extract_locations_single_dict() -> None:
    assert _extract_locations(SAMPLE_LOCATION) == [SAMPLE_LOCATION]


def test_extract_locations_unknown_shape() -> None:
    assert _extract_locations({"unexpected": "payload"}) == []


def test_location_from_api_happy() -> None:
    loc = Location.from_api(SAMPLE_LOCATION)
    assert loc.zid == SAMPLE_LOCATION["zid"]
    assert loc.name == SAMPLE_LOCATION["name"]
    assert loc.last_value == 9.94
    assert loc.last_unit == "g/m³"
    assert loc.last_stype == "AAH"
    assert loc.last_value_time == 1777022015
    assert loc.group_zid is None


def test_location_from_api_missing_optionals() -> None:
    loc = Location.from_api(
        {
            "zid": "abc",
            "name": "",
            "last_value": "",
            "last_value_time": None,
        }
    )
    assert loc.zid == "abc"
    # Empty name should fall back to zid so the entity always has a label.
    assert loc.name == "abc"
    assert loc.last_value is None
    assert loc.last_value_time is None
    assert loc.last_unit is None
    assert loc.last_stype is None


def test_location_from_api_refstr_name() -> None:
    loc = Location.from_api({"zid": "abc", "name": ["ref:xyz", "Fridge 1"], "last_value": 3})
    assert loc.name == "Fridge 1"


# --- signing --------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_without_secret() -> None:
    async with aiohttp.ClientSession() as session:
        client = CelsiviewClient(session, "https://example.invalid", "APPKEY")
        headers = client._sign("GET", "/api/v2/locations", b"")
        assert headers == {"X-Application-Key": "APPKEY"}


@pytest.mark.asyncio
async def test_sign_with_secret_adds_request_headers() -> None:
    async with aiohttp.ClientSession() as session:
        client = CelsiviewClient(
            session, "https://example.invalid", "APPKEY", client_secret="SECRET"
        )
        headers = client._sign("GET", "/api/v2/locations", b"")
        assert headers["X-Application-Key"] == "APPKEY"
        assert "X-Request-Key" in headers
        assert "X-Request-Timestamp" in headers
        assert "X-Request-Nonce" in headers
        assert len(headers["X-Request-Key"]) == 64  # HMAC-SHA256 hex


# --- HTTP behaviour via a local aiohttp server -----------------------------


@pytest.fixture
async def celsiview_server(aiohttp_server):  # type: ignore[no-untyped-def]
    """Spin up a small aiohttp server whose behaviour is driven per-test."""

    handlers: dict[str, web.RequestHandler] = {}

    async def _dispatch(request: web.Request) -> web.StreamResponse:
        handler = handlers.get(request.path)
        if handler is None:
            return web.Response(status=404, text="not found")
        return await handler(request)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", _dispatch)
    server = await aiohttp_server(app)
    server.handlers = handlers  # attach so tests can register responses
    return server


def _client_for(server) -> CelsiviewClient:  # type: ignore[no-untyped-def]
    """Return a client pointed at the test server, sharing no session."""
    session = aiohttp.ClientSession()
    client = CelsiviewClient(session, str(server.make_url("")), "APPKEY")
    client._owned_session = session  # remembered for teardown
    return client


async def _aclose(client: CelsiviewClient) -> None:
    session = getattr(client, "_owned_session", None)
    if session is not None:
        await session.close()


@pytest.mark.asyncio
async def test_list_locations_happy(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    async def handler(request: web.Request) -> web.Response:
        assert request.headers.get("X-Application-Key") == "APPKEY"
        return web.json_response({"truncated": False, "locations": [SAMPLE_LOCATION]})

    celsiview_server.handlers["/api/v2/locations"] = handler

    client = _client_for(celsiview_server)
    try:
        locs = await client.list_locations()
        assert len(locs) == 1
        assert locs[0].zid == SAMPLE_LOCATION["zid"]
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_redirect_is_auth_error(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=302, headers={"Location": "/login"})

    celsiview_server.handlers["/api/v2/locations"] = handler

    client = _client_for(celsiview_server)
    try:
        with pytest.raises(CelsiviewAuthError):
            await client.list_locations()
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_401_is_auth_error(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"message": "Invalid application key."}, status=401)

    celsiview_server.handlers["/api/v2/locations"] = handler

    client = _client_for(celsiview_server)
    try:
        with pytest.raises(CelsiviewAuthError):
            await client.list_locations()
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_invalid_json_includes_body_preview(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    async def handler(request: web.Request) -> web.Response:
        return web.Response(
            status=200,
            text="<html>not json</html>",
            content_type="application/json",
        )

    celsiview_server.handlers["/api/v2/locations"] = handler

    client = _client_for(celsiview_server)
    try:
        with pytest.raises(CelsiviewApiError) as excinfo:
            await client.list_locations()
        assert "not json" in str(excinfo.value)
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_get_locations_filters_selection(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    other = dict(SAMPLE_LOCATION, zid="otherzid", name="Other")

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"truncated": False, "locations": [SAMPLE_LOCATION, other]})

    celsiview_server.handlers["/api/v2/locations"] = handler

    client = _client_for(celsiview_server)
    try:
        subset = await client.get_locations([SAMPLE_LOCATION["zid"]])
        assert set(subset.keys()) == {SAMPLE_LOCATION["zid"]}
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_get_locations_empty_returns_empty(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    client = _client_for(celsiview_server)
    try:
        # No HTTP call should be made when the selection is empty.
        assert await client.get_locations([]) == {}
    finally:
        await _aclose(client)


# --- history parsing ------------------------------------------------------


ZID = "a44b1ca98845324c77356912e6779631"


def test_parse_history_basic() -> None:
    data = {ZID: {"status": "ok", "times": [100, 200, 300], "values": [1.0, 2.0, 3.0]}}
    samples = _parse_history_response(data, ZID, 0, 1000)
    assert samples == [Sample(100, 1.0), Sample(200, 2.0), Sample(300, 3.0)]


def test_parse_history_trims_out_of_range() -> None:
    # The Celsiview server sometimes returns samples outside the requested
    # window; those must be discarded so we don't pollute statistics.
    data = {ZID: {"times": [50, 150, 250, 2000], "values": [0.5, 1.5, 2.5, 20.0]}}
    samples = _parse_history_response(data, ZID, 100, 300)
    assert [s.ts for s in samples] == [150, 250]


def test_parse_history_drops_none_values() -> None:
    data = {ZID: {"times": [100, 200, 300], "values": [1.0, None, 3.0]}}
    samples = _parse_history_response(data, ZID, 0, 1000)
    assert [s.ts for s in samples] == [100, 300]


def test_parse_history_sorts_by_ts() -> None:
    data = {ZID: {"times": [300, 100, 200], "values": [3.0, 1.0, 2.0]}}
    samples = _parse_history_response(data, ZID, 0, 1000)
    assert [s.ts for s in samples] == [100, 200, 300]


def test_parse_history_empty() -> None:
    data = {ZID: {"status": "ok", "times": [], "values": []}}
    assert _parse_history_response(data, ZID, 0, 1000) == []


def test_parse_history_missing_zid_raises() -> None:
    with pytest.raises(CelsiviewApiError):
        _parse_history_response("not a dict", ZID, 0, 1000)


# --- fetch_history via test server ----------------------------------------


@pytest.mark.asyncio
async def test_fetch_history_passes_startTime_endTime(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    received: dict[str, str] = {}
    start = CELSIVIEW_EPOCH + 1_000_000
    end = start + 100
    mid = start + 50

    async def handler(request: web.Request) -> web.Response:
        received.update(request.rel_url.query)
        return web.json_response({ZID: {"times": [mid], "values": [1.5]}})

    celsiview_server.handlers[f"/api/v2/location/{ZID}/history"] = handler

    client = _client_for(celsiview_server)
    try:
        samples = await client.fetch_history(ZID, start, end)
        assert received["startTime"] == str(start)
        assert received["endTime"] == str(end)
        assert samples == [Sample(mid, 1.5)]
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_fetch_history_clamps_to_epoch(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    received: list[dict[str, str]] = []

    async def handler(request: web.Request) -> web.Response:
        received.append(dict(request.rel_url.query))
        return web.json_response({ZID: {"times": [], "values": []}})

    celsiview_server.handlers[f"/api/v2/location/{ZID}/history"] = handler

    client = _client_for(celsiview_server)
    try:
        # start=0 should be clamped forward to 2010-01-01
        await client.fetch_history(ZID, 0, CELSIVIEW_EPOCH + 100)
        assert received, "expected at least one request"
        assert int(received[0]["startTime"]) == CELSIVIEW_EPOCH
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_fetch_history_chunks_large_windows(celsiview_server) -> None:  # type: ignore[no-untyped-def]
    received: list[tuple[int, int]] = []

    async def handler(request: web.Request) -> web.Response:
        q = request.rel_url.query
        received.append((int(q["startTime"]), int(q["endTime"])))
        return web.json_response({ZID: {"times": [], "values": []}})

    celsiview_server.handlers[f"/api/v2/location/{ZID}/history"] = handler

    # Ask for 2 * chunk + 100 seconds of history: expect 3 chunks.
    start = CELSIVIEW_EPOCH + 1
    end = start + 2 * HISTORY_CHUNK_SECONDS + 100
    client = _client_for(celsiview_server)
    try:
        await client.fetch_history(ZID, start, end)
        assert len(received) == 3
        # chunks must be contiguous, cover the whole window, and none can
        # exceed the configured chunk size
        assert received[0][0] == start
        assert received[-1][1] == end
        for s, e in received:
            assert 0 < e - s <= HISTORY_CHUNK_SECONDS
        for i in range(len(received) - 1):
            assert received[i][1] == received[i + 1][0]
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_fetch_history_empty_window() -> None:
    async with aiohttp.ClientSession() as session:
        client = CelsiviewClient(session, "https://example.invalid", "APPKEY")
        # end <= start should short-circuit without any HTTP call
        assert await client.fetch_history(ZID, 200, 100) == []
        assert await client.fetch_history(ZID, 200, 200) == []


# --- JSON file validation -------------------------------------------------


def test_shipped_json_is_parseable() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in (
        "custom_components/celsiview/manifest.json",
        "custom_components/celsiview/strings.json",
        "custom_components/celsiview/translations/en.json",
        "hacs.json",
    ):
        with (root / rel).open() as fh:
            json.load(fh)
