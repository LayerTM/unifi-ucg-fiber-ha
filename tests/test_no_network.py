"""A test in this suite cannot reach another machine.

This library talks to real hardware, and the same code that talks to the fakes in
these tests would talk to a console on the network. A test that got there by mistake
would send a made-up key to a real device, which counts failed logins and can lock
the address out, and a test of a write could change a real system. Each test here
fails if the refusal in conftest.py is gone. 192.0.2.1 is TEST-NET-1, never routed.
"""

from __future__ import annotations

import socket

import aiohttp
import pytest
from pytest_socket import SocketConnectBlockedError

# The refusal warns as it raises; here that is the point.
pytestmark = pytest.mark.filterwarnings("ignore:A test:UserWarning")


def test_a_plain_socket_is_refused() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("192.0.2.1", 9), timeout=1)


async def test_the_http_stack_the_library_uses_is_refused() -> None:
    timeout = aiohttp.ClientTimeout(total=2)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        with pytest.raises(SocketConnectBlockedError):
            await session.get("http://192.0.2.1:9/")


def test_loopback_stays_open() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
