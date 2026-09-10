"""Write / action client for the UniFi Network local REST API.

Constructing a :class:`GatewayActionClient` is a deliberate opt-in to
state-changing operations — it is intentionally separate from the read-only
:class:`GatewayClient` so read paths keep their no-write guarantee.

Actions go through the ``devmgr`` command channel
(``POST /proxy/network/api/s/<site>/cmd/devmgr``) using the well-established
UniFi controller command payloads. They require a write-capable auth (a local
account, or a write-scoped API key); a read-only key returns 401/403.
"""

from __future__ import annotations

import aiohttp

from .auth import AbstractAuth
from .const import (
    DEFAULT_PORT,
    DEFAULT_SITE,
    DEFAULT_TIMEOUT,
    PATH_CMD_DEVMGR,
)
from .transport import GatewayTransport


class GatewayActionClient:
    """Opt-in client for state-changing UniFi gateway operations."""

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

    async def async_prepare(self) -> None:
        await self._transport.async_prepare()

    async def _devmgr(self, body: dict[str, object]) -> None:
        await self._transport.send("POST", PATH_CMD_DEVMGR.format(site=self._site), json_body=body)

    async def run_speedtest(self) -> None:
        """Trigger an ISP speedtest on the active WAN."""
        await self._devmgr({"cmd": "speedtest"})

    async def restart_gateway(self, mac: str) -> None:
        """Soft-reboot the gateway/console identified by *mac*."""
        await self._devmgr({"cmd": "restart", "mac": mac, "reboot_type": "soft"})
