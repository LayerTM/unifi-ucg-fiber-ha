"""The feature check behind `hub_link` agrees with Home Assistant itself."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from custom_components.unifi_gateway_rest.const import DOMAIN
from custom_components.unifi_gateway_rest.entity import _ACCEPTS_VIA_DEVICE_ID, hub_link
from homeassistant.helpers.device_registry import DeviceRegistry


def test_flag_matches_what_the_registry_accepts() -> None:
    """The registry's own signature is the oracle for which spelling is current."""
    registry_takes_it = (
        "via_device_id" in inspect.signature(DeviceRegistry.async_get_or_create).parameters
    )
    assert _ACCEPTS_VIA_DEVICE_ID is registry_takes_it


def test_hub_link_uses_the_spelling_the_flag_names() -> None:
    coordinator = MagicMock()
    coordinator.hub_device_id = "hub-registry-id"
    coordinator.config_entry.entry_id = "entry"
    expected = (
        {"via_device_id": "hub-registry-id"}
        if _ACCEPTS_VIA_DEVICE_ID
        else {"via_device": (DOMAIN, "entry")}
    )
    assert hub_link(coordinator) == expected


def test_hub_link_names_the_hub_by_identifiers_until_it_has_an_id() -> None:
    coordinator = MagicMock()
    coordinator.hub_device_id = None
    coordinator.config_entry.entry_id = "entry"
    assert hub_link(coordinator) == {"via_device": (DOMAIN, "entry")}
