"""Every path that changes an entry sets it up exactly once.

The entry keeps an update listener that reloads it. Reconfigure,
re-authentication and the certificate repair used to update the entry — firing
that listener, reload one — and then schedule a reload of their own — reload
two. The core reports that combination as breaking in 2026.12, but the first
reload removed the listener before the core looked, so the report never
appeared. None of this is visible unless the entry is loaded first, which is why
these tests set it up before touching it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import custom_components.unifi_gateway_rest as integration
import homeassistant.config_entries as config_entries
from custom_components.unifi_gateway_rest.aiounifigw import Capabilities, GwAuthError, TlsMode
from custom_components.unifi_gateway_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    CONF_SITE,
    CONF_TLS_MODE,
    DEFAULT_SCAN_INTERVAL,
    ISSUE_TLS_INSECURE,
)
from custom_components.unifi_gateway_rest.repairs import async_create_fix_flow
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

CAPS = Capabilities(device=True, health=True, sysinfo=True)
_PROBE = "custom_components.unifi_gateway_rest.repairs.async_probe_fingerprint"


class _Watch:
    def __init__(self) -> None:
        self.setups = 0
        self.reports: list[str] = []


@contextmanager
def _patched(client: AsyncMock) -> Iterator[None]:
    with (
        patch.multiple(
            "custom_components.unifi_gateway_rest",
            GatewayClient=lambda *a, **k: client,
            probe=AsyncMock(return_value=CAPS),
        ),
        patch(
            "custom_components.unifi_gateway_rest.config_flow.GatewayClient", return_value=client
        ),
    ):
        yield


@contextmanager
def _watch() -> Iterator[_Watch]:
    """Count setups of the entry and any report the core makes about reloading."""
    watch = _Watch()
    real_setup = integration.async_setup_entry
    real_report = config_entries.report_usage

    async def counting_setup(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
        watch.setups += 1
        return await real_setup(hass, entry)

    def recording_report(what: str, *args: Any, **kwargs: Any) -> None:
        watch.reports.append(what)
        real_report(what, *args, **kwargs)

    with (
        patch.object(integration, "async_setup_entry", counting_setup),
        patch.object(config_entries, "report_usage", recording_report),
    ):
        yield watch


async def _loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_reconfiguring_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    with _patched(mock_client):
        await _loaded(hass, config_entry)
        with _watch() as watch:
            result = await config_entry.start_reconfigure_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_HOST: "192.0.2.55",
                    CONF_PORT: 443,
                    CONF_SITE: "default",
                    CONF_TLS_MODE: TlsMode.INSECURE,
                    CONF_AUTH_METHOD: AUTH_API_KEY,
                },
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_API_KEY: "new-key"}
            )
            await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert watch.setups == 1
    assert watch.reports == []


async def test_reauthenticating_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    with _patched(mock_client):
        await _loaded(hass, config_entry)
        with _watch() as watch:
            result = await config_entry.start_reauth_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_API_KEY: "new-key"}
            )
            await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert watch.setups == 1
    assert watch.reports == []


async def test_changing_options_on_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    with _patched(mock_client):
        await _loaded(hass, config_entry)
        with _watch() as watch:
            result = await hass.config_entries.options.async_init(config_entry.entry_id)
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], {CONF_ENABLE_CONTROLS: True}
            )
            await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert watch.setups == 1


async def test_saving_unchanged_options_does_not_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The other branch: a reload that nothing asked for is not free either."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL, CONF_ENABLE_CONTROLS: False},
    )
    with _patched(mock_client):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        with _watch() as watch:
            result = await hass.config_entries.options.async_init(config_entry.entry_id)
            current = {**config_entry.options}
            result = await hass.config_entries.options.async_configure(result["flow_id"], current)
            await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert watch.setups == 0


async def test_pinning_a_certificate_on_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, legacy_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The repair reloads the entry itself; the listener used to add a second one."""
    fingerprint = "cd:" * 31 + "cd"
    with _patched(mock_client):
        await _loaded(hass, legacy_config_entry)
        flow = await async_create_fix_flow(
            hass,
            f"{ISSUE_TLS_INSECURE}_{legacy_config_entry.entry_id}",
            {"entry_id": legacy_config_entry.entry_id},
        )
        flow.hass = hass
        with _watch() as watch, patch(_PROBE, AsyncMock(return_value=fingerprint)):
            await flow.async_step_init()
            await flow.async_step_confirm({})
            await hass.async_block_till_done()

    assert legacy_config_entry.data[CONF_TLS_MODE] == TlsMode.FINGERPRINT
    assert watch.setups == 1


async def test_reauthenticating_with_unchanged_credentials_still_reloads(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The listener fires only on a change, so the reload must come from elsewhere.

    Without it an entry that failed on a transient auth error would stay failed
    after the user confirmed the very credentials it already had.
    """
    with _patched(mock_client):
        await _loaded(hass, config_entry)
        with _watch() as watch:
            result = await config_entry.start_reauth_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_API_KEY: config_entry.data[CONF_API_KEY]}
            )
            await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert watch.setups == 1


async def test_reauthenticating_an_entry_that_failed_setup_loads_it_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A failed entry has no listener yet, so the changed data alone reloads nothing."""
    config_entry.add_to_hass(hass)
    mock_client.async_prepare = AsyncMock(side_effect=GwAuthError("rejected"))
    with _patched(mock_client):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR

    # The failed setup has already opened the re-authentication; answer that one,
    # as a user would, rather than starting a second.
    [flow] = [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"]["source"] == SOURCE_REAUTH
    ]
    mock_client.async_prepare = AsyncMock(return_value=None)
    with _patched(mock_client), _watch() as watch:
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert watch.setups == 1
    assert config_entry.state is ConfigEntryState.LOADED
