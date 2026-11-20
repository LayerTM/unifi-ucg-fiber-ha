"""Tests for endpoint capability probing."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from _fake import FakeSession
from aiounifigw import ApiKeyAuth, GatewayClient, GwConnectionError, probe

BASE = "https://gw.local/proxy/network/api/s/default"
SYSTEM = "https://gw.local/api/system"
SYSTEM_LOG = "https://gw.local/proxy/network/v2/api/site/default/system-log/all"
DASHBOARD = (
    "https://gw.local/proxy/network/v2/api/site/default/aggregated-dashboard"
    "?historySeconds=3600&widgets=wan_activity,cybersecure"
)


def _client(session: FakeSession) -> GatewayClient:
    return GatewayClient(session, "gw.local", ApiKeyAuth("k"), ssl=False)  # type: ignore[arg-type]


async def test_probe_all_reachable(
    stat_device: dict[str, Any], stat_health: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", payload=stat_health)
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    s.add("GET", DASHBOARD, payload={"wan_activity": {}, "cybersecure": {}})
    s.add("POST", SYSTEM_LOG, payload={"data": []})
    s.add("GET", SYSTEM, payload={"mac": "aa:bb:cc:00:11:22", "backupSchedule": {}})
    caps = await probe(_client(s))
    assert caps.device and caps.health and caps.sysinfo and caps.dashboard and caps.system_log
    assert caps.console_backup


async def test_probe_marks_forbidden_endpoint(
    stat_device: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", status=403)  # scope denial
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    s.add("GET", DASHBOARD, status=403)
    s.add("POST", SYSTEM_LOG, status=404)
    s.add("GET", SYSTEM, payload={"mac": "aa:bb:cc:00:11:22"})  # an API key's short payload
    caps = await probe(_client(s))
    assert caps.device is True
    assert caps.health is False
    assert caps.sysinfo is True
    assert caps.dashboard is False
    assert caps.system_log is False
    assert caps.console_backup is False


async def _probe_with_dashboard_status(
    status: int,
    stat_device: dict[str, Any],
    stat_health: dict[str, Any],
    stat_sysinfo: dict[str, Any],
) -> bool:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", payload=stat_health)
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    s.add("GET", DASHBOARD, status=status)
    s.add("POST", SYSTEM_LOG, status=status)
    s.add("GET", SYSTEM, status=status)
    caps = await probe(_client(s))
    assert caps.system_log is caps.dashboard
    assert caps.console_backup is caps.dashboard
    return caps.dashboard


async def test_firmware_without_the_dashboard_has_no_dashboard(
    stat_device: dict[str, Any], stat_health: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    """A 404 means the firmware has no such endpoint: the feature is absent."""
    assert await _probe_with_dashboard_status(404, stat_device, stat_health, stat_sysinfo) is False


@pytest.mark.parametrize("status", [400, 401, 403, 500, 502])
async def test_an_optional_endpoint_never_fails_the_probe(
    status: int,
    stat_device: dict[str, Any],
    stat_health: dict[str, Any],
    stat_sysinfo: dict[str, Any],
) -> None:
    """A rejected query, a credential not allowed it, or a server error: not offered."""
    assert (
        await _probe_with_dashboard_status(status, stat_device, stat_health, stat_sysinfo) is False
    )


async def test_an_unreachable_console_still_propagates(
    stat_device: dict[str, Any], stat_health: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", payload=stat_health)
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    s.add("GET", DASHBOARD, exc=aiohttp.ClientConnectionError("gone"))
    s.add("POST", SYSTEM_LOG, payload={"data": []})
    with pytest.raises(GwConnectionError):
        await probe(_client(s))
