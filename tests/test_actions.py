"""Tests for the opt-in write/action client."""

from __future__ import annotations

import json

from _fake import FakeSession
from aiounifigw import ApiKeyAuth, GatewayActionClient

CMD = "https://gw.local/proxy/network/api/s/default/cmd/devmgr"


def _client(session: FakeSession) -> GatewayActionClient:
    return GatewayActionClient(session, "gw.local", ApiKeyAuth("k"), verify_ssl=False)  # type: ignore[arg-type]


async def test_run_speedtest_posts_command() -> None:
    s = FakeSession()
    s.add("POST", CMD, status=200, payload={"meta": {"rc": "ok"}})
    await _client(s).run_speedtest()
    assert s.last_json() == {"cmd": "speedtest"}


async def test_restart_posts_mac() -> None:
    s = FakeSession()
    s.add("POST", CMD, status=200, payload={"meta": {"rc": "ok"}})
    await _client(s).restart_gateway("aa:bb:cc:00:11:22")
    body = s.last_json()
    assert body["cmd"] == "restart"
    assert body["mac"] == "aa:bb:cc:00:11:22"
    json.dumps(body)  # must be JSON-serializable
