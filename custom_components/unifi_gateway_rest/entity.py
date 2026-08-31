"""Base entities for the UniFi Gateway integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aiounifigw import SfpPort, Wan
from .const import DEFAULT_PORT, DOMAIN, MANUFACTURER
from .coordinator import GatewayDataUpdateCoordinator


def add_new_entities(
    async_add_entities: AddConfigEntryEntitiesCallback,
    seen: set[str],
    keys: Callable[[], Iterable[str]],
    make: Callable[[str], list[Entity]],
) -> Callable[[], None]:
    """Build a sync function that adds entities for keys not yet seen.

    Call the returned function once immediately and register it via
    ``coordinator.async_add_listener`` so WANs / SFP ports / temperatures that
    appear at runtime get their entities without a reload (the ``dynamic-devices``
    rule).
    """

    def _sync() -> None:
        fresh: list[Entity] = []
        for key in keys():
            if key not in seen:
                seen.add(key)
                fresh.extend(make(key))
        if fresh:
            async_add_entities(fresh)

    return _sync


class GatewayEntity(CoordinatorEntity[GatewayDataUpdateCoordinator]):
    """Base entity attached to the gateway/console hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        data = coordinator.data
        sysinfo = data.sysinfo
        host = entry.data[CONF_HOST]
        port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        config_url = f"https://{host}" if port == DEFAULT_PORT else f"https://{host}:{port}"
        connections: set[tuple[str, str]] = set()
        if entry.unique_id:
            connections = {(CONNECTION_NETWORK_MAC, format_mac(entry.unique_id))}
        name = (sysinfo.name if sysinfo else "") or data.device.name or "UniFi Gateway"
        sw_version = (sysinfo.console_version if sysinfo else "") or data.device.firmware_version
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            connections=connections,
            manufacturer=MANUFACTURER,
            name=name,
            model=data.device.model or None,
            sw_version=sw_version or None,
            configuration_url=config_url,
        )


class GatewayWanEntity(CoordinatorEntity[GatewayDataUpdateCoordinator]):
    """Base entity attached to a per-WAN sub-device (grouped under the hub)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayDataUpdateCoordinator, wan_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._wan_id = wan_id
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_{wan_id.lower()}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{wan_id.lower()}")},
            # `via_device` left the DeviceInfo TypedDict in 2026.8 in favour of
            # `via_device_id`, which needs a device-registry id we do not have here.
            # It stays functional until its removal in 2027.8, and it is the only
            # form that also works on the 2025.3 floor this integration supports.
            via_device=(DOMAIN, entry.entry_id),  # type: ignore[typeddict-unknown-key]
            manufacturer=MANUFACTURER,
            model="WAN uplink",
            name=wan_id,
        )

    @property
    def wan(self) -> Wan | None:
        """Return the current model for this WAN, if present."""
        return next((w for w in self.coordinator.data.device.wans if w.id == self._wan_id), None)

    @property
    def available(self) -> bool:
        return super().available and self.wan is not None


class GatewaySfpEntity(CoordinatorEntity[GatewayDataUpdateCoordinator]):
    """Base entity attached to a per-SFP-port sub-device (grouped under the hub)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayDataUpdateCoordinator, port_idx: int, key: str) -> None:
        super().__init__(coordinator)
        self._port_idx = port_idx
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_sfp{port_idx}_{key}"
        port = self.port
        has_module = bool(port and port.present)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_sfp{port_idx}")},
            # `via_device` left the DeviceInfo TypedDict in 2026.8 in favour of
            # `via_device_id`, which needs a device-registry id we do not have here.
            # It stays functional until its removal in 2027.8, and it is the only
            # form that also works on the 2025.3 floor this integration supports.
            via_device=(DOMAIN, entry.entry_id),  # type: ignore[typeddict-unknown-key]
            manufacturer=port.vendor if has_module and port and port.vendor else MANUFACTURER,
            model=(port.part if has_module and port and port.part else "SFP+ port"),
            name=f"SFP Port {port_idx}",
        )

    @property
    def port(self) -> SfpPort | None:
        """Return the current model for this SFP port, if present."""
        return next(
            (p for p in self.coordinator.data.device.sfp_ports if p.port_idx == self._port_idx),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.port is not None
