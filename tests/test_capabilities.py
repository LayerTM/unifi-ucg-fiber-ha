"""Tests for endpoint capability probing."""

from __future__ import annotations

from typing import Any

import pytest

from _fake import FakeSession
from aiounifigw import ApiKeyAuth, GatewayClient, GwApiError, probe

BASE = "https://gw.local/proxy/network/api/s/default"
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
    caps = await probe(_client(s))
    assert caps.device and caps.health and caps.sysinfo and caps.dashboard


async def test_probe_marks_forbidden_endpoint(
    stat_device: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/stat/device", payload=stat_device)
    s.add("GET", f"{BASE}/stat/health", status=403)  # scope denial
    s.add("GET", f"{BASE}/stat/sysinfo", payload=stat_sysinfo)
    s.add("GET", DASHBOARD, status=403)
    caps = await probe(_client(s))
    assert caps.device is True
    assert caps.health is False
    assert caps.sysinfo is True
    assert caps.dashboard is False


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
    return (await probe(_client(s))).dashboard


async def test_firmware_without_the_dashboard_has_no_dashboard(
    stat_device: dict[str, Any], stat_health: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    """A 404 means the firmware has no such endpoint: the feature is absent."""
    assert await _probe_with_dashboard_status(404, stat_device, stat_health, stat_sysinfo) is False


async def test_dashboard_server_error_is_not_mistaken_for_absence(
    stat_device: dict[str, Any], stat_health: dict[str, Any], stat_sysinfo: dict[str, Any]
) -> None:
    with pytest.raises(GwApiError):
        await _probe_with_dashboard_status(502, stat_device, stat_health, stat_sysinfo)
