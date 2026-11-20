"""The gateway event entity: one Home Assistant event per new system-log entry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import Capabilities, SystemLog
from custom_components.unifi_gateway_rest.const import DOMAIN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "network_11" / "system_log.json"
WITH_LOG = Capabilities(device=True, health=True, sysinfo=True, system_log=True)
WITHOUT_LOG = Capabilities(device=True, health=True, sysinfo=True)


def _page(*indices: int) -> SystemLog:
    """The fixture's entries at *indices* (0 = newest)."""
    payload: dict[str, Any] = json.loads(_FX.read_text(encoding="utf-8"))
    payload["data"] = [payload["data"][i] for i in indices]
    return SystemLog.from_api(payload)


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


async def test_new_entries_fire_events_history_does_not(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.get_system_log_window = AsyncMock(return_value=_page(2))  # existed before setup
    await _setup(hass, config_entry, mock_client, WITH_LOG)
    entity_id = er.async_get(hass).async_get_entity_id(
        "event", DOMAIN, f"{config_entry.unique_id}_gateway_event"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "unknown"  # history is not replayed

    fired: list[dict[str, Any]] = []

    @callback
    def _record(event: Event[Any]) -> None:
        if event.data["entity_id"] == entity_id:
            fired.append(dict(event.data["new_state"].attributes))

    hass.bus.async_listen("state_changed", _record)
    mock_client.get_system_log_window = AsyncMock(return_value=_page(0, 1, 2))
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [(a["event_type"], a["event"], a["severity"]) for a in fired] == [
        ("internet_and_wan", "isp_high_latency", "medium"),
        ("security", "threat_blocked", "high"),
    ]
    assert fired[0]["title"] == "WAN1 High Latency Detected"

    # the next, overlapping poll returns the same entries: nothing fires again
    fired.clear()
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert fired == []


async def test_no_event_entity_without_the_system_log(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client, WITHOUT_LOG)
    assert (
        er.async_get(hass).async_get_entity_id(
            "event", DOMAIN, f"{config_entry.unique_id}_gateway_event"
        )
        is None
    )
    mock_client.get_system_log_window.assert_not_called()
