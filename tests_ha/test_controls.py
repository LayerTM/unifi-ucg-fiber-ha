"""Opt-in control (button) tests + diagnostics redaction."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import Capabilities
from custom_components.unifi_gateway_rest.const import CONF_ENABLE_CONTROLS
from custom_components.unifi_gateway_rest.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

CAPS = Capabilities(device=True, health=True, sysinfo=True)


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    client: AsyncMock,
    action_client: AsyncMock | None = None,
    options: dict[str, Any] | None = None,
) -> None:
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    patches: dict[str, Any] = {
        "GatewayClient": lambda *a, **k: client,
        "probe": AsyncMock(return_value=CAPS),
    }
    if action_client is not None:
        patches["GatewayActionClient"] = lambda *a, **k: action_client
    with patch.multiple("custom_components.unifi_gateway_rest", **patches):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_buttons_present_when_controls_enabled(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    action_client = AsyncMock()
    await _setup(hass, config_entry, mock_client, action_client, {CONF_ENABLE_CONTROLS: True})

    registry = er.async_get(hass)
    uid = config_entry.unique_id
    speedtest_id = registry.async_get_entity_id(
        "button", "unifi_gateway_rest", f"{uid}_run_speedtest"
    )
    assert speedtest_id is not None

    await hass.services.async_call("button", "press", {"entity_id": speedtest_id}, blocking=True)
    action_client.run_speedtest.assert_awaited_once()


async def test_restart_button_passes_mac(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    action_client = AsyncMock()
    await _setup(hass, config_entry, mock_client, action_client, {CONF_ENABLE_CONTROLS: True})

    registry = er.async_get(hass)
    restart_id = registry.async_get_entity_id(
        "button", "unifi_gateway_rest", f"{config_entry.unique_id}_restart"
    )
    await hass.services.async_call("button", "press", {"entity_id": restart_id}, blocking=True)
    action_client.restart_gateway.assert_awaited_once_with("aa:bb:cc:00:11:22")


async def test_diagnostics_redacts_pii(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    blob = json.dumps(diag)

    # secrets and PII must not leak
    assert "test-key" not in blob
    assert "aa:bb:cc:00:11:22" not in blob  # gateway MAC redacted
    assert "203.0.113.10" not in blob  # WAN IP redacted
    # non-PII telemetry is retained
    assert diag["device"]["model"] == "UDMA6A8"
    assert diag["capabilities"]["device"] is True
