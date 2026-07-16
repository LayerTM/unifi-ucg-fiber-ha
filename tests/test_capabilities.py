"""Tests for endpoint capability probing."""

from __future__ import annotations

from typing import Any

from _fake import FakeSession
from aiounifigw import ApiKeyAuth, GatewayClient, probe

BASE = "https://gw.local/proxy/network/api/s/default"


def _client(session: FakeSession) -> GatewayClient:
    return GatewayClient(session, "gw.local", ApiKeyAuth("k"), verify_ssl=False)  # type: ignore[arg-type]


async def test_probe_all_reachable(
    stat_device: dict[str, Any], stat_health: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", payload=stat_health)
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    caps = await probe(_client(s))
    assert caps.device and caps.health and caps.sysinfo


async def test_probe_marks_forbidden_endpoint(
    stat_device: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", status=403)  # scope denial
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    caps = await probe(_client(s))
    assert caps.device is True
    assert caps.health is False
    assert caps.sysinfo is True
