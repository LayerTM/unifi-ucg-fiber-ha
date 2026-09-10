"""Data update coordinator for the UniFi Gateway integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiounifigw import (
    Capabilities,
    Device,
    GatewayClient,
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwCertificateMismatch,
    GwConnectionError,
    Health,
    SysInfo,
)
from .const import DOMAIN
from .issues import clear_cert_mismatch, raise_cert_mismatch

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GwData:
    """Snapshot of everything the coordinator fetches each cycle."""

    device: Device
    health: Health | None
    sysinfo: SysInfo | None


class GatewayDataUpdateCoordinator(DataUpdateCoordinator[GwData]):
    """Polls the UniFi Network REST API and exposes typed models."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GatewayClient,
        capabilities: Capabilities,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.capabilities = capabilities
        self.hub_device_id: str | None = None
        """Device-registry id of the hub, set by `async_setup_entry` before the
        platforms load. Sub-devices point at it (see `entity.link_to_hub`)."""

    async def _optional[T](self, call: Callable[[], Awaitable[T]]) -> T | None:
        """Run a supplementary fetch, degrading to None on a scope/API error.

        A capability denial or API error on health/sysinfo degrades that field to
        None rather than failing the whole update (the core device telemetry stays
        available). Auth (401) and connection errors still propagate so re-auth /
        retry fire.
        """
        try:
            return await call()
        except (GwCapabilityError, GwApiError):
            return None

    async def _async_update_data(self) -> GwData:
        try:
            device = await self.client.get_device()
            health, sysinfo = await asyncio.gather(
                self._optional(self.client.get_health) if self.capabilities.health else _none(),
                self._optional(self.client.get_sysinfo) if self.capabilities.sysinfo else _none(),
            )
        except GwAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GwCertificateMismatch as err:
            # Must precede GwConnectionError, its base class. A certificate that
            # changes while the integration is running is the same event as one
            # that changes before setup, and it has to reach the user the same
            # way: as a repair naming both fingerprints. Left to the branch
            # below it becomes an ordinary UpdateFailed, and the entities simply
            # go unavailable with the reason buried in the log.
            if self.config_entry is not None:
                raise_cert_mismatch(self.hass, self.config_entry, err)
            raise UpdateFailed(str(err)) from err
        except (GwConnectionError, GwApiError) as err:
            raise UpdateFailed(str(err)) from err
        # Symmetric with raising it above. Without this the repair outlives the
        # condition: the gateway recovers, the entities come back, and a scary
        # notification stays on a healthy system — offering to pin a certificate
        # that is no longer served.
        if self.config_entry is not None:
            clear_cert_mismatch(self.hass, self.config_entry)
        return GwData(device=device, health=health, sysinfo=sysinfo)


async def _none() -> None:
    """Awaitable that resolves to None (for disabled optional fetches)."""
    return None
