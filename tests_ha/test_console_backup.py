"""The console's own auto-backup schedule, read from the full /api/system payload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.unifi_gateway_rest import coordinator as coordinator_module
from custom_components.unifi_gateway_rest.aiounifigw import Capabilities, SystemIdentity
from custom_components.unifi_gateway_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "network_11"
WITH_BACKUP = Capabilities(device=True, health=True, sysinfo=True, console_backup=True)
WITHOUT_BACKUP = Capabilities(device=True, health=True, sysinfo=True)


def _identity(name: str) -> SystemIdentity:
    return SystemIdentity.from_api(json.loads((_FX / name).read_text(encoding="utf-8")))


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


def _state(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> Any:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.unique_id}_{key}")
    if entity_id is None:
        return None
    return hass.states.get(entity_id).state


async def test_console_backup_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(coordinator_module.time, "monotonic", lambda: clock[0])
    mock_client.get_identity = AsyncMock(return_value=_identity("api_system_session.json"))
    await _setup(hass, config_entry, mock_client, WITH_BACKUP)

    assert _state(hass, config_entry, "binary_sensor", "console_auto_backup") == "on"
    assert _state(hass, config_entry, "sensor", "console_backup_frequency") == "weekly"
    assert mock_client.get_identity.await_count == 1

    coordinator = config_entry.runtime_data.coordinator
    clock[0] += coordinator_module.BACKUP_REFRESH_S - 1
    await coordinator.async_refresh()
    assert mock_client.get_identity.await_count == 1  # a setting: not re-read every poll

    clock[0] += 1
    mock_client.get_identity = AsyncMock(side_effect=coordinator_module.GwApiError("busy"))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    # a failed read keeps the last schedule
    assert _state(hass, config_entry, "sensor", "console_backup_frequency") == "weekly"
    assert mock_client.get_identity.await_count == 1


async def test_no_console_backup_entities_without_the_schedule(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, WITHOUT_BACKUP)
    assert _state(hass, config_entry, "binary_sensor", "console_auto_backup") is None
    assert _state(hass, config_entry, "sensor", "console_backup_frequency") is None
    mock_client.get_identity.assert_not_called()
