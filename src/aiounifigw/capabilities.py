"""Probe which read endpoints the active auth method is allowed to reach."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .client import GatewayClient
from .exceptions import GwCapabilityError


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Reachability of each read endpoint under the current auth."""

    device: bool
    health: bool
    sysinfo: bool


async def _reachable(call: Callable[[], Awaitable[object]]) -> bool:
    """True if *call* succeeds; False only on a capability (scope) denial.

    Connection and auth failures propagate — they are not capability signals.
    """
    try:
        await call()
    except GwCapabilityError:
        return False
    return True


async def probe(client: GatewayClient) -> Capabilities:
    """Determine endpoint reachability for the client's auth method."""
    return Capabilities(
        device=await _reachable(client.get_device),
        health=await _reachable(client.get_health),
        sysinfo=await _reachable(client.get_sysinfo),
    )
