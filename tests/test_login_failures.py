"""A session login that fails on the network is a connection failure, not bad credentials.

These run against real local sockets rather than a fake session: the point is what
aiohttp actually raises when a console refuses the connection or never answers,
and a fake would only replay what the test already assumed.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp import web

from aiounifigw import GatewayClient, GwApiError, GwAuthError, GwConnectionError, SessionAuth


def _closed_port() -> int:
    """A local port that was free a moment ago, so a connection to it is refused."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _client(session: aiohttp.ClientSession, port: int, *, timeout: int = 15) -> GatewayClient:
    return GatewayClient(
        session, "127.0.0.1", SessionAuth("u", "p"), port=port, use_ssl=False, timeout=timeout
    )


@pytest.fixture
async def silent_port() -> AsyncIterator[int]:
    """A server that accepts the connection and never answers."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()  # until the client gives up and closes
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


async def _serve(login_status: int) -> tuple[web.AppRunner, int]:
    async def root(_request: web.Request) -> web.Response:
        return web.Response(text="<html></html>", content_type="text/html")

    async def login(_request: web.Request) -> web.Response:
        return web.json_response({}, status=login_status)

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, runner.addresses[0][1]


async def test_refused_connection_during_login_is_a_connection_error() -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(GwConnectionError) as caught:
            await _client(session, _closed_port()).async_prepare()
    assert str(caught.value).startswith("login: ")


async def test_login_that_never_answers_times_out_as_a_connection_error(silent_port: int) -> None:
    # The outer bound is the test's own guard: an unbounded login would otherwise
    # hang the suite for aiohttp's default five minutes instead of failing it.
    async with aiohttp.ClientSession() as session, asyncio.timeout(5):
        with pytest.raises(GwConnectionError) as caught:
            await _client(session, silent_port, timeout=1).async_prepare()
    assert str(caught.value) == "login: TimeoutError"


async def test_refused_credentials_are_still_an_auth_error() -> None:
    runner, port = await _serve(401)
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(GwAuthError, match="invalid credentials"):
                await _client(session, port).async_prepare()
    finally:
        await runner.cleanup()


async def test_a_proxy_error_on_login_is_not_an_auth_error() -> None:
    """A 502 from the console's proxy while it boots says nothing about the password."""
    runner, port = await _serve(502)
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(GwApiError) as caught:
                await _client(session, port).async_prepare()
    finally:
        await runner.cleanup()
    assert not isinstance(caught.value, GwAuthError)
    assert caught.value.status == 502
