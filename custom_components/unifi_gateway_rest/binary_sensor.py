"""Binary sensor platform for the UniFi Gateway integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .aiounifigw import SfpPort, Wan
from .coordinator import GatewayDataUpdateCoordinator, GwData
from .entity import GatewayEntity, GatewaySfpEntity, GatewayWanEntity, add_new_entities

PARALLEL_UPDATES = 0  # read-only; all data comes from the shared coordinator


@dataclass(frozen=True, kw_only=True)
class GatewayBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[GwData], bool | None]


@dataclass(frozen=True, kw_only=True)
class GatewayWanBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Wan], bool]


@dataclass(frozen=True, kw_only=True)
class GatewaySfpBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[SfpPort], bool]


BINARY_SENSORS: tuple[GatewayBinaryDescription, ...] = (
    GatewayBinaryDescription(
        key="internet",
        translation_key="internet",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: d.health.internet_up if d.health else None,
    ),
    GatewayBinaryDescription(
        key="overheating",
        translation_key="overheating",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.overheating,
    ),
    GatewayBinaryDescription(
        key="failover",
        translation_key="failover",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: d.device.failover_active,
    ),
    GatewayBinaryDescription(
        key="update_available",
        translation_key="update_available",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,  # official `unifi` owns the update entity
        value_fn=lambda d: d.sysinfo.update_available if d.sysinfo else None,
    ),
    GatewayBinaryDescription(
        key="vpn_site_to_site",
        translation_key="vpn_site_to_site",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.vpn.site_to_site_enabled if d.health else None,
    ),
)

WAN_BINARY_SENSORS: tuple[GatewayWanBinaryDescription, ...] = (
    GatewayWanBinaryDescription(
        key="up",
        translation_key="wan_up",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda w: w.up,
    ),
    GatewayWanBinaryDescription(
        key="active",
        translation_key="wan_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w: w.is_active,
    ),
)

SFP_BINARY_SENSORS: tuple[GatewaySfpBinaryDescription, ...] = (
    GatewaySfpBinaryDescription(
        key="present",
        translation_key="sfp_present",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.present,
    ),
    GatewaySfpBinaryDescription(
        key="problem",
        translation_key="sfp_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda p: p.has_problem,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UniFi Gateway binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    aggregate: list[BinarySensorEntity] = [GatewayConnectivity(coordinator)]
    aggregate.extend(GatewayBinarySensor(coordinator, d) for d in BINARY_SENSORS)
    async_add_entities(aggregate)

    syncers = [
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [w.id for w in coordinator.data.device.wans],
            lambda wan_id: [
                GatewayWanBinarySensor(coordinator, wan_id, d) for d in WAN_BINARY_SENSORS
            ],
        ),
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [str(p.port_idx) for p in coordinator.data.device.sfp_ports],
            lambda idx: [
                GatewaySfpBinarySensor(coordinator, int(idx), d) for d in SFP_BINARY_SENSORS
            ],
        ),
    ]
    for sync in syncers:
        sync()
        entry.async_on_unload(coordinator.async_add_listener(sync))


class GatewayConnectivity(GatewayEntity, BinarySensorEntity):
    """Reports OFF (not unavailable) when polling fails."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "device_online"

    def __init__(self, coordinator: GatewayDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "device_online")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class GatewayBinarySensor(GatewayEntity, BinarySensorEntity):
    entity_description: GatewayBinaryDescription

    def __init__(
        self, coordinator: GatewayDataUpdateCoordinator, description: GatewayBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)


class GatewayWanBinarySensor(GatewayWanEntity, BinarySensorEntity):
    entity_description: GatewayWanBinaryDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        wan_id: str,
        description: GatewayWanBinaryDescription,
    ) -> None:
        super().__init__(coordinator, wan_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        wan = self.wan
        return self.entity_description.value_fn(wan) if wan is not None else None


class GatewaySfpBinarySensor(GatewaySfpEntity, BinarySensorEntity):
    entity_description: GatewaySfpBinaryDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        port_idx: int,
        description: GatewaySfpBinaryDescription,
    ) -> None:
        super().__init__(coordinator, port_idx, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        port = self.port
        return self.entity_description.value_fn(port) if port is not None else None
