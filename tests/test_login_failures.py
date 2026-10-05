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

from aiounifigw import GatewayClient, GwAuthError, GwConnectionError, SessionAuth


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


async def _serve(
    login_status: int, *, data_status: int = 200, hang_relogin: bool = False
) -> tuple[web.AppRunner, int]:
    """A console: ``/`` primes CSRF, the login answers *login_status*, ``/x`` *data_status*.

    With *hang_relogin*, the first login succeeds and every later one never answers.
    """
    logins = 0

    async def root(_request: web.Request) -> web.Response:
        return web.Response(text="<html></html>", content_type="text/html")

    async def login(_request: web.Request) -> web.Response:
        nonlocal logins
        logins += 1
        if hang_relogin and logins > 1:
            await asyncio.Event().wait()
        headers = {"Location": "/manage"} if 300 <= login_status < 400 else {}
        if login_status == 200:
            headers["Set-Cookie"] = "TOKEN=t; Path=/"
        return web.json_response({}, status=login_status, headers=headers)

    async def data(_request: web.Request) -> web.Response:
        return web.json_response({}, status=data_status)

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/x", data)
    # A handler left hanging must not hold the teardown for aiohttp's default minute.
    runner = web.AppRunner(app, shutdown_timeout=0.1)
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


@pytest.mark.parametrize(("status", "message"), [(401, "invalid credentials"), (400, "400")])
async def test_refused_credentials_are_still_an_auth_error(status: int, message: str) -> None:
    runner, port = await _serve(status)
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(GwAuthError, match=message):
                await _client(session, port).async_prepare()
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("status", [302, 429, 502, 503])
async def test_a_login_answer_without_a_verdict_is_a_connection_error(status: int) -> None:
    """A redirect to the UI, a rate limit, or the proxy answering for a console that
    is still booting says nothing about the password, so it must not ask for one."""
    runner, port = await _serve(status)
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(GwConnectionError, match=f"status {status}") as caught:
                await _client(session, port).async_prepare()
    finally:
        await runner.cleanup()
    assert not isinstance(caught.value, GwAuthError)


async def test_a_relogin_that_never_answers_is_bounded() -> None:
    """The re-login after a 401 runs under the same timeout as the first one."""
    runner, port = await _serve(200, data_status=401, hang_relogin=True)
    try:
        async with aiohttp.ClientSession() as session, asyncio.timeout(5):
            client = _client(session, port, timeout=1)
            await client.async_prepare()
            with pytest.raises(GwConnectionError) as caught:
                await client._transport.get_json("/x")
    finally:
        await runner.cleanup()
    assert str(caught.value) == "login: TimeoutError"
