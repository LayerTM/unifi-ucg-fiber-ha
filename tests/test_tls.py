"""TLS trust: fingerprint parsing, and pinning against a real handshake.

The pinning tests deliberately do not mock aiohttp. A self-signed certificate is
generated, a TLS server is started with it, and the client is pointed at it —
once with the right fingerprint and once with the wrong one. Mocking the check
would only prove the mock was called; this proves the connection is refused.
"""

from __future__ import annotations

import hashlib

import aiohttp
import pytest

from _fake import TlsServer
from aiounifigw.exceptions import GwConnectionError
from aiounifigw.tls import (
    GwCertificateMismatch,
    TlsMode,
    async_probe_fingerprint,
    format_fingerprint,
    mismatch_from,
    parse_fingerprint,
    ssl_param,
)

_OTHER = "aa:" * 31 + "aa"


# --- fingerprint parsing ------------------------------------------------------


def test_parse_accepts_the_shapes_people_paste() -> None:
    digest = hashlib.sha256(b"cert").digest()
    canonical = format_fingerprint(digest)
    assert parse_fingerprint(canonical) == digest
    assert parse_fingerprint(canonical.upper()) == digest
    assert parse_fingerprint(canonical.replace(":", "")) == digest
    assert parse_fingerprint(canonical.replace(":", "-")) == digest
    assert parse_fingerprint(f"  {canonical}  ") == digest


@pytest.mark.parametrize("value", ["", "zz", "ab:cd", "ab" * 33])
def test_parse_rejects_anything_that_is_not_a_sha256(value: str) -> None:
    with pytest.raises(ValueError):
        parse_fingerprint(value)


def test_ssl_param_per_mode() -> None:
    assert ssl_param(TlsMode.CA) is True
    assert ssl_param(TlsMode.INSECURE) is False
    assert isinstance(ssl_param(TlsMode.FINGERPRINT, _OTHER), aiohttp.Fingerprint)


def test_ssl_param_refuses_to_pin_nothing() -> None:
    """A pinning mode without a pin must fail, never fall back to unverified."""
    with pytest.raises(ValueError):
        ssl_param(TlsMode.FINGERPRINT, None)


def test_mismatch_from_carries_both_fingerprints() -> None:
    expected, got = hashlib.sha256(b"a").digest(), hashlib.sha256(b"b").digest()
    err = mismatch_from(aiohttp.ServerFingerprintMismatch(expected, got, "h", 443))
    assert err.expected == format_fingerprint(expected)
    assert err.got == format_fingerprint(got)
    assert isinstance(err, GwCertificateMismatch)


# --- against a real handshake -------------------------------------------------


async def test_probe_reads_the_served_certificate(tls_server: TlsServer) -> None:
    assert await async_probe_fingerprint("127.0.0.1", tls_server.port) == tls_server.fingerprint


async def test_probe_reports_an_unreachable_host() -> None:
    with pytest.raises(GwConnectionError):
        await async_probe_fingerprint("127.0.0.1", 1, timeout=2)


async def test_matching_fingerprint_connects(tls_server: TlsServer) -> None:
    """The branch that must succeed: the pinned certificate is the served one."""
    async with (
        aiohttp.ClientSession() as session,
        session.get(
            f"https://127.0.0.1:{tls_server.port}/",
            ssl=ssl_param(TlsMode.FINGERPRINT, tls_server.fingerprint),
        ) as resp,
    ):
        assert resp.status == 200


async def test_mismatched_fingerprint_is_refused(tls_server: TlsServer) -> None:
    """The branch that must fail, and fail as a mismatch rather than a timeout."""
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ServerFingerprintMismatch) as caught:
            await session.get(
                f"https://127.0.0.1:{tls_server.port}/",
                ssl=ssl_param(TlsMode.FINGERPRINT, _OTHER),
            )
    assert format_fingerprint(caught.value.got) == tls_server.fingerprint


async def test_ca_mode_rejects_a_self_signed_certificate(tls_server: TlsServer) -> None:
    """CA mode is a real setting, not a synonym for the pinning one."""
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientConnectorCertificateError):
            await session.get(f"https://127.0.0.1:{tls_server.port}/", ssl=ssl_param(TlsMode.CA))


async def test_insecure_mode_accepts_it(tls_server: TlsServer) -> None:
    async with (
        aiohttp.ClientSession() as session,
        session.get(
            f"https://127.0.0.1:{tls_server.port}/", ssl=ssl_param(TlsMode.INSECURE)
        ) as resp,
    ):
        assert resp.status == 200


