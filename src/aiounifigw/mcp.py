"""Read-only MCP server for aiounifigw.

Install with ``pip install "aiounifigw[mcp]"`` and run ``unifi-gateway-mcp``.
Exposes gateway/WAN/internet status as a read tool for LLMs and agents; no write
tools are registered (the server is read-only by design). Credentials come from
the same environment variables as the CLI (``UNIFI_GW_HOST`` +
``UNIFI_GW_APIKEY``, or ``UNIFI_GW_USER`` / ``UNIFI_GW_PASS``).
"""

from __future__ import annotations

from typing import Any

import aiohttp
from mcp.server.fastmcp import FastMCP

from .summary import make_client, read_all, status_payload

server = FastMCP("unifi-gateway")


@server.tool()
async def gateway_status() -> dict[str, Any]:
    """Return a UniFi gateway / WAN / ISP / internet status summary (read-only)."""
    async with aiohttp.ClientSession() as session:
        device, health, sysinfo = await read_all(make_client(session))
        return status_payload(device, health, sysinfo)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
