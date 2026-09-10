"""TLS trust for a local UniFi OS gateway.

A UniFi OS console serves a self-signed certificate, so ordinary CA verification
cannot succeed against one. The historical answer was to switch verification off
entirely, which also switches off any assurance that the host answering is the
gateway — a plain machine-in-the-middle opening.

This module offers the middle ground and makes it the default: **trust on first
use**. The certificate is read once while the integration is being set up, its
SHA-256 fingerprint is recorded, and every later connection is accepted only if
it presents that exact certificate. A console with a real certificate can still
be verified against the CA store instead.

``aiohttp.Fingerprint`` does the enforcing. Two properties of it matter and both
were read from the installed aiohttp rather than assumed:

- passing a ``Fingerprint`` as the per-request ``ssl`` argument makes aiohttp use
  its *unverified* SSL context (``TCPConnector._get_ssl_context``), which is what
  lets a self-signed certificate be pinned at all;
- the check runs in ``TCPConnector._create_direct_connection`` immediately after
  the TLS handshake and **before the request is written**, closing the transport
  on mismatch. Credentials therefore never reach an impostor.

Trust on first use is not equivalent to a certificate signed by a real authority:
it assumes the first contact was not already intercepted. That is exactly why the
fingerprint is shown for the user to compare against the console's own UI instead
of being adopted silently.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import ssl
from enum import StrEnum
from typing import Final

import aiohttp

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
from .exceptions import GwConnectionError

FINGERPRINT_BYTES: Final = 32  # SHA-256; aiohttp rejects md5/sha1 outright

_HEX_SEPARATORS: Final = re.compile(r"[\s:-]")


class TlsMode(StrEnum):
    """How the gateway's certificate is trusted."""

    CA = "ca"
    """Verify against the system CA store. Needs a real certificate."""

    FINGERPRINT = "fingerprint"
    """Accept only the one certificate recorded at setup (trust on first use)."""

    INSECURE = "insecure"
    """Accept any certificate. No assurance the peer is the gateway."""


# One unverified context for the whole library, built at import time: creating an
# SSLContext touches the filesystem, and a library must not do that from inside a
# running event loop. PROTOCOL_TLS_CLIENT defaults to verifying, so both switches
# are turned off explicitly — the fingerprint is what provides the assurance here.
_UNVERIFIED_CONTEXT: Final = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_UNVERIFIED_CONTEXT.check_hostname = False
_UNVERIFIED_CONTEXT.verify_mode = ssl.CERT_NONE


class GwCertificateMismatch(GwConnectionError):
    """The gateway presented a certificate other than the pinned one.

    Subclasses :class:`GwConnectionError` deliberately: to a caller that does not
    care about TLS this is simply "could not talk to the gateway", and Home
    Assistant will retry rather than tear the entry down. Callers that do care
    read :attr:`expected` and :attr:`got` and offer the user the new fingerprint.
    """

    def __init__(self, expected: str, got: str) -> None:
        super().__init__(
            f"certificate fingerprint changed: expected {expected}, got {got}. "
            "Either the gateway's certificate was reissued, or something is "
            "impersonating it."
        )
        self.expected = expected
        self.got = got


def format_fingerprint(digest: bytes) -> str:
    """Render a digest as the canonical lowercase colon-separated hex form."""
    return ":".join(f"{b:02x}" for b in digest)


def parse_fingerprint(value: str) -> bytes:
    """Parse a user- or storage-supplied SHA-256 fingerprint into raw bytes.

    Accepts the shapes people actually paste: colon-, space- or dash-separated,
    upper or lower case, or an unbroken hex string.

    Raises:
        ValueError: if it is not 32 bytes of hex.
    """
    cleaned = _HEX_SEPARATORS.sub("", value.strip())
    try:
        digest = bytes.fromhex(cleaned)
    except ValueError as err:
        raise ValueError(f"not a hex fingerprint: {value!r}") from err
    if len(digest) != FINGERPRINT_BYTES:
        raise ValueError(f"a SHA-256 fingerprint is {FINGERPRINT_BYTES} bytes, got {len(digest)}")
    return digest


def ssl_param(
    mode: TlsMode | str = TlsMode.FINGERPRINT, fingerprint: str | None = None
) -> bool | aiohttp.Fingerprint:
    """Build the value to pass as aiohttp's per-request ``ssl`` argument.

    Args:
        mode: how to trust the certificate.
        fingerprint: the pinned SHA-256, required when *mode* is FINGERPRINT.

    Raises:
        ValueError: when FINGERPRINT is asked for without a usable fingerprint.
            Never falls back to an unverified connection — a pinning mode that
            quietly stops pinning is worse than one that refuses to start.
    """
    if mode == TlsMode.CA:
        return True
    if mode == TlsMode.INSECURE:
        return False
    if not fingerprint:
        raise ValueError("TlsMode.FINGERPRINT requires a fingerprint")
    return aiohttp.Fingerprint(parse_fingerprint(fingerprint))


async def async_probe_fingerprint(
    host: str,
    port: int = DEFAULT_PORT,
    *,
    timeout: int = DEFAULT_TIMEOUT,  # noqa: ASYNC109 - caller-facing budget, applied via asyncio.timeout below
) -> str:
    """Read the certificate a host is currently serving and return its SHA-256.

    This is the "first use" half of trust on first use, and it is the only place
    the library talks TLS without checking anything: nothing is trusted as a
    result of it, the fingerprint is merely shown to the user to accept.
    """
    writer: asyncio.StreamWriter | None = None
    try:
        async with asyncio.timeout(timeout):
            _reader, writer = await asyncio.open_connection(
                host, port, ssl=_UNVERIFIED_CONTEXT, server_hostname=host
            )
            sslobj = writer.get_extra_info("ssl_object")
            if sslobj is None:  # pragma: no cover - only if the peer speaks no TLS
                raise GwConnectionError(f"{host}:{port} did not negotiate TLS")
            cert = sslobj.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError, TimeoutError) as err:
        raise GwConnectionError(f"could not read the certificate of {host}:{port}: {err}") from err
    finally:
        if writer is not None:
            writer.close()
            # The peer may already be gone; the fingerprint is read by then, so a
            # failure to shut down cleanly must not lose it.
            with contextlib.suppress(OSError, ssl.SSLError):
                await writer.wait_closed()
    return format_fingerprint(hashlib.sha256(cert).digest())


def mismatch_from(err: aiohttp.ServerFingerprintMismatch) -> GwCertificateMismatch:
    """Convert aiohttp's mismatch into the library's typed error.

    Worth doing at every call site that catches ``aiohttp.ClientError``, because
    ``ServerFingerprintMismatch`` *is* one: left unclassified in the session-auth
    path it surfaces as "invalid credentials", which Home Assistant treats as
    terminal and answers by asking the user to retype a password that was never
    wrong.
    """
    return GwCertificateMismatch(format_fingerprint(err.expected), format_fingerprint(err.got))
