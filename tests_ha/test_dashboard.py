"""Entities read from the v2 site dashboard: per-WAN link quality and threat detection."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.unifi_gateway_rest.aiounifigw import Capabilities, GwApiError, GwAuthError
from custom_components.unifi_gateway_rest.const import DOMAIN
from custom_components.unifi_gateway_rest.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

WITH_DASHBOARD = Capabilities(device=True, health=True, sysinfo=True, dashboard=True)
WITHOUT_DASHBOARD = Capabilities(device=True, health=True, sysinfo=True)


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


def _entity(hass: HomeAssistant, platform: str, unique: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique)


async def test_dashboard_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, WITH_DASHBOARD)
    uid = config_entry.unique_id

    def state(platform: str, key: str) -> Any:
        entity_id = _entity(hass, platform, f"{uid}_{key}")
        assert entity_id is not None, f"missing {platform} {key}"
        return hass.states.get(entity_id).state

    assert state("sensor", "wan_packet_loss") == "1.5"
    assert state("sensor", "wan2_packet_loss") == "0.0"
    assert state("sensor", "ips_threats") == "2"
    assert state("binary_sensor", "ips_rules_missing") == "off"

    peak = er.async_get(hass).async_get(_entity(hass, "sensor", f"{uid}_wan_latency_max") or "")
    assert peak is not None
    assert peak.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_no_dashboard_entities_on_firmware_without_it(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, WITHOUT_DASHBOARD)
    uid = config_entry.unique_id
    for platform, key in (
        ("sensor", "wan_packet_loss"),
        ("sensor", "wan_latency_max"),
        ("sensor", "ips_threats"),
        ("binary_sensor", "ips_rules_missing"),
    ):
        assert _entity(hass, platform, f"{uid}_{key}") is None, key
    mock_client.get_dashboard.assert_not_called()


async def test_diagnostics_carry_the_dashboard(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, WITH_DASHBOARD)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["capabilities"]["dashboard"] is True
    assert diag["dashboard"]["wan_quality"]["WAN"]["packet_loss_pct"] == 1.5
    assert diag["dashboard"]["threat_detection"]["threats"] == 2


@pytest.mark.parametrize(
    "error",
    [
        GwApiError("bad request", status=400),
        GwAuthError("unauthorized"),
        GwApiError("server error", status=500),
    ],
    ids=["400", "401", "500"],
)
async def test_a_failing_dashboard_never_stops_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock, error: Exception
) -> None:
    """The real probe runs; only the optional dashboard fails."""
    mock_client.get_dashboard = AsyncMock(side_effect=error)
    config_entry.add_to_hass(hass)
    with patch("custom_components.unifi_gateway_rest.GatewayClient", lambda *a, **k: mock_client):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    uid = config_entry.unique_id
    cpu = _entity(hass, "sensor", f"{uid}_cpu")
    assert cpu is not None
    assert hass.states.get(cpu).state == "20.0"
    assert _entity(hass, "sensor", f"{uid}_wan_packet_loss") is None
    assert _entity(hass, "binary_sensor", f"{uid}_ips_rules_missing") is None
    assert not hass.config_entries.flow.async_progress()
