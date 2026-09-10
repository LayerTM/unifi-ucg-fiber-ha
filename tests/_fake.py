"""A tiny version-proof fake of the aiohttp session interface used by aiounifigw.

aioresponses lags aiohttp's ``ClientResponse`` signature across releases; this
duck-typed fake mocks exactly the surface the transport/auth use — no external
mocking dependency, works on any aiohttp.
"""

from __future__ import annotations

import json as _json
from typing import Any

import aiohttp
import yarl
from multidict import CIMultiDict


class FakeResponse:
    """Async-context-manager response with the fields the transport reads."""

    def __init__(
        self,
        url: str,
        *,
        status: int = 200,
        payload: Any = None,
        body: str | bytes | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._url = url
        self.status = status
        self._payload = payload
        self._body = body
        self._content_type = content_type
        self.headers = CIMultiDict(headers or {})
        self._exc = exc

    async def __aenter__(self) -> FakeResponse:
        if self._exc is not None:
            raise self._exc
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> Any:
        if self._content_type != "application/json":
            info = aiohttp.RequestInfo(
                yarl.URL(self._url), "GET", CIMultiDict(), yarl.URL(self._url)
            )
            raise aiohttp.ContentTypeError(info, (), message=self._content_type)
        return self._payload

    async def read(self) -> bytes:
        if self._body is not None:
            return self._body.encode() if isinstance(self._body, str) else self._body
        if self._payload is not None:
            return _json.dumps(self._payload).encode()
        return b""


class FakeSession:
    """Duck-typed aiohttp.ClientSession: register routes, capture requests."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], list[FakeResponse]] = {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def add(self, method: str, url: str, **kwargs: Any) -> None:
        self._routes.setdefault((method.upper(), url), []).append(FakeResponse(url, **kwargs))

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method.upper(), url, kwargs))
        queue = self._routes.get((method.upper(), url))
        if not queue:
            raise AssertionError(f"no fake route for {method} {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)

    def last_json(self) -> Any:
        return self.requests[-1][2].get("json")


class TlsServer:
    """Where a running self-signed TLS server is listening, and what it serves."""

    def __init__(self, port: int, fingerprint: str) -> None:
        self.port = port
        self.fingerprint = fingerprint
