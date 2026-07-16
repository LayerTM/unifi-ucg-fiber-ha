"""Setup / unload and entity creation for the UniFi Gateway integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import Capabilities
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

CAPS = Capabilities(device=True, health=True, sysinfo=True)


def _patch(client: AsyncMock) -> Any:
    return patch.multiple(
        "custom_components.unifi_gateway_rest",
        GatewayClient=lambda *a, **k: client,
        probe=AsyncMock(return_value=CAPS),
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, client: AsyncMock) -> None:
    entry.add_to_hass(hass)
    with _patch(client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_hub_and_subdevice_sensor_states(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    registry = er.async_get(hass)
    uid = config_entry.unique_id

    def state_of(key: str) -> str | None:
        entity_id = registry.async_get_entity_id("sensor", "unifi_gateway_rest", f"{uid}_{key}")
        assert entity_id is not None, f"missing sensor {key}"
        state = hass.states.get(entity_id)
        return state.state if state else None

    assert state_of("cpu") == "20.9"
    assert state_of("memory") == "74.8"
    assert state_of("clients") == "51"
    assert state_of("isp") == "Example ISP"
    assert state_of("active_wan") == "WAN"
    # per-WAN sub-device sensor
    assert state_of("wan_availability") == "100.0"


async def test_binary_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    registry = er.async_get(hass)
    uid = config_entry.unique_id

    internet_id = registry.async_get_entity_id(
        "binary_sensor", "unifi_gateway_rest", f"{uid}_internet"
    )
    assert internet_id is not None
    assert hass.states.get(internet_id).state == "on"

    # SFP problem sub-device binary sensor exists for the present module (port 7)
    sfp_problem = registry.async_get_entity_id(
        "binary_sensor", "unifi_gateway_rest", f"{uid}_sfp7_problem"
    )
    assert sfp_problem is not None
    assert hass.states.get(sfp_problem).state == "off"


async def test_no_control_buttons_without_opt_in(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    registry = er.async_get(hass)
    uid = config_entry.unique_id
    assert (
        registry.async_get_entity_id("button", "unifi_gateway_rest", f"{uid}_run_speedtest") is None
    )


async def test_auth_failure_sets_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    from custom_components.unifi_gateway_rest.aiounifigw import GwAuthError

    mock_client.async_prepare = AsyncMock(side_effect=GwAuthError("bad key"))
    config_entry.add_to_hass(hass)
    with _patch(mock_client):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
