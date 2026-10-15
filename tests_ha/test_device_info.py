"""The feature check behind `link_to_hub` agrees with Home Assistant itself."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from custom_components.unifi_gateway_rest.const import DOMAIN
from custom_components.unifi_gateway_rest.entity import _ACCEPTS_VIA_DEVICE_ID, link_to_hub
from homeassistant.helpers.device_registry import DeviceInfo, DeviceRegistry


def test_flag_matches_what_the_registry_accepts() -> None:
    """The registry's own signature is the oracle for which spelling is current."""
    registry_takes_it = (
        "via_device_id" in inspect.signature(DeviceRegistry.async_get_or_create).parameters
    )
    assert _ACCEPTS_VIA_DEVICE_ID is registry_takes_it


def test_link_to_hub_uses_the_spelling_the_flag_names() -> None:
    coordinator = MagicMock()
    coordinator.hub_device_id = "hub-registry-id"
    coordinator.config_entry.entry_id = "entry"
    info = link_to_hub(DeviceInfo(identifiers={(DOMAIN, "child")}), coordinator)
    if _ACCEPTS_VIA_DEVICE_ID:
        assert info["via_device_id"] == "hub-registry-id"
        assert "via_device" not in info
    else:
        assert info["via_device"] == (DOMAIN, "entry")
