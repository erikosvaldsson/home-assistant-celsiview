"""Client for the Celsiview HTTP API.

The Celsiview API (v2) is a REST-ish service hosted at `app.celsiview.se`.
Authentication is performed with an application key obtained from
`https://app.celsiview.se/api/keys`. If the API key has
`client_secret_required` set, a client-secret-derived request key must
also be included on every call.

Only the small subset of endpoints needed by the Home Assistant
integration is implemented here:

* ``GET /api/v2/locations``       - list locations (with last value)
* ``GET /api/v2/location/{zid}``  - fetch a single location

`Location` is the primary entity exposed to Home Assistant: each location
holds a time series of samples and carries ``last_value``,
``last_value_time``, ``last_unit`` and ``last_stype`` fields. A location
is what becomes a Home Assistant sensor entity.

If the exact header names or signature scheme used by Celsiview differ
from the assumptions here, only this file needs to change - the rest of
the integration treats the client as an opaque service.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import aiohttp

_LOGGER = logging.getLogger(__name__)

HEADER_APPLICATION_KEY = "X-Application-Key"
# The following headers are used when the API key has
# `client_secret_required` enabled. The exact names and signing payload
# format used by Celsiview for the request-key HMAC are not documented in
# the public API reference; the values below are best-effort placeholders.
# If your API key requires a client secret and authentication fails,
# adjust these constants and/or `_sign` below to match the Celsiview
# implementation.
HEADER_REQUEST_KEY = "X-Request-Key"
HEADER_TIMESTAMP = "X-Request-Timestamp"
HEADER_NONCE = "X-Request-Nonce"


class CelsiviewError(Exception):
    """Base error raised by the Celsiview client."""


class CelsiviewAuthError(CelsiviewError):
    """Raised when the server rejects the provided credentials."""


class CelsiviewApiError(CelsiviewError):
    """Raised when the server returns a non-auth error."""


@dataclass(frozen=True)
class Location:
    """Subset of a Celsiview Location relevant to Home Assistant."""

    zid: str
    name: str
    last_value: float | None
    last_unit: str | None
    last_stype: str | None
    last_value_time: int | None
    account_zid: str | None = None
    group_zid: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Location:
        """Build a Location from the raw API payload."""
        return cls(
            zid=data["zid"],
            name=_refstr(data.get("name")) or data["zid"],
            last_value=_as_float(data.get("last_value")),
            last_unit=data.get("last_unit"),
            last_stype=data.get("last_stype"),
            last_value_time=_as_int(data.get("last_value_time")),
            account_zid=data.get("account_zid"),
            group_zid=data.get("group_zid"),
        )


def _refstr(value: Any) -> str | None:
    """Resolve a Celsiview ``refstr`` to a plain string."""
    if value is None:
        return None
    if isinstance(value, list) and len(value) >= 2:
        return str(value[1])
    return str(value)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CelsiviewClient:
    """Small async client for the Celsiview API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        application_key: str,
        client_secret: str | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._application_key = application_key
        self._client_secret = client_secret or None
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _sign(self, method: str, path: str, body: bytes) -> dict[str, str]:
        """Return signing headers for a request."""
        headers = {HEADER_APPLICATION_KEY: self._application_key}
        if self._client_secret:
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(8)
            payload = "\n".join(
                [method.upper(), path, timestamp, nonce, body.decode("utf-8", "replace")]
            ).encode("utf-8")
            digest = hmac.new(
                self._client_secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
            headers[HEADER_TIMESTAMP] = timestamp
            headers[HEADER_NONCE] = nonce
            headers[HEADER_REQUEST_KEY] = digest
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = urljoin(self._base_url + "/", path.lstrip("/"))
        body = b"" if json_body is None else _json_dumps(json_body)
        headers = self._sign(method, path, body)
        headers["Accept"] = "application/json"
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                data=body if json_body is not None else None,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                text = await resp.text()
                # Unauthenticated requests redirect to /login; treat that
                # as an auth error rather than chasing the redirect.
                if 300 <= resp.status < 400:
                    raise CelsiviewAuthError(
                        f"Unauthenticated ({resp.status} redirect to "
                        f"{resp.headers.get('Location', '?')}). "
                        f"Check application key."
                    )
                if resp.status in (401, 403):
                    raise CelsiviewAuthError(f"Authentication failed ({resp.status}): {text[:200]}")
                if resp.status >= 400:
                    raise CelsiviewApiError(f"{method} {path} failed ({resp.status}): {text[:200]}")
                if not text:
                    return None
                try:
                    return _json_loads(text)
                except ValueError as err:
                    raise CelsiviewApiError(
                        f"Invalid JSON from {path}: {err}. First 200 chars: {text[:200]!r}"
                    ) from err
        except TimeoutError as err:
            raise CelsiviewApiError(f"Timeout on {method} {path}") from err
        except aiohttp.ClientError as err:
            raise CelsiviewApiError(f"HTTP error on {method} {path}: {err}") from err

    async def verify_credentials(self) -> None:
        """Perform a lightweight call to verify the credentials."""
        await self.list_locations()

    async def list_locations(self) -> list[Location]:
        """Return every location visible to the API key."""
        data = await self._request(
            "GET",
            "/api/v2/locations",
            params={"include": "locations"},
        )
        raw_locations = _extract_locations(data)
        return [Location.from_api(item) for item in raw_locations]

    async def get_location(self, zid: str) -> Location:
        """Return a single location by zid.

        The single-location endpoint returns the same envelope shape as
        the list endpoint, just filtered to one location, so we reuse
        the list extractor.
        """
        data = await self._request("GET", f"/api/v2/location/{zid}")
        raw_list = _extract_locations(data)
        match = next((item for item in raw_list if item.get("zid") == zid), None)
        if match is None:
            raise CelsiviewApiError(f"Unexpected payload for location {zid}: {data!r}")
        return Location.from_api(match)

    async def get_locations(self, zids: list[str]) -> dict[str, Location]:
        """Return the selected locations keyed by zid.

        Internally this calls ``list_locations`` once and filters the
        result, which keeps the number of HTTP calls to the API at one
        per poll regardless of how many sensors the user has selected.
        """
        if not zids:
            return {}
        wanted = set(zids)
        all_locations = await self.list_locations()
        return {loc.zid: loc for loc in all_locations if loc.zid in wanted}


def _extract_locations(data: Any) -> list[dict[str, Any]]:
    """Pull the location list out of a `/api/v2/locations` response."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("locations", "values", "data", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if "zid" in data:
            return [data]
    return []


def _json_dumps(data: Any) -> bytes:
    import json

    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _json_loads(text: str) -> Any:
    import json

    return json.loads(text)
