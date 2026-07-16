"""Coordinator degraded-path and stale-device removal tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest import async_remove_config_entry_device
from custom_components.unifi_gateway_rest.aiounifigw import Capabilities, GwApiError
from custom_components.unifi_gateway_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, client: AsyncMock, caps: Capabilities
) -> None:
    entry.add_to_hass(hass)
    with patch.multiple(
        "custom_components.unifi_gateway_rest",
        GatewayClient=lambda *a, **k: client,
        probe=AsyncMock(return_value=caps),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_health_capability_off_yields_none(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, Capabilities(True, False, True))
    coordinator = config_entry.runtime_data.coordinator
    assert coordinator.data.health is None
    mock_client.get_health.assert_not_awaited()


async def test_health_api_error_is_swallowed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.get_health = AsyncMock(side_effect=GwApiError("transient", status=500))
    await _setup(hass, config_entry, mock_client, Capabilities(True, True, True))
    coordinator = config_entry.runtime_data.coordinator
    # a transient API error on the supplementary fetch degrades to None, not failure
    assert coordinator.data.health is None
    assert coordinator.last_update_success is True


async def test_stale_subdevice_is_removable(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, Capabilities(True, True, True))
    entry = config_entry

    def device(ident: str) -> Any:
        return SimpleNamespace(identifiers={(DOMAIN, ident)})

    # the hub and live sub-devices must be kept
    assert await async_remove_config_entry_device(hass, entry, device(entry.entry_id)) is False
    assert (
        await async_remove_config_entry_device(hass, entry, device(f"{entry.entry_id}_wan"))
        is False
    )
    assert (
        await async_remove_config_entry_device(hass, entry, device(f"{entry.entry_id}_sfp7"))
        is False
    )
    # a WAN/SFP that no longer exists may be removed
    assert (
        await async_remove_config_entry_device(hass, entry, device(f"{entry.entry_id}_wan9"))
        is True
    )
