"""Tests for the high-level GatewayClient against a fake session."""

from __future__ import annotations

from typing import Any

import pytest

from _fake import FakeSession
from aiounifigw import ApiKeyAuth, GatewayClient
from aiounifigw.exceptions import GwApiError

BASE = "https://gw.local"


def _client(session: FakeSession, site: str = "default") -> GatewayClient:
    return GatewayClient(session, "gw.local", ApiKeyAuth("k"), site=site, verify_ssl=False)  # type: ignore[arg-type]


async def test_get_device(stat_device: dict[str, Any]) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/default/stat/device", payload=stat_device)
    device = await _client(s).get_device()
    assert device.model == "UDMA6A8"
    assert device.name == "UCG Fiber"
    assert len(device.wans) == 2


async def test_get_device_prefers_gateway_over_switch(stat_device: dict[str, Any]) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/default/stat/device", payload=stat_device)
    device = await _client(s).get_device()
    assert device.type == "udm"


async def test_get_device_fallback_to_wan_holder() -> None:
    payload = {"data": [{"type": "unknownmodel", "wan1": {"up": True}}]}
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/default/stat/device", payload=payload)
    device = await _client(s).get_device()
    assert device.wans[0].up is True


async def test_get_device_no_gateway_raises() -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/default/stat/device", payload={"data": []})
    with pytest.raises(GwApiError):
        await _client(s).get_device()


async def test_get_health(stat_health: dict[str, Any]) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/default/stat/health", payload=stat_health)
    health = await _client(s).get_health()
    assert health.isp.name == "Example ISP"
    assert health.internet_up is True


async def test_get_sysinfo(stat_sysinfo: dict[str, Any]) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/default/stat/sysinfo", payload=stat_sysinfo)
    sysinfo = await _client(s).get_sysinfo()
    assert sysinfo.netapp_version == "10.5.62"


async def test_get_identity(api_system: dict[str, Any]) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/api/system", payload=api_system)
    ident = await _client(s).get_identity()
    assert ident.mac == "aa:bb:cc:00:11:22"
    assert ident.model_shortname == "UCGF"


async def test_custom_site_in_path(stat_device: dict[str, Any]) -> None:
    s = FakeSession()
    s.add("GET", f"{BASE}/proxy/network/api/s/branch/stat/device", payload=stat_device)
    device = await _client(s, site="branch").get_device()
    assert device.model == "UDMA6A8"


async def test_close_is_noop() -> None:
    client = _client(FakeSession())
    await client.close()
    assert client.site == "default"
