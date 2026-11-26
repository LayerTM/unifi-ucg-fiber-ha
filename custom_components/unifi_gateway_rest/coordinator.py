"""Data update coordinator for the UniFi Gateway integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiounifigw import (
    Capabilities,
    ConsoleBackup,
    Dashboard,
    Device,
    GatewayClient,
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwCertificateMismatch,
    GwConnectionError,
    Health,
    SysInfo,
    SystemLogCursor,
    SystemLogEntry,
)
from .const import DOMAIN
from .issues import clear_cert_mismatch, raise_cert_mismatch

_LOGGER = logging.getLogger(__name__)

# The console's backup schedule is a setting, and the full /api/system payload
# that carries it is large: it is read every ten minutes, not every poll.
BACKUP_REFRESH_S = 600
# The schedule shown is at most this old: past it, after failed reads, the
# schedule is reported as unknown (its entities unavailable) until a read succeeds.
BACKUP_STALE_S = 3 * BACKUP_REFRESH_S


@dataclass(slots=True)
class GwData:
    """Snapshot of everything the coordinator fetches each cycle."""

    device: Device
    health: Health | None
    sysinfo: SysInfo | None
    dashboard: Dashboard | None = None
    console_backup: ConsoleBackup | None = None
    new_log_entries: tuple[SystemLogEntry, ...] = ()
    """System-log entries first seen in this update, oldest first."""


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
        self._log_cursor = SystemLogCursor()
        self._backup: ConsoleBackup | None = None
        self._backup_read_at: float | None = None
        self.hub_device_id: str | None = None
        """Device-registry id of the hub, set by `async_setup_entry` before the
        platforms load. Sub-devices point at it (see `entity.hub_link`)."""

    async def _optional[T](self, call: Callable[[], Awaitable[T]]) -> T | None:
        """Run a supplementary fetch, degrading to None when the console refuses it.

        Only the core device read decides re-authentication. A supplementary read
        (health, sysinfo, dashboard, system log, console identity) runs after that
        read has succeeded with the same credential, so a 401 here means this one
        endpoint refuses it, not that the credential is wrong: like a scope denial
        or an API error, the field
        degrades to None and the core telemetry stays available. A connection
        error still propagates, so the update is retried.
        """
        try:
            return await call()
        except (GwCapabilityError, GwApiError, GwAuthError) as err:
            _LOGGER.debug("supplementary read unavailable, its entities show unknown: %s", err)
            return None

    async def _async_update_data(self) -> GwData:
        try:
            device = await self.client.get_device()
            caps = self.capabilities
            start_ms, end_ms = self._log_cursor.window(int(time.time() * 1000))
            backup_due = caps.console_backup and (
                self._backup_read_at is None
                or time.monotonic() - self._backup_read_at >= BACKUP_REFRESH_S
            )
            health, sysinfo, dashboard, log, identity = await asyncio.gather(
                self._optional(self.client.get_health) if caps.health else _none(),
                self._optional(self.client.get_sysinfo) if caps.sysinfo else _none(),
                self._optional(self.client.get_dashboard) if caps.dashboard else _none(),
                self._optional(lambda: self.client.get_system_log_window(start_ms, end_ms))
                if caps.system_log
                else _none(),
                self._optional(self.client.get_identity) if backup_due else _none(),
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
        new_entries = self._log_cursor.advance(log) if log is not None else ()
        # A failed read keeps the last schedule for a while; the next poll tries again.
        if backup_due and identity is not None:
            self._backup = identity.backup
            self._backup_read_at = time.monotonic()
        backup_fresh = (
            self._backup_read_at is not None
            and time.monotonic() - self._backup_read_at <= BACKUP_STALE_S
        )
        return GwData(
            device=device,
            health=health,
            sysinfo=sysinfo,
            dashboard=dashboard,
            console_backup=self._backup if backup_fresh else None,
            new_log_entries=new_entries,
        )


async def _none() -> None:
    """Awaitable that resolves to None (for disabled optional fetches)."""
    return None
