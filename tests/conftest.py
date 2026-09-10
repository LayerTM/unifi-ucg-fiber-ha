"""Shared fixtures for the aiounifigw test-suite."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import ssl
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from _fake import TlsServer
from aiounifigw.tls import format_fingerprint

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def stat_device() -> dict[str, Any]:
    return _load("stat_device.json")


@pytest.fixture
def stat_health() -> dict[str, Any]:
    return _load("stat_health.json")


@pytest.fixture
def stat_sysinfo() -> dict[str, Any]:
    return _load("stat_sysinfo.json")


@pytest.fixture
def api_system() -> dict[str, Any]:
    return _load("api_system.json")


# --- a real TLS server, for the tests that refuse to mock the handshake --------


def _self_signed(tmp_path: Path, common_name: str = "localhost") -> tuple[str, str, str]:
    """Write a self-signed cert/key pair; return (cert_path, key_path, sha256)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{common_name}.pem"
    key_path = tmp_path / f"{common_name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()
    return str(cert_path), str(key_path), format_fingerprint(digest)


@pytest.fixture
async def tls_server(tmp_path: Path) -> AsyncIterator[TlsServer]:
    """A minimal HTTPS server presenting a freshly generated self-signed cert."""
    cert_path, key_path, fingerprint = _self_signed(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b'Content-Length: 15\r\n\r\n{"data": [{}]}\n'
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    async with server:
        await server.start_serving()
        yield TlsServer(port, fingerprint)
