"""Entities read from the v2 site dashboard: per-WAN link quality and threat detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import Capabilities, Dashboard
from custom_components.unifi_gateway_rest.const import DOMAIN
from custom_components.unifi_gateway_rest.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "network_11"
    / "aggregated_dashboard.json"
)
WITH_DASHBOARD = Capabilities(device=True, health=True, sysinfo=True, dashboard=True)
WITHOUT_DASHBOARD = Capabilities(device=True, health=True, sysinfo=True)


def _dashboard() -> Dashboard:
    return Dashboard.from_api(json.loads(_FIXTURE.read_text(encoding="utf-8")))


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, client: AsyncMock, caps: Capabilities
) -> None:
    client.get_dashboard = AsyncMock(return_value=_dashboard())
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
