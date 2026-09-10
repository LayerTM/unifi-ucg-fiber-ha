"""High-level UniFi gateway client: endpoint methods returning typed models."""

from __future__ import annotations

from typing import Any

import aiohttp

from .auth import AbstractAuth
from .const import (
    DEFAULT_PORT,
    DEFAULT_SITE,
    DEFAULT_TIMEOUT,
    GATEWAY_TYPES,
    PATH_STAT_DEVICE,
    PATH_STAT_HEALTH,
    PATH_STAT_SYSINFO,
    PATH_SYSTEM,
)
from .exceptions import GwApiError
from .models import Device, Health, SysInfo, SystemIdentity
from .transport import GatewayTransport


def _find_gateway(devices: list[Any]) -> dict[str, Any] | None:
    """Pick the gateway/console from a /stat/device device list.

    Prefers a device of a known gateway ``type``; falls back to any device that
    reports a ``wan1`` uplink (covers model codes not in the static type set).
    """
    fallback: dict[str, Any] | None = None
    for d in devices:
        if not isinstance(d, dict):
            continue
        if _str(d.get("type")) in GATEWAY_TYPES:
            return d
        if fallback is None and ("wan1" in d or "wan2" in d):
            fallback = d
    return fallback


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


class GatewayClient:
    """Read-only client for the UniFi Network local REST API.

    The caller owns *session*; the client never closes it.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        auth: AbstractAuth,
        *,
        site: str = DEFAULT_SITE,
        port: int = DEFAULT_PORT,
        use_ssl: bool = True,
        ssl: bool | aiohttp.Fingerprint = True,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._site = site
        self._transport = GatewayTransport(
            session,
            host,
            auth,
            port=port,
            use_ssl=use_ssl,
            ssl=ssl,
            timeout=timeout,
        )

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    @property
    def site(self) -> str:
        return self._site

    async def async_prepare(self) -> None:
        """Run the auth handshake once (optional; done lazily otherwise)."""
        await self._transport.async_prepare()

    async def get_identity(self) -> SystemIdentity:
        """Console identity (MAC / name / model) from /api/system."""
        return SystemIdentity.from_api(await self._transport.get_json(PATH_SYSTEM))

    async def get_device(self) -> Device:
        """The gateway device object from /stat/device."""
        payload = await self._transport.get_json(PATH_STAT_DEVICE.format(site=self._site))
        devices = payload.get("data") if isinstance(payload, dict) else payload
        gateway = _find_gateway(devices if isinstance(devices, list) else [])
        if gateway is None:
            raise GwApiError("no gateway device found in /stat/device response")
        return Device.from_api(gateway)

    async def get_health(self) -> Health:
        """Subsystem health (WAN/ISP/www/vpn/lan/wlan) from /stat/health."""
        payload = await self._transport.get_json(PATH_STAT_HEALTH.format(site=self._site))
        data = payload.get("data") if isinstance(payload, dict) else payload
        return Health.from_api(data)

    async def get_sysinfo(self) -> SysInfo:
        """Controller/console info (Network version, updates) from /stat/sysinfo."""
        payload = await self._transport.get_json(PATH_STAT_SYSINFO.format(site=self._site))
        data = payload.get("data") if isinstance(payload, dict) else payload
        return SysInfo.from_api(data)

    async def close(self) -> None:
        """Release client resources.

        A no-op: the ``aiohttp`` session is owned by the caller and is never
        closed here. Present so consumers (CLI/MCP) can call it unconditionally.
        """
