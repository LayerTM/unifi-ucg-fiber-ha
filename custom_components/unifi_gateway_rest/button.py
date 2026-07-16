"""Button platform (opt-in control actions) for the UniFi Gateway integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .aiounifigw import GatewayActionClient
from .aiounifigw.exceptions import GwError
from .coordinator import GatewayDataUpdateCoordinator
from .entity import GatewayEntity
from .errors import action_error

PARALLEL_UPDATES = 1  # serialize write actions


@dataclass(frozen=True, kw_only=True)
class GatewayButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[GatewayActionClient, GatewayDataUpdateCoordinator], Awaitable[None]]


BUTTONS: tuple[GatewayButtonDescription, ...] = (
    GatewayButtonDescription(
        key="run_speedtest",
        translation_key="run_speedtest",
        press_fn=lambda client, _coord: client.run_speedtest(),
    ),
    GatewayButtonDescription(
        key="restart",
        translation_key="restart",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda client, coord: client.restart_gateway(coord.data.device.mac),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up control buttons only when the user has opted in to controls."""
    runtime = entry.runtime_data
    if runtime.action_client is None:
        return
    async_add_entities(
        GatewayButton(runtime.coordinator, runtime.action_client, description)
        for description in BUTTONS
    )


class GatewayButton(GatewayEntity, ButtonEntity):
    entity_description: GatewayButtonDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        action_client: GatewayActionClient,
        description: GatewayButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._action_client = action_client

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self._action_client, self.coordinator)
        except GwError as err:
            raise action_error(err) from err
