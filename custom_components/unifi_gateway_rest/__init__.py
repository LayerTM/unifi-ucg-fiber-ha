"""The UniFi Gateway (non-invasive) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .aiounifigw import (
    ApiKeyAuth,
    GatewayActionClient,
    GatewayClient,
    GwApiError,
    GwAuthError,
    GwCertificateMismatch,
    GwConnectionError,
    SessionAuth,
    TlsMode,
    probe,
)
from .aiounifigw.auth import AbstractAuth
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_SITE,
    CONTROL_PLATFORMS,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SITE,
    DOMAIN,
    ISSUE_TLS_INSECURE,
    PLATFORMS,
    WITHDRAWN_UNIQUE_ID_SUFFIXES,
)
from .coordinator import GatewayDataUpdateCoordinator
from .entity import hub_device_info
from .issues import clear_cert_mismatch, raise_cert_mismatch
from .tls import ssl_for_entry, tls_mode_of

_LOGGER = logging.getLogger(__name__)


@dataclass
class GatewayRuntimeData:
    """Per-entry runtime state."""

    coordinator: GatewayDataUpdateCoordinator
    action_client: GatewayActionClient | None


type GatewayConfigEntry = ConfigEntry[GatewayRuntimeData]


def build_auth(data: Mapping[str, Any]) -> AbstractAuth:
    """Construct the auth strategy from stored config-entry data."""
    if data.get(CONF_API_KEY):
        return ApiKeyAuth(data[CONF_API_KEY])
    return SessionAuth(data[CONF_USERNAME], data[CONF_PASSWORD])


async def async_setup_entry(hass: HomeAssistant, entry: GatewayConfigEntry) -> bool:
    """Set up UniFi Gateway from a config entry."""
    data = entry.data
    port = data.get(CONF_PORT, DEFAULT_PORT)
    site = data.get(CONF_SITE, DEFAULT_SITE)
    ssl = ssl_for_entry(data)
    # The trust is decided per request, so the shared verifying session is the
    # right one to take even when a self-signed certificate is being pinned.
    session = async_get_clientsession(hass)
    client = GatewayClient(
        session,
        data[CONF_HOST],
        build_auth(data),
        site=site,
        port=port,
        use_ssl=True,
        ssl=ssl,
    )

    try:
        await client.async_prepare()
        capabilities = await probe(client)
    except GwCertificateMismatch as err:
        # NOT ConfigEntryAuthFailed: the credentials are fine and asking for them
        # again would teach the user to retype a password at exactly the moment
        # something may be impersonating their gateway. Raise a repair instead,
        # which shows both fingerprints and lets them accept the new one.
        raise_cert_mismatch(hass, entry, err)
        raise ConfigEntryNotReady(str(err)) from err
    except GwAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (GwConnectionError, GwApiError) as err:
        # A console that is still booting, or a reverse proxy answering 502/503,
        # is transient: retry rather than leaving the entry permanently failed.
        raise ConfigEntryNotReady(str(err)) from err

    _async_review_tls(hass, entry)

    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = GatewayDataUpdateCoordinator(hass, entry, client, capabilities, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    action_client: GatewayActionClient | None = None
    if entry.options.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS):
        # Controls need write-capable auth. A local account always is; an API key
        # works only if it was created with write scope (a read-only key returns
        # 401/403, surfaced as a clear action error at press time).
        action_client = GatewayActionClient(
            session,
            data[CONF_HOST],
            build_auth(data),
            site=site,
            port=port,
            use_ssl=True,
            ssl=ssl,
        )

    _async_prune_control_entities(hass, entry, keep=action_client is not None)
    _async_prune_withdrawn_entities(hass, entry)

    entry.runtime_data = GatewayRuntimeData(coordinator, action_client)
    # Register the hub before the platforms load: a sub-device can only be linked
    # to it by device-registry id, which does not exist until the hub does.
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator)
    )
    coordinator.hub_device_id = hub.id
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GatewayConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: GatewayConfigEntry, device: DeviceEntry
) -> bool:
    """Allow deleting a WAN / SFP sub-device that no longer exists.

    The hub device and any sub-device still present in the latest poll are kept;
    a stale one (a removed WAN uplink or SFP module) can be deleted by the user.
    """
    gw = entry.runtime_data.coordinator.data.device
    prefix = f"{entry.entry_id}_"
    known = {entry.entry_id}
    known |= {f"{prefix}{wan.id.lower()}" for wan in gw.wans}
    known |= {f"{prefix}sfp{port.port_idx}" for port in gw.sfp_ports}
    return not any(ident in known for domain, ident in device.identifiers if domain == DOMAIN)


async def _async_reload(hass: HomeAssistant, entry: GatewayConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_prune_control_entities(
    hass: HomeAssistant, entry: GatewayConfigEntry, *, keep: bool
) -> None:
    """Remove the control entities of this entry when controls are switched off.

    The button platform declines to create them, which is enough for an entry
    that never had controls. It is not enough for one that did: the registry
    entry survives the platform that stopped providing it, so the button stays
    on the device page and in every dashboard that references it, permanently
    unavailable and unpressable. Turning controls off should leave no trace of
    them, which is what this does — and turning controls back on recreates the
    entities with the same unique ids, so nothing is lost that the user would
    notice.
    """
    # Measured rather than assumed: Home Assistant keeps a removed registry entry
    # in its deleted-entities store and restores the entity id when the same
    # unique id is registered again, so removing and recreating on every reload
    # would not lose a user's rename. The guard is here because deleting what is
    # about to be recreated is churn and registry noise, not because the data
    # would be lost.
    if keep:
        return
    registry = er.async_get(hass)
    for existing in er.async_entries_for_config_entry(registry, entry.entry_id):
        if existing.domain in CONTROL_PLATFORMS:
            registry.async_remove(existing.entity_id)


def _async_prune_withdrawn_entities(hass: HomeAssistant, entry: GatewayConfigEntry) -> None:
    """Remove entities this integration no longer creates.

    A platform that stops describing an entity does not remove it: the registry
    entry survives, so it stays on the device page and in every dashboard that
    references it, permanently unavailable. The suffixes live in
    ``WITHDRAWN_UNIQUE_ID_SUFFIXES`` so withdrawing the next one is a single
    line there rather than another cleanup written here.
    """
    registry = er.async_get(hass)
    for existing in er.async_entries_for_config_entry(registry, entry.entry_id):
        if existing.unique_id.endswith(WITHDRAWN_UNIQUE_ID_SUFFIXES):
            registry.async_remove(existing.entity_id)


def _async_review_tls(hass: HomeAssistant, entry: GatewayConfigEntry) -> None:
    """Clear a resolved mismatch, and flag an entry that verifies nothing.

    The insecure issue exists because entries created before pinning keep working
    unchanged on upgrade, which is deliberate — silently pinning whatever the
    gateway served during an upgrade would record a certificate nobody looked at.
    The user is asked once, here, and can dismiss it.
    """
    clear_cert_mismatch(hass, entry)
    issue_id = f"{ISSUE_TLS_INSECURE}_{entry.entry_id}"
    if tls_mode_of(entry.data) is not TlsMode.INSECURE:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_TLS_INSECURE,
        translation_placeholders={"host": entry.data[CONF_HOST]},
        data={"entry_id": entry.entry_id},
    )
