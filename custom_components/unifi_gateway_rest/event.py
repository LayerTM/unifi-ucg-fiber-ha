"""Event platform: the gateway's system log as Home Assistant events."""

from __future__ import annotations

import logging

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .aiounifigw.const import SYSTEM_LOG_CATEGORIES
from .coordinator import GatewayDataUpdateCoordinator
from .entity import GatewayEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # read-only; all data comes from the shared coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the gateway event entity when the firmware serves the system log."""
    coordinator = entry.runtime_data.coordinator
    if coordinator.capabilities.system_log:
        async_add_entities([GatewayLogEvent(coordinator)])


class GatewayLogEvent(GatewayEntity, EventEntity):
    """Fires once per new system-log entry; the event type is its category."""

    _attr_translation_key = "gateway_event"

    def __init__(self, coordinator: GatewayDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "gateway_event")
        self._attr_event_types = [c.lower() for c in SYSTEM_LOG_CATEGORIES]

    @callback
    def _handle_coordinator_update(self) -> None:
        fired = False
        for entry in self.coordinator.data.new_log_entries:
            event_type = entry.category.lower()
            if event_type not in self._attr_event_types:
                _LOGGER.debug("system-log entry of an unknown category skipped: %s", entry.category)
                continue
            self._trigger_event(
                event_type,
                {
                    "event": entry.event.lower(),
                    "severity": entry.severity.lower(),
                    "title": entry.title,
                    "message": entry.message,
                    "occurred": entry.occurred.isoformat(),
                },
            )
            # One state write per event: each write is the event Home Assistant
            # records, and a later trigger would overwrite an unwritten one.
            self.async_write_ha_state()
            fired = True
        if not fired:
            super()._handle_coordinator_update()
