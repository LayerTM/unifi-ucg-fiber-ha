"""HTTP transport over the UniFi OS / Network local REST API.

Maps HTTP status codes to the typed exception hierarchy and retries once through
the auth strategy on 401. Reads use :meth:`get_json`; writes use :meth:`send`.
The read client (``GatewayClient``) only ever calls ``get_json`` — that is its
no-write guarantee; state-changing calls live in ``GatewayActionClient``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .auth import AbstractAuth
from .const import DEFAULT_PORT, DEFAULT_TIMEOUT, DEFAULT_VERIFY_SSL
from .exceptions import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwConnectionError,
)


class GatewayTransport:
    """Issue authenticated requests and map failures to typed errors."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        auth: AbstractAuth,
        *,
        port: int = DEFAULT_PORT,
        use_ssl: bool = True,
        verify_ssl: bool = DEFAULT_VERIFY_SSL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._auth = auth
        self._timeout = timeout
        self._ssl = verify_ssl
        scheme = "https" if use_ssl else "http"
        default_port = 443 if use_ssl else 80
        netloc = host if port == default_port else f"{host}:{port}"
        self._base_url = f"{scheme}://{netloc}"
        self._prepared = False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def async_prepare(self) -> None:
        """Run the auth handshake once (idempotent)."""
        if not self._prepared:
            await self._auth.async_prepare(self._session, self._base_url, ssl=self._ssl)
            self._prepared = True

    async def get_json(self, path: str, *, allow_reauth: bool = True) -> Any:
        """GET *path* and return parsed JSON, or raise a typed error."""
        return await self._call("GET", path, expect_json=True, allow_reauth=allow_reauth)

    async def send(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        allow_reauth: bool = True,
    ) -> Any:
        """Issue a write (POST/PUT/DELETE). Returns parsed JSON if present, else None."""
        return await self._call(
            method, path, json_body=json_body, expect_json=False, allow_reauth=allow_reauth
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        expect_json: bool = True,
        allow_reauth: bool = True,
    ) -> Any:
        await self.async_prepare()
        status, data = await self._request(
            method, path, json_body=json_body, expect_json=expect_json
        )

        if (
            status == 401
            and allow_reauth
            and self._auth.can_reauth
            and await self._auth.async_reauth(self._session, self._base_url, ssl=self._ssl)
        ):
            status, data = await self._request(
                method, path, json_body=json_body, expect_json=expect_json
            )

        if status == 401:
            raise GwAuthError(f"unauthorized for {path}")
        if status == 403:
            raise GwCapabilityError(f"forbidden for {path}")
        if not (200 <= status < 300):
            raise GwApiError(f"unexpected status {status} for {path}", status=status)
        return data

    async def _request(
        self, method: str, path: str, *, json_body: Any = None, expect_json: bool = True
    ) -> tuple[int, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json", **self._auth.headers()}
        try:
            async with (
                asyncio.timeout(self._timeout),
                self._session.request(
                    method, url, headers=headers, json=json_body, ssl=self._ssl
                ) as resp,
            ):
                status = resp.status
                if 200 <= status < 300:
                    if expect_json:
                        try:
                            return status, await resp.json()
                        except aiohttp.ContentTypeError:
                            # A 2xx with a non-JSON body is the UniFi OS SPA/login
                            # shell served after a silent session expiry. Surface a
                            # clean auth error and DO NOT chain the source exception:
                            # its request_info carries the session cookie / API key.
                            raise GwAuthError(
                                "non-JSON response; session may have expired"
                            ) from None
                    # writes: an empty 2xx body is a bodyless success and a JSON
                    # body is returned as-is; any other non-empty 2xx body is the
                    # SPA/login shell served after a silent session expiry — surface
                    # it as an auth error, never a false success (mirrors the read
                    # path's no-silent-failure guarantee).
                    raw = await resp.read()
                    if not raw:
                        return status, None
                    try:
                        return status, json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise GwAuthError("non-JSON response; session may have expired") from None
                await resp.read()
                return status, None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GwConnectionError(str(err)) from err
