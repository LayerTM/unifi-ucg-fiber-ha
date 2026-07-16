"""Authentication strategies for the UniFi OS / Network local REST API.

Two interchangeable strategies:

* :class:`ApiKeyAuth` — sends ``X-API-Key`` on every request; no handshake. On
  the UCG-Fiber this key reaches the rich classic ``/stat/*`` endpoints, so it is
  the recommended read-only default.
* :class:`SessionAuth` — primes a CSRF token from the console root, logs in via
  ``POST /api/auth/login``, and captures the ``TOKEN`` cookie manually (a shared
  ``aiohttp`` session backed by an IP host will not persist it otherwise). This
  is the fallback for keys scoped to the Integration API only, and the auth
  required for control (write) actions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import aiohttp

from .const import (
    COOKIE_TOKEN,
    HEADER_API_KEY,
    HEADER_CSRF,
    HEADER_CSRF_UPDATED,
    PATH_LOGIN,
)
from .exceptions import GwAuthError


class AbstractAuth(ABC):
    """Strategy interface consumed by the transport."""

    can_reauth: bool = False

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Return auth headers to attach to every request."""

    async def async_prepare(
        self, session: aiohttp.ClientSession, base_url: str, *, ssl: bool = True
    ) -> None:
        """Perform any handshake needed before the first request (default: none)."""
        return None

    async def async_reauth(
        self, session: aiohttp.ClientSession, base_url: str, *, ssl: bool = True
    ) -> bool:
        """Re-authenticate after a 401. Return True if a retry is worthwhile."""
        return False


class ApiKeyAuth(AbstractAuth):
    """Static ``X-API-Key`` authentication (recommended for read-only)."""

    can_reauth = False

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def headers(self) -> dict[str, str]:
        return {HEADER_API_KEY: self._api_key}


class SessionAuth(AbstractAuth):
    """Local-account session authentication (CSRF + TOKEN cookie)."""

    can_reauth = True

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._csrf: str | None = None
        self._token: str | None = None

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._csrf:
            headers[HEADER_CSRF] = self._csrf
        if self._token:
            headers["Cookie"] = f"{COOKIE_TOKEN}={self._token}"
        return headers

    async def async_prepare(
        self, session: aiohttp.ClientSession, base_url: str, *, ssl: bool = True
    ) -> None:
        await self._login(session, base_url, ssl)

    async def async_reauth(
        self, session: aiohttp.ClientSession, base_url: str, *, ssl: bool = True
    ) -> bool:
        await self._login(session, base_url, ssl)
        return True

    async def _login(self, session: aiohttp.ClientSession, base_url: str, ssl: bool) -> None:
        # 1) prime CSRF from the console root
        try:
            async with session.get(f"{base_url}/", ssl=ssl) as resp:
                self._capture(resp)
        except aiohttp.ClientError as err:
            raise GwAuthError(f"could not reach console: {err}") from err

        # 2) log in
        payload = {
            "username": self._username,
            "password": self._password,
            "rememberMe": True,
            "remember": True,
        }
        request_headers = {HEADER_CSRF: self._csrf} if self._csrf else {}
        try:
            async with session.post(
                f"{base_url}{PATH_LOGIN}", json=payload, headers=request_headers, ssl=ssl
            ) as resp:
                if resp.status in (401, 403):
                    raise GwAuthError("invalid credentials")
                if resp.status >= 400:
                    raise GwAuthError(f"login failed with status {resp.status}")
                self._capture(resp)
        except aiohttp.ClientError as err:
            raise GwAuthError(f"login request failed: {err}") from err

        if not self._token:
            raise GwAuthError("login did not return a session token")

    def _capture(self, resp: aiohttp.ClientResponse) -> None:
        csrf = resp.headers.get(HEADER_CSRF) or resp.headers.get(HEADER_CSRF_UPDATED)
        if csrf:
            self._csrf = csrf
        for raw in resp.headers.getall("Set-Cookie", []):
            first = raw.split(";", 1)[0].strip()
            if first.startswith(f"{COOKIE_TOKEN}="):
                self._token = first[len(COOKIE_TOKEN) + 1 :]
                break
