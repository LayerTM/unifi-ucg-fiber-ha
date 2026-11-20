"""Sensor platform for the UniFi Gateway integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import GatewayConfigEntry
from .aiounifigw import Wan, WanQuality
from .coordinator import GatewayDataUpdateCoordinator, GwData
from .entity import GatewayEntity, GatewayWanEntity, add_new_entities

PARALLEL_UPDATES = 0  # read-only; all data comes from the shared coordinator


@dataclass(frozen=True, kw_only=True)
class GatewaySensorDescription(SensorEntityDescription):
    """Aggregate/console sensor bound to a GwData accessor."""

    value_fn: Callable[[GwData], StateType | datetime]
    available_fn: Callable[[GwData], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class GatewayWanSensorDescription(SensorEntityDescription):
    """Per-WAN sensor bound to a Wan accessor."""

    value_fn: Callable[[Wan], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class GatewayWanQualitySensorDescription(SensorEntityDescription):
    """Per-WAN sensor bound to the WAN's dashboard link-quality sample."""

    value_fn: Callable[[WanQuality], StateType]


SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.device.cpu_percent,
    ),
    GatewaySensorDescription(
        key="memory",
        translation_key="memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.device.memory_percent,
    ),
    GatewaySensorDescription(
        key="load_1",
        translation_key="load_1",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda d: d.device.loadavg_1,
    ),
    GatewaySensorDescription(
        key="load_5",
        translation_key="load_5",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda d: d.device.loadavg_5,
    ),
    GatewaySensorDescription(
        key="load_15",
        translation_key="load_15",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda d: d.device.loadavg_15,
    ),
    GatewaySensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.uptime_since,
    ),
    GatewaySensorDescription(
        key="storage_usage",
        translation_key="storage_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: (
            d.device.persistent_storage.usage_percent if d.device.persistent_storage else None
        ),
    ),
    GatewaySensorDescription(
        key="clients",
        translation_key="clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.device.num_clients,
    ),
    GatewaySensorDescription(
        key="clients_wired",
        translation_key="clients_wired",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.health.num_wired if d.health else None,
    ),
    GatewaySensorDescription(
        key="clients_wireless",
        translation_key="clients_wireless",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.health.num_wireless if d.health else None,
    ),
    GatewaySensorDescription(
        key="clients_guest",
        translation_key="clients_guest",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.num_guest if d.health else None,
    ),
    GatewaySensorDescription(
        key="clients_iot",
        translation_key="clients_iot",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.num_iot if d.health else None,
    ),
    GatewaySensorDescription(
        key="network_version",
        translation_key="network_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.sysinfo.netapp_version if d.sysinfo else None,
    ),
    GatewaySensorDescription(
        key="isp",
        translation_key="isp",
        value_fn=lambda d: (d.health.isp.name or None) if d.health else None,
    ),
    GatewaySensorDescription(
        key="isp_asn",
        translation_key="isp_asn",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.health.isp.asn_label if d.health else None,
    ),
    GatewaySensorDescription(
        key="internet_latency",
        translation_key="internet_latency",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.health.internet_latency_ms if d.health else None,
    ),
    GatewaySensorDescription(
        key="speedtest_download",
        translation_key="speedtest_download",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.health.speedtest.download_mbps if d.health else None,
    ),
    GatewaySensorDescription(
        key="speedtest_upload",
        translation_key="speedtest_upload",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.health.speedtest.upload_mbps if d.health else None,
    ),
    GatewaySensorDescription(
        key="speedtest_ping",
        translation_key="speedtest_ping",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.health.speedtest.ping_ms if d.health else None,
    ),
    GatewaySensorDescription(
        key="speedtest_last_run",
        translation_key="speedtest_last_run",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.health.speedtest.last_run if d.health else None,
    ),
    GatewaySensorDescription(
        key="speedtest_wan",
        translation_key="speedtest_wan",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.speedtest_wan.id if d.device.speedtest_wan else None,
    ),
    GatewaySensorDescription(
        key="active_wan",
        translation_key="active_wan",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.active_wan.id if d.device.active_wan else None,
    ),
    GatewaySensorDescription(
        key="ips_rules",
        translation_key="ips_rules",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.ips.rule_count if d.device.ips else None,
    ),
    GatewaySensorDescription(
        key="ips_updated",
        translation_key="ips_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.ips.updated if d.device.ips else None,
    ),
    GatewaySensorDescription(
        key="vpn_remote_active",
        translation_key="vpn_remote_active",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.health.vpn.remote_active if d.health else None,
    ),
)


