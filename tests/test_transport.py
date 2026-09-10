"""Tests for the HTTP transport: status mapping, reauth, non-JSON handling."""

from __future__ import annotations

import aiohttp
import pytest

from _fake import FakeSession
from aiounifigw.auth import AbstractAuth, ApiKeyAuth
from aiounifigw.exceptions import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwConnectionError,
)
from aiounifigw.transport import GatewayTransport

URL = "https://gw.local/x"


class StubAuth(AbstractAuth):
    """Auth stub that can flag reauth support and count reauth calls."""

    def __init__(self, *, reauth: bool = False) -> None:
        self.can_reauth = reauth
        self.reauth_calls = 0

    def headers(self) -> dict[str, str]:
        return {"X-Test": "1"}

    async def async_reauth(self, session, base_url, *, ssl=True) -> bool:  # type: ignore[no-untyped-def]
        self.reauth_calls += 1
        return True


def _transport(session: FakeSession, auth: AbstractAuth) -> GatewayTransport:
    return GatewayTransport(session, "gw.local", auth, ssl=False)  # type: ignore[arg-type]


async def test_get_json_ok() -> None:
    s = FakeSession()
    s.add("GET", URL, payload={"ok": True})
    assert await _transport(s, ApiKeyAuth("k")).get_json("/x") == {"ok": True}


async def test_base_url_omits_default_port() -> None:
    s = FakeSession()
    assert _transport(s, ApiKeyAuth("k")).base_url == "https://gw.local"
    t = GatewayTransport(s, "gw.local", ApiKeyAuth("k"), port=8443)  # type: ignore[arg-type]
    assert t.base_url == "https://gw.local:8443"


async def test_401_raises_auth() -> None:
    s = FakeSession()
    s.add("GET", URL, status=401)
    with pytest.raises(GwAuthError):
        await _transport(s, ApiKeyAuth("k")).get_json("/x")


async def test_403_raises_capability() -> None:
    s = FakeSession()
    s.add("GET", URL, status=403)
    with pytest.raises(GwCapabilityError):
        await _transport(s, ApiKeyAuth("k")).get_json("/x")


async def test_500_raises_api_error_with_status() -> None:
    s = FakeSession()
    s.add("GET", URL, status=500)
    with pytest.raises(GwApiError) as exc:
        await _transport(s, ApiKeyAuth("k")).get_json("/x")
    assert exc.value.status == 500


async def test_non_json_2xx_is_api_error_not_auth() -> None:
    """The console serving its SPA is unavailability, not a rejected credential.

    Classifying it as auth makes HA raise ConfigEntryAuthFailed, which is terminal:
    one such response during a firmware update permanently detaches the entry even
    though the credential is still valid.
    """
    s = FakeSession()
    s.add("GET", URL, status=200, body="<html>login</html>", content_type="text/html")
    with pytest.raises(GwApiError):
        await _transport(s, ApiKeyAuth("k")).get_json("/x")


async def test_non_json_2xx_reauths_once_when_supported() -> None:
    """A session-based auth still gets its one re-login: the body may be a login shell."""
    auth = StubAuth(reauth=True)
    s = FakeSession()
    s.add("GET", URL, status=200, body="<html>login</html>", content_type="text/html")
    s.add("GET", URL, payload={"ok": True})
    assert await _transport(s, auth).get_json("/x") == {"ok": True}
    assert auth.reauth_calls == 1


async def test_non_json_2xx_after_reauth_is_api_error() -> None:
    auth = StubAuth(reauth=True)
    s = FakeSession()
    s.add("GET", URL, status=200, body="<html>login</html>", content_type="text/html")
    s.add("GET", URL, status=200, body="<html>login</html>", content_type="text/html")
    with pytest.raises(GwApiError):
        await _transport(s, auth).get_json("/x")
    assert auth.reauth_calls == 1


async def test_redirects_are_not_followed() -> None:
    """aiohttp follows redirects by default; a redirect to the SPA would then
    arrive as a 200 text/html and be misread as an expired session."""
    s = FakeSession()
    s.add("GET", URL, payload={"ok": True})
    await _transport(s, ApiKeyAuth("k")).get_json("/x")
    assert s.requests[-1][2].get("allow_redirects") is False


async def test_redirect_is_api_error_not_auth() -> None:
    s = FakeSession()
    s.add("GET", URL, status=302, headers={"Location": "https://gw.local/manage"})
    with pytest.raises(GwApiError) as exc:
        await _transport(s, ApiKeyAuth("k")).get_json("/x")
    assert exc.value.status == 302


async def test_connection_error_mapped() -> None:
    s = FakeSession()
    s.add("GET", URL, exc=aiohttp.ClientError("boom"))
    with pytest.raises(GwConnectionError):
        await _transport(s, ApiKeyAuth("k")).get_json("/x")


async def test_reauth_retry_succeeds() -> None:
    auth = StubAuth(reauth=True)
    s = FakeSession()
    s.add("GET", URL, status=401)
    s.add("GET", URL, payload={"ok": True})
    assert await _transport(s, auth).get_json("/x") == {"ok": True}
    assert auth.reauth_calls == 1


async def test_no_reauth_when_unsupported() -> None:
    auth = StubAuth(reauth=False)
    s = FakeSession()
    s.add("GET", URL, status=401)
    with pytest.raises(GwAuthError):
        await _transport(s, auth).get_json("/x")
    assert auth.reauth_calls == 0


async def test_send_empty_2xx_returns_none() -> None:
    s = FakeSession()
    s.add("POST", "https://gw.local/cmd", status=200, body="")
    assert await _transport(s, ApiKeyAuth("k")).send("POST", "/cmd") is None


async def test_send_non_json_2xx_is_api_error_not_auth() -> None:
    s = FakeSession()
    s.add("POST", "https://gw.local/cmd", status=200, body="<html>")
    with pytest.raises(GwApiError):
        await _transport(s, ApiKeyAuth("k")).send("POST", "/cmd")
