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
from .exceptions import GwAuthError, GwConnectionError


class AbstractAuth(ABC):
    """Strategy interface consumed by the transport."""

    can_reauth: bool = False

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Return auth headers to attach to every request."""

    async def async_prepare(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> None:
        """Perform any handshake needed before the first request (default: none)."""
        return None

    async def async_reauth(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
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
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> None:
        await self._login(session, base_url, ssl)

    async def async_reauth(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> bool:
        await self._login(session, base_url, ssl)
        return True

    async def _login(
        self, session: aiohttp.ClientSession, base_url: str, ssl: bool | aiohttp.Fingerprint
    ) -> None:
        # Network failures — unreachable, reset, timed out, a swapped certificate —
        # are deliberately not caught here. They say nothing about the credentials,
        # and the transport that runs this handshake types them exactly as it types
        # every other request's. Only the console's own answer is an auth verdict.

        # 1) prime CSRF from the console root
        async with session.get(f"{base_url}/", ssl=ssl) as resp:
            self._capture(resp)

        # 2) log in
        payload = {
            "username": self._username,
            "password": self._password,
            "rememberMe": True,
            "remember": True,
        }
        request_headers = {HEADER_CSRF: self._csrf} if self._csrf else {}
        async with session.post(
            f"{base_url}{PATH_LOGIN}",
            json=payload,
            headers=request_headers,
            ssl=ssl,
            # A console that is booting redirects to its web UI; followed, that
            # ends as a 200 page with no token and reads as a refused login.
            allow_redirects=False,
        ) as resp:
            status = resp.status
            if 300 <= status < 400 or status in (408, 429) or status >= 500:
                # No verdict on the credentials: the console redirected, gave up
                # waiting, is rate-limiting, or its proxy answered for an
                # application that is not up yet. Retry later rather than ask
                # for a password.
                raise GwConnectionError(
                    f"login: console answered with status {status}, "
                    "not a verdict on the credentials"
                )
            if status >= 400:
                raise GwAuthError(
                    "invalid credentials"
                    if status in (401, 403)
                    else f"login refused with status {status}"
                )
            self._capture(resp)

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
