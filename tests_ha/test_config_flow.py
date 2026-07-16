"""Config-flow tests for the UniFi Gateway integration."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import GwAuthError, GwConnectionError
from custom_components.unifi_gateway_rest.const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_SITE,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONNECTION = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 443,
    CONF_SITE: "default",
    CONF_VERIFY_SSL: False,
}


def _patch_client(client: AsyncMock) -> ExitStack:
    """Patch the flow's client and stub async_setup_entry (the entry-creation
    steps otherwise trigger a real setup with a live client)."""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "custom_components.unifi_gateway_rest.config_flow.GatewayClient",
            return_value=client,
        )
    )
    stack.enter_context(
        patch(
            "custom_components.unifi_gateway_rest.async_setup_entry", AsyncMock(return_value=True)
        )
    )
    return stack


async def test_user_flow_api_key(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, CONF_AUTH_METHOD: AUTH_API_KEY}
        )
        assert result["step_id"] == "api_key"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "aa:bb:cc:00:11:22"
    assert result["data"][CONF_API_KEY] == "test-key"


async def test_user_flow_password(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, CONF_AUTH_METHOD: AUTH_PASSWORD}
        )
        assert result["step_id"] == "password"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "pw"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "admin"


async def test_cannot_connect(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    mock_client.async_prepare = AsyncMock(side_effect=GwConnectionError("down"))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, CONF_AUTH_METHOD: AUTH_API_KEY}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "x"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_auth(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    mock_client.get_identity = AsyncMock(side_effect=GwAuthError("bad"))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, CONF_AUTH_METHOD: AUTH_API_KEY}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "x"}
        )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_aborts(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, CONF_AUTH_METHOD: AUTH_API_KEY}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
