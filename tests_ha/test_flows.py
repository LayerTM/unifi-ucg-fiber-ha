"""Reauth, reconfigure and options flows."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import Capabilities
from custom_components.unifi_gateway_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    CONF_SITE,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

CAPS = Capabilities(device=True, health=True, sysinfo=True)
CONNECTION = {CONF_HOST: "192.0.2.10", CONF_PORT: 443, CONF_SITE: "default", CONF_VERIFY_SSL: False}


@contextmanager
def _patched(client: AsyncMock, action_client: AsyncMock | None = None) -> Iterator[None]:
    extra = {"GatewayActionClient": lambda *a, **k: action_client} if action_client else {}
    with (
        patch.multiple(
            "custom_components.unifi_gateway_rest",
            GatewayClient=lambda *a, **k: client,
            probe=AsyncMock(return_value=CAPS),
            **extra,
        ),
        patch(
            "custom_components.unifi_gateway_rest.config_flow.GatewayClient",
            return_value=client,
        ),
    ):
        yield


async def test_reauth_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    config_entry.add_to_hass(hass)
    with _patched(mock_client):
        result = await config_entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "new-key"


async def test_reauth_wrong_device_aborts(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock, gateway_models: dict
) -> None:
    from custom_components.unifi_gateway_rest.aiounifigw import SystemIdentity

    config_entry.add_to_hass(hass)
    other = SystemIdentity.from_api({"mac": "aa:bb:cc:99:99:99", "name": "Other"})
    mock_client.get_identity = AsyncMock(return_value=other)
    with _patched(mock_client):
        result = await config_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "k"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"


async def test_reconfigure_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    config_entry.add_to_hass(hass)
    with _patched(mock_client):
        result = await config_entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_HOST: "192.0.2.55", CONF_AUTH_METHOD: AUTH_API_KEY},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "192.0.2.55"


async def test_options_enable_controls_adds_buttons(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    config_entry.add_to_hass(hass)
    action_client = AsyncMock()
    with _patched(mock_client, action_client):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENABLE_CONTROLS: True}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "button", "unifi_gateway_rest", f"{config_entry.unique_id}_run_speedtest"
        )
        is not None
    )
