"""Test the read-only MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from aiounifigw import mcp as mcp_module
from aiounifigw.models import Device, Health, SysInfo


async def test_gateway_status_tool(stat_device, stat_health, stat_sysinfo) -> None:  # type: ignore[no-untyped-def]
    gw = next(d for d in stat_device["data"] if d.get("type") == "udm")
    models = (
        Device.from_api(gw),
        Health.from_api(stat_health["data"]),
        SysInfo.from_api(stat_sysinfo["data"]),
    )
    with patch.multiple(
        "aiounifigw.mcp",
        make_client=lambda _session: object(),
        read_all=AsyncMock(return_value=models),
    ):
        result = await mcp_module.gateway_status()
    assert result["console"]["model"] == "UDMA6A8"
    assert result["internet"]["isp"] == "Example ISP"


def test_server_registered() -> None:
    assert mcp_module.server.name == "unifi-gateway"