WAN_SENSORS: tuple[GatewayWanSensorDescription, ...] = (
    GatewayWanSensorDescription(
        key="ip",
        translation_key="wan_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda w: w.ip or None,
    ),
    GatewayWanSensorDescription(
        key="latency",
        translation_key="wan_latency",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w: w.latency_ms,
    ),
    GatewayWanSensorDescription(
        key="availability",
        translation_key="wan_availability",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda w: w.availability,
    ),
    GatewayWanSensorDescription(
        key="link_speed",
        translation_key="wan_link_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w: w.speed or None,
    ),
    GatewayWanSensorDescription(
        key="throughput_rx",
        translation_key="wan_throughput_rx",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda w: w.rx_rate_bps,
    ),
    GatewayWanSensorDescription(
        key="throughput_tx",
        translation_key="wan_throughput_tx",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda w: w.tx_rate_bps,
    ),
    GatewayWanSensorDescription(
        key="uptime",
        translation_key="wan_uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda w: w.uptime_since,
    ),
    GatewayWanSensorDescription(
        key="media",
        translation_key="wan_media",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda w: w.media or None,
    ),
    GatewayWanSensorDescription(
        key="total_rx",
        translation_key="wan_total_rx",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda w: w.rx_bytes,
    ),
    GatewayWanSensorDescription(
        key="total_tx",
        translation_key="wan_total_tx",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda w: w.tx_bytes,
    ),
)


# Read from the v2 site dashboard; created only when the firmware serves it.
DASHBOARD_SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="ips_threats",
        translation_key="ips_threats",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (
            d.dashboard.threat_detection.threats
            if d.dashboard and d.dashboard.threat_detection
            else None
        ),
    ),
)

BACKUP_FREQUENCIES = ["daily", "weekly", "monthly"]

# The console's own backup schedule; created only when /api/system reports it.
CONSOLE_BACKUP_SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="console_backup_frequency",
        translation_key="console_backup_frequency",
        device_class=SensorDeviceClass.ENUM,
        options=BACKUP_FREQUENCIES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            d.console_backup.frequency
            if d.console_backup and d.console_backup.frequency in BACKUP_FREQUENCIES
            else None
        ),
        available_fn=lambda d: d.console_backup is not None,
    ),
)

WAN_QUALITY_SENSORS: tuple[GatewayWanQualitySensorDescription, ...] = (
    GatewayWanQualitySensorDescription(
        key="packet_loss",
        translation_key="wan_packet_loss",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda q: q.packet_loss_pct,
    ),
    GatewayWanQualitySensorDescription(
        key="latency_max",
        translation_key="wan_latency_max",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda q: q.latency_max_ms,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UniFi Gateway sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    dashboard = coordinator.capabilities.dashboard
    async_add_entities(
        GatewaySensor(coordinator, d)
        for d in SENSORS
        + (DASHBOARD_SENSORS if dashboard else ())
        + (CONSOLE_BACKUP_SENSORS if coordinator.capabilities.console_backup else ())
    )

    def _wan_sensors(wan_id: str) -> list[Entity]:
        entities: list[Entity] = [GatewayWanSensor(coordinator, wan_id, d) for d in WAN_SENSORS]
        if dashboard:
            entities += [
                GatewayWanQualitySensor(coordinator, wan_id, d) for d in WAN_QUALITY_SENSORS
            ]
        return entities

    syncers = [
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [w.id for w in coordinator.data.device.wans],
            _wan_sensors,
        ),
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [t.name for t in coordinator.data.device.temperatures],
            lambda name: [GatewayTemperatureSensor(coordinator, name)],
        ),
    ]
    for sync in syncers:
        sync()
        entry.async_on_unload(coordinator.async_add_listener(sync))


class GatewaySensor(GatewayEntity, SensorEntity):
    entity_description: GatewaySensorDescription

    def __init__(
        self, coordinator: GatewayDataUpdateCoordinator, description: GatewaySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.coordinator.data)


class GatewayWanSensor(GatewayWanEntity, SensorEntity):
    entity_description: GatewayWanSensorDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        wan_id: str,
        description: GatewayWanSensorDescription,
    ) -> None:
        super().__init__(coordinator, wan_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        wan = self.wan
        return self.entity_description.value_fn(wan) if wan is not None else None


class GatewayWanQualitySensor(GatewayWanEntity, SensorEntity):
    """Per-WAN link quality from the site dashboard."""

    entity_description: GatewayWanQualitySensorDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        wan_id: str,
        description: GatewayWanQualitySensorDescription,
    ) -> None:
        super().__init__(coordinator, wan_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        dashboard = self.coordinator.data.dashboard
        quality = dashboard.wan_quality.get(self._wan_id) if dashboard else None
        return self.entity_description.value_fn(quality) if quality is not None else None


class GatewayTemperatureSensor(GatewayEntity, SensorEntity):
    """A named temperature sensor on the console hub."""

    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GatewayDataUpdateCoordinator, name: str) -> None:
        super().__init__(coordinator, f"temp_{name.lower()}")
        self._temp_name = name
        self._attr_translation_placeholders = {"name": name}

    @property
    def native_value(self) -> float | None:
        return next(
            (
                t.value
                for t in self.coordinator.data.device.temperatures
                if t.name == self._temp_name
            ),
            None,
        )
