"""Certificate trust as the user meets it: setup, the coordinator, and repairs.

Every test here asks a behavioural question — what is stored, what is raised,
what is withdrawn — rather than whether a helper was called. The two that decide
whether the feature is worth anything are the pair at the end: what gets pinned
is only ever what was put on screen, and nothing is pinned that the gateway has
stopped serving.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.unifi_gateway_rest.aiounifigw import (
    Capabilities,
    GwCertificateMismatch,
    GwConnectionError,
    TlsMode,
)
from custom_components.unifi_gateway_rest.const import (
    CONF_CERT_FINGERPRINT,
    CONF_TLS_MODE,
    DOMAIN,
    ISSUE_CERT_MISMATCH,
    ISSUE_TLS_INSECURE,
)
from custom_components.unifi_gateway_rest.repairs import async_create_fix_flow
from custom_components.unifi_gateway_rest.tls import ssl_for_entry, tls_mode_of
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import PINNED_FINGERPRINT

SERVED = "cd:" * 31 + "cd"
SWAPPED = "ef:" * 31 + "ef"

_PROBE = "custom_components.unifi_gateway_rest.repairs.async_probe_fingerprint"


# --- what an entry's stored trust resolves to ---------------------------------


def test_a_pinned_entry_pins() -> None:
    data = {CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_CERT_FINGERPRINT: PINNED_FINGERPRINT}
    assert tls_mode_of(data) is TlsMode.FINGERPRINT
    assert ssl_for_entry(data) is not True and ssl_for_entry(data) is not False


@pytest.mark.parametrize(
    ("stored", "mode", "ssl"),
    [
        ({CONF_VERIFY_SSL: True}, TlsMode.CA, True),
        ({CONF_VERIFY_SSL: False}, TlsMode.INSECURE, False),
        ({}, TlsMode.INSECURE, False),
    ],
)
def test_entries_that_predate_the_setting_keep_working_unchanged(
    stored: dict[str, Any], mode: TlsMode, ssl: bool
) -> None:
    """An upgrade must not silently pin a certificate nobody looked at."""
    assert tls_mode_of(stored) is mode
    assert ssl_for_entry(stored) is ssl


def test_a_pinning_entry_with_no_fingerprint_refuses_to_connect() -> None:
    """Fail closed. Falling back to unverified would be pinning that stopped pinning."""
    with pytest.raises(ValueError):
        ssl_for_entry({CONF_TLS_MODE: TlsMode.FINGERPRINT})


# --- setup and the coordinator ------------------------------------------------


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, client: AsyncMock) -> None:
    entry.add_to_hass(hass)
    with (
        patch("custom_components.unifi_gateway_rest.GatewayClient", return_value=client),
        patch(
            "custom_components.unifi_gateway_rest.probe",
            AsyncMock(return_value=Capabilities(device=True, health=True, sysinfo=True)),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_a_mismatch_at_setup_raises_a_repair_and_never_asks_for_credentials(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Reauth here would teach the user to retype a password at the worst moment."""
    mock_client.async_prepare = AsyncMock(
        side_effect=GwCertificateMismatch(PINNED_FINGERPRINT, SERVED)
    )
    await _setup(hass, config_entry, mock_client)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {
        "host": "192.0.2.10",
        "expected": PINNED_FINGERPRINT,
        "got": SERVED,
    }
    in_progress = hass.config_entries.flow.async_progress()
    assert not [f for f in in_progress if f["context"]["source"] == "reauth"]


