"""Tests for the authentication strategies."""

from __future__ import annotations

import aiohttp
import pytest

from _fake import FakeSession
from aiounifigw.auth import ApiKeyAuth, SessionAuth
from aiounifigw.exceptions import GwAuthError

BASE = "https://gw.local"


def test_api_key_headers() -> None:
    auth = ApiKeyAuth("secret-key")
    assert auth.headers() == {"X-API-Key": "secret-key"}
    assert auth.can_reauth is False


async def test_session_login_captures_csrf_and_token() -> None:
    auth = SessionAuth("admin", "pw")
    s = FakeSession()
    s.add("GET", f"{BASE}/", status=200)
    s.add(
        "POST",
        f"{BASE}/api/auth/login",
        status=200,
        headers={"X-CSRF-Token": "csrf1", "Set-Cookie": "TOKEN=jwt123; Path=/; HttpOnly"},
    )
    await auth.async_prepare(s, BASE, ssl=False)  # type: ignore[arg-type]
    headers = auth.headers()
    assert headers["X-CSRF-Token"] == "csrf1"
    assert headers["Cookie"] == "TOKEN=jwt123"
    assert auth.can_reauth is True


async def test_session_invalid_credentials() -> None:
    auth = SessionAuth("admin", "bad")
    s = FakeSession()
    s.add("GET", f"{BASE}/", status=200)
    s.add("POST", f"{BASE}/api/auth/login", status=401)
    with pytest.raises(GwAuthError):
        await auth.async_prepare(s, BASE, ssl=False)  # type: ignore[arg-type]


async def test_session_missing_token_raises() -> None:
    auth = SessionAuth("admin", "pw")
    s = FakeSession()
    s.add("GET", f"{BASE}/", status=200)
    s.add("POST", f"{BASE}/api/auth/login", status=200)  # no Set-Cookie
    with pytest.raises(GwAuthError):
        await auth.async_prepare(s, BASE, ssl=False)  # type: ignore[arg-type]


async def test_session_unreachable_console() -> None:
    auth = SessionAuth("admin", "pw")
    s = FakeSession()
    s.add("GET", f"{BASE}/", exc=aiohttp.ClientError("down"))
    with pytest.raises(GwAuthError):
        await auth.async_prepare(s, BASE, ssl=False)  # type: ignore[arg-type]


async def test_session_reauth_relogins() -> None:
    auth = SessionAuth("admin", "pw")
    s = FakeSession()
    s.add("GET", f"{BASE}/", status=200)
    s.add(
        "POST",
        f"{BASE}/api/auth/login",
        status=200,
        headers={"Set-Cookie": "TOKEN=jwt123; Path=/"},
    )
    assert await auth.async_reauth(s, BASE, ssl=False) is True  # type: ignore[arg-type]
    assert auth.headers()["Cookie"] == "TOKEN=jwt123"
