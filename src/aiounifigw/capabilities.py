"""Probe which read endpoints the active auth method is allowed to reach."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .client import GatewayClient
from .exceptions import GwCapabilityError, GwConnectionError, GwError
from .models import SystemIdentity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Reachability of each read endpoint under the current auth."""

    device: bool
    health: bool
    sysinfo: bool
    dashboard: bool = False  # v2 site dashboard (UniFi Network with the v2 API)
    system_log: bool = False  # v2 system log
    console_backup: bool = False  # console backup schedule in /api/system (session only)


async def _reachable(call: Callable[[], Awaitable[object]]) -> bool:
    """True if *call* succeeds; False only on a capability (scope) denial.

    Connection and auth failures propagate — they are not capability signals.
    """
    try:
        await call()
    except GwCapabilityError:
        return False
    return True


async def _supported(
    call: Callable[[], Awaitable[object]],
    present: Callable[[object], bool] = lambda _: True,
) -> bool:
    """Reachability of an optional endpoint: it never decides whether setup succeeds.

    Any answer from the console other than success — absent on this firmware
    (404), a query it rejects (400), a credential not allowed this endpoint
    (401/403), a server error, or an answer without the data (*present*) — means
    the feature is not offered, and the core
    telemetry loads without it. Only an unreachable console propagates, because
    then the core endpoints cannot be read either.
    """
    try:
        answer = await call()
    except GwConnectionError:
        raise
    except GwError as err:
        _LOGGER.debug("optional endpoint not available, its entities are skipped: %s", err)
        return False
    return present(answer)


async def probe(client: GatewayClient) -> Capabilities:
    """Determine endpoint reachability for the client's auth method."""
    return Capabilities(
        device=await _reachable(client.get_device),
        health=await _reachable(client.get_health),
        sysinfo=await _reachable(client.get_sysinfo),
        dashboard=await _supported(client.get_dashboard),
        system_log=await _supported(_system_log_probe(client)),
        console_backup=await _supported(
            client.get_identity,
            lambda identity: isinstance(identity, SystemIdentity) and identity.backup is not None,
        ),
    )


def _system_log_probe(client: GatewayClient) -> Callable[[], Awaitable[object]]:
    """A one-minute search: enough to learn whether the log answers."""

    async def call() -> object:
        now_ms = int(time.time() * 1000)
        return await client.get_system_log(now_ms - 60_000, now_ms)

    return call