# --- the classification that the auth path used to get wrong -------------------


async def test_client_reports_a_mismatch_as_a_certificate_error(tls_server: TlsServer) -> None:
    """Through the whole client, a swapped certificate stays a certificate error.

    ``ServerFingerprintMismatch`` is an ``aiohttp.ClientError``, so every handler
    that catches one can swallow it. The read path would otherwise turn it into a
    plain connection error, which loses the fingerprints the user needs.
    """
    from aiounifigw import ApiKeyAuth, GatewayClient

    async with aiohttp.ClientSession() as session:
        client = GatewayClient(
            session,
            "127.0.0.1",
            ApiKeyAuth("k"),
            port=tls_server.port,
            ssl=ssl_param(TlsMode.FINGERPRINT, _OTHER),
        )
        with pytest.raises(GwCertificateMismatch) as caught:
            await client.get_identity()
    assert caught.value.got == tls_server.fingerprint
    assert caught.value.expected == _OTHER


async def test_session_login_does_not_call_a_swapped_certificate_bad_credentials(
    tls_server: TlsServer,
) -> None:
    """The expensive misfiling: a mismatch during login is not an auth failure.

    ``SessionAuth._login`` wraps ``aiohttp.ClientError`` into ``GwAuthError``,
    which Home Assistant treats as terminal — it would tear the entry down and
    ask the user to retype a password that was never wrong, at exactly the moment
    something may be impersonating their gateway.
    """
    from aiounifigw import GatewayClient, GwAuthError, SessionAuth

    async with aiohttp.ClientSession() as session:
        client = GatewayClient(
            session,
            "127.0.0.1",
            SessionAuth("u", "p"),
            port=tls_server.port,
            ssl=ssl_param(TlsMode.FINGERPRINT, _OTHER),
        )
        with pytest.raises(GwCertificateMismatch) as caught:
            await client.async_prepare()
    assert not isinstance(caught.value, GwAuthError)
    assert caught.value.got == tls_server.fingerprint


async def test_matching_pin_lets_the_client_through(tls_server: TlsServer) -> None:
    """Same path, right certificate: the pin must not break ordinary use."""
    from aiounifigw import ApiKeyAuth, GatewayClient, SystemIdentity

    async with aiohttp.ClientSession() as session:
        client = GatewayClient(
            session,
            "127.0.0.1",
            ApiKeyAuth("k"),
            port=tls_server.port,
            ssl=ssl_param(TlsMode.FINGERPRINT, tls_server.fingerprint),
        )
        # The stub answers a minimal payload, which the model reads as a device
        # with empty fields. Getting a model back at all is the point: the
        # handshake was accepted and the request was served.
        assert isinstance(await client.get_identity(), SystemIdentity)


async def test_a_certificate_swapped_between_the_two_login_requests() -> None:
    """The second guard in ``_login``, which a single server cannot reach.

    ``_login`` issues two requests: it primes CSRF from the console root, then
    posts the credentials. A mismatch normally stops the first one. This covers
    the case where the certificate changes in between — a reconnect landing on a
    different host behind the same address — because that is precisely the
    request that carries the password.
    """
    from aiounifigw.auth import SessionAuth

    expected, got = hashlib.sha256(b"pinned").digest(), hashlib.sha256(b"impostor").digest()

    class _Headers:
        """Just enough of aiohttp's multidict for ``SessionAuth._capture``."""

        @staticmethod
        def get(_name: str, default: object = None) -> object:
            return default

        @staticmethod
        def getall(_name: str, default: list[str] | None = None) -> list[str]:
            return default or []

    class _OkGet:
        headers = _Headers()

        async def __aenter__(self) -> _OkGet:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class _SwappingSession:
        def get(self, *_a: object, **_k: object) -> _OkGet:
            return _OkGet()

        def post(self, *_a: object, **_k: object) -> object:
            raise aiohttp.ServerFingerprintMismatch(expected, got, "127.0.0.1", 443)

    with pytest.raises(GwCertificateMismatch) as caught:
        await SessionAuth("u", "p")._login(
            _SwappingSession(),  # type: ignore[arg-type]
            "https://127.0.0.1",
            ssl_param(TlsMode.FINGERPRINT, format_fingerprint(expected)),
        )
    assert caught.value.expected == format_fingerprint(expected)
    assert caught.value.got == format_fingerprint(got)
