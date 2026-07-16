"""Dependency-light helpers shared by the CLI and MCP server.

No third-party imports beyond aiohttp — so importing this never pulls in the
optional ``cli`` (typer/rich) or ``mcp`` extras.
"""

from __future__ import annotations

import os
from typing import Any

import aiohttp

from .actions import GatewayActionClient
from .auth import AbstractAuth, ApiKeyAuth, SessionAuth
from .client import GatewayClient
from .const import DEFAULT_SITE
from .models import Device, Health, SysInfo


def env_host() -> str:
    host = os.environ.get("UNIFI_GW_HOST")
    if not host:
        raise ValueError("set UNIFI_GW_HOST")
    return host


def env_auth() -> AbstractAuth:
    key = os.environ.get("UNIFI_GW_APIKEY")
    if key:
        return ApiKeyAuth(key)
    user, password = os.environ.get("UNIFI_GW_USER"), os.environ.get("UNIFI_GW_PASS")
    if user and password:
        return SessionAuth(user, password)
    raise ValueError("set UNIFI_GW_APIKEY, or UNIFI_GW_USER + UNIFI_GW_PASS")


def env_site() -> str:
    return os.environ.get("UNIFI_GW_SITE", DEFAULT_SITE)


def env_verify_ssl() -> bool:
    return os.environ.get("UNIFI_GW_VERIFY_SSL", "").lower() in ("1", "true", "yes", "on")


def make_client(session: aiohttp.ClientSession) -> GatewayClient:
    return GatewayClient(
        session, env_host(), env_auth(), site=env_site(), verify_ssl=env_verify_ssl()
    )


def make_action_client(session: aiohttp.ClientSession) -> GatewayActionClient:
    return GatewayActionClient(
        session, env_host(), env_auth(), site=env_site(), verify_ssl=env_verify_ssl()
    )


async def read_all(client: GatewayClient) -> tuple[Device, Health | None, SysInfo | None]:
    """Read device + (best-effort) health + sysinfo."""
    device = await client.get_device()
    health: Health | None
    sysinfo: SysInfo | None
    try:
        health = await client.get_health()
    except Exception:
        health = None
    try:
        sysinfo = await client.get_sysinfo()
    except Exception:
        sysinfo = None
    return device, health, sysinfo


def status_payload(
    device: Device, health: Health | None, sysinfo: SysInfo | None
) -> dict[str, Any]:
    """Assemble a machine-readable gateway/WAN/internet status dict."""
    active = device.active_wan
    return {
        "console": {
            "model": device.model,
            "name": device.name,
            "firmware": device.firmware_version,
            "network_version": sysinfo.netapp_version if sysinfo else None,
            "online": device.online,
            "cpu_percent": device.cpu_percent,
            "memory_percent": device.memory_percent,
            "loadavg": [device.loadavg_1, device.loadavg_5, device.loadavg_15],
            "temperatures": {t.name: t.value for t in device.temperatures},
            "clients": device.num_clients,
            "overheating": device.overheating,
            "update_available": sysinfo.update_available if sysinfo else None,
        },
        "internet": {
            "up": health.internet_up if health else None,
            "isp": health.isp.name if health else None,
            "asn": health.isp.asn_label if health else None,
            "latency_ms": health.internet_latency_ms if health else None,
            "speedtest": {
                "status": health.speedtest.status if health else None,
                "download_mbps": health.speedtest.download_mbps if health else None,
                "upload_mbps": health.speedtest.upload_mbps if health else None,
                "ping_ms": health.speedtest.ping_ms if health else None,
            },
        },
        "active_wan": active.id if active else None,
        "failover_active": device.failover_active,
        "wans": [
            {
                "id": w.id,
                "up": w.up,
                "active": w.is_active,
                "media": w.media,
                "speed_mbps": w.speed,
                "latency_ms": w.latency_ms,
                "availability": w.availability,
            }
            for w in device.wans
        ],
        "sfp_ports": [
            {"port": p.port_idx, "vendor": p.vendor, "part": p.part, "problem": p.has_problem}
            for p in device.sfp_ports
        ],
    }
