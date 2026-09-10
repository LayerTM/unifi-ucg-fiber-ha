"""Coordinator degraded-path and stale-device removal tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import yarl
from custom_components.unifi_gateway_rest import async_remove_config_entry_device
from custom_components.unifi_gateway_rest.aiounifigw import (
    ApiKeyAuth,
    Capabilities,
    GatewayClient,
    GwApiError,
)
from custom_components.unifi_gateway_rest.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from multidict import CIMultiDict
from pytest_homeassistant_custom_component.common import MockConfigEntry


class _SpaResponse:
    """Response serving the UniFi OS SPA shell instead of JSON."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.headers: dict[str, str] = {}

    async def __aenter__(self) -> _SpaResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> Any:
        info = aiohttp.RequestInfo(yarl.URL("https://192.0.2.10/x"), "GET", CIMultiDict(), None)
        raise aiohttp.ContentTypeError(info, (), message="text/html")

    async def read(self) -> bytes:
        return b"<!doctype html><html><head><title>UniFi OS</title></head></html>"


class _SpaSession:
    """Session whose console answers every path with its web UI (or a status)."""

    def __init__(self, status: int = 200) -> None:
        self._status = status

    def request(self, method: str, url: str, **kwargs: Any) -> _SpaResponse:
        return _SpaResponse(self._status)


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


async def test_console_serving_ui_does_not_trigger_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A console answering an API path with its web UI must not detach the entry.

    End-to-end through the real transport, because the defect lived there: it
    classified a 2xx-non-JSON body as an auth failure, and the coordinator turns
    an auth failure into ConfigEntryAuthFailed — terminal in Home Assistant. One
    such response during a firmware update permanently detached the entry while
    the credential was still valid. The console is merely unavailable, so this has
    to surface as UpdateFailed and be retried.
    """
    caps = Capabilities(device=True, health=True, sysinfo=True)
    await _setup(hass, config_entry, mock_client, caps)
    assert config_entry.state is ConfigEntryState.LOADED

    coordinator = config_entry.runtime_data.coordinator
    # Swap in a real client whose console serves the SPA shell on every path.
    coordinator.client = GatewayClient(
        _SpaSession(),  # type: ignore[arg-type]
        "192.0.2.10",
        ApiKeyAuth("still-valid-key"),
        ssl=False,
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert config_entry.state is ConfigEntryState.LOADED
    assert not [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]


async def test_real_401_still_triggers_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The other half of the contract: a rejected credential must still reauth."""
    caps = Capabilities(device=True, health=True, sysinfo=True)
    await _setup(hass, config_entry, mock_client, caps)

    coordinator = config_entry.runtime_data.coordinator
    coordinator.client = GatewayClient(
        _SpaSession(status=401),  # type: ignore[arg-type]
        "192.0.2.10",
        ApiKeyAuth("revoked-key"),
        ssl=False,
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]