async def test_a_certificate_that_changes_while_running_raises_the_repair_immediately(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Not just on the next restart: without this the user sees only 'unavailable'."""
    await _setup(hass, config_entry, mock_client)
    assert config_entry.state is ConfigEntryState.LOADED

    mock_client.get_device = AsyncMock(
        side_effect=GwCertificateMismatch(PINNED_FINGERPRINT, SWAPPED)
    )
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert config_entry.runtime_data.coordinator.last_update_success is False
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["got"] == SWAPPED


async def test_the_repair_is_withdrawn_once_the_gateway_answers_again(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    gateway_models: dict[str, Any],
) -> None:
    """A scary notification must not outlive the condition it describes."""
    await _setup(hass, config_entry, mock_client)
    coordinator = config_entry.runtime_data.coordinator

    mock_client.get_device = AsyncMock(
        side_effect=GwCertificateMismatch(PINNED_FINGERPRINT, SWAPPED)
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}"
    )

    mock_client.get_device = AsyncMock(return_value=gateway_models["device"])
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}")
        is None
    )


async def test_an_entry_that_verifies_nothing_is_flagged_but_keeps_working(
    hass: HomeAssistant, legacy_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, legacy_config_entry, mock_client)

    assert legacy_config_entry.state is ConfigEntryState.LOADED
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_TLS_INSECURE}_{legacy_config_entry.entry_id}"
    )
    assert issue is not None and issue.is_fixable


async def test_a_pinned_entry_is_not_flagged(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_TLS_INSECURE}_{config_entry.entry_id}")
        is None
    )


# --- the repair flows ---------------------------------------------------------


async def _insecure_flow(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    flow = await async_create_fix_flow(
        hass, f"{ISSUE_TLS_INSECURE}_{entry.entry_id}", {"entry_id": entry.entry_id}
    )
    flow.hass = hass
    return flow


async def _mismatch_flow(hass: HomeAssistant, entry: MockConfigEntry, got: str) -> Any:
    flow = await async_create_fix_flow(
        hass,
        f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}",
        {"entry_id": entry.entry_id, "expected": PINNED_FINGERPRINT, "fingerprint": got},
    )
    flow.hass = hass
    return flow


async def test_the_insecure_repair_pins_exactly_what_it_showed(
    hass: HomeAssistant, legacy_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The whole point of the feature: the value compared is the value stored."""
    await _setup(hass, legacy_config_entry, mock_client)
    flow = await _insecure_flow(hass, legacy_config_entry)

    with patch(_PROBE, AsyncMock(return_value=SERVED)):
        shown = await flow.async_step_init()
        assert shown["type"] is FlowResultType.FORM
        assert shown["description_placeholders"] == {"fingerprint": SERVED}
        with patch("custom_components.unifi_gateway_rest.GatewayClient", return_value=mock_client):
            done = await flow.async_step_confirm({})
            await hass.async_block_till_done()

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert legacy_config_entry.data[CONF_CERT_FINGERPRINT] == SERVED
    assert legacy_config_entry.data[CONF_TLS_MODE] == TlsMode.FINGERPRINT


async def test_a_certificate_that_moves_between_showing_and_confirming_is_not_pinned(
    hass: HomeAssistant, legacy_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Confirmation re-reads and compares. A test whose probe returns one value
    twice cannot tell this apart from pinning blindly, so the two calls differ."""
    await _setup(hass, legacy_config_entry, mock_client)
    flow = await _insecure_flow(hass, legacy_config_entry)

    with patch(_PROBE, AsyncMock(side_effect=[SERVED, SWAPPED])):
        await flow.async_step_init()
        again = await flow.async_step_confirm({})

    assert again["type"] is FlowResultType.FORM
    assert again["description_placeholders"] == {"fingerprint": SWAPPED}
    assert CONF_CERT_FINGERPRINT not in legacy_config_entry.data


async def test_the_mismatch_repair_pins_the_new_certificate_it_showed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, config_entry, mock_client)
    flow = await _mismatch_flow(hass, config_entry, SERVED)

    shown = await flow.async_step_init()
    assert shown["description_placeholders"] == {"expected": PINNED_FINGERPRINT, "got": SERVED}

    with (
        patch(_PROBE, AsyncMock(return_value=SERVED)),
        patch("custom_components.unifi_gateway_rest.GatewayClient", return_value=mock_client),
    ):
        done = await flow.async_step_confirm({})
        await hass.async_block_till_done()

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.data[CONF_CERT_FINGERPRINT] == SERVED


async def test_the_mismatch_repair_shows_a_third_certificate_rather_than_storing_it(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A repair can sit unread for days; what it offered may be long gone."""
    await _setup(hass, config_entry, mock_client)
    flow = await _mismatch_flow(hass, config_entry, SERVED)
    await flow.async_step_init()

    with patch(_PROBE, AsyncMock(return_value=SWAPPED)):
        again = await flow.async_step_confirm({})

    assert again["type"] is FlowResultType.FORM
    assert again["description_placeholders"] == {"expected": PINNED_FINGERPRINT, "got": SWAPPED}
    assert config_entry.data[CONF_CERT_FINGERPRINT] == PINNED_FINGERPRINT


async def test_a_repair_aborts_when_the_gateway_cannot_be_read(
    hass: HomeAssistant, legacy_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    await _setup(hass, legacy_config_entry, mock_client)
    flow = await _insecure_flow(hass, legacy_config_entry)

    with patch(_PROBE, AsyncMock(side_effect=GwConnectionError("down"))):
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert CONF_CERT_FINGERPRINT not in legacy_config_entry.data


async def test_a_repair_for_a_deleted_entry_aborts(hass: HomeAssistant) -> None:
    flow = await async_create_fix_flow(hass, f"{ISSUE_TLS_INSECURE}_gone", {"entry_id": "gone"})
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"


async def test_the_mismatch_repair_aborts_when_the_gateway_cannot_be_read(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The pinned certificate must survive a gateway that is merely unreachable."""
    await _setup(hass, config_entry, mock_client)
    flow = await _mismatch_flow(hass, config_entry, SERVED)
    await flow.async_step_init()

    with patch(_PROBE, AsyncMock(side_effect=GwConnectionError("down"))):
        result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert config_entry.data[CONF_CERT_FINGERPRINT] == PINNED_FINGERPRINT


async def test_the_mismatch_repair_for_a_deleted_entry_aborts(hass: HomeAssistant) -> None:
    flow = await async_create_fix_flow(
        hass,
        f"{ISSUE_CERT_MISMATCH}_gone",
        {"entry_id": "gone", "expected": PINNED_FINGERPRINT, "fingerprint": SERVED},
    )
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"
