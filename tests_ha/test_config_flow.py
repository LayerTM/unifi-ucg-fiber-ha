"""Config-flow tests for the UniFi Gateway integration."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import (
    GwAuthError,
    GwCertificateMismatch,
    GwConnectionError,
    TlsMode,
)
from custom_components.unifi_gateway_rest.const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_CERT_FINGERPRINT,
    CONF_SITE,
    CONF_TLS_MODE,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import PINNED_FINGERPRINT

CONNECTION = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 443,
    CONF_SITE: "default",
    CONF_TLS_MODE: TlsMode.INSECURE,
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


# --- pinning the certificate during setup -------------------------------------

_FLOW_PROBE = "custom_components.unifi_gateway_rest.config_flow.async_probe_fingerprint"
SERVED = "cd:" * 31 + "cd"


async def test_pinning_shows_the_fingerprint_before_asking_for_credentials(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """The user has to be able to compare it, so it is shown on its own screen."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client), patch(_FLOW_PROBE, AsyncMock(return_value=SERVED)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
        assert result["step_id"] == "tls_fingerprint"
        assert result["description_placeholders"]["fingerprint"] == SERVED

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "api_key"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TLS_MODE] == TlsMode.FINGERPRINT
    assert result["data"][CONF_CERT_FINGERPRINT] == SERVED


async def test_choosing_a_non_pinning_mode_stores_no_fingerprint(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.CA, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
        assert result["step_id"] == "api_key"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )
    assert CONF_CERT_FINGERPRINT not in result["data"]


async def test_a_gateway_that_cannot_be_read_returns_to_the_connection_form(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with (
        _patch_client(mock_client),
        patch(_FLOW_PROBE, AsyncMock(side_effect=GwConnectionError("down"))),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_says_so_when_the_certificate_is_not_the_one_on_file(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Someone reconfiguring during an impersonation must see the discrepancy.

    Without this the new certificate is adopted with nothing on screen to notice.
    """
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": config_entry.entry_id},
    )
    with _patch_client(mock_client), patch(_FLOW_PROBE, AsyncMock(return_value=SERVED)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )

    assert result["step_id"] == "tls_fingerprint_changed"
    assert result["description_placeholders"] == {
        "fingerprint": SERVED,
        "previous": PINNED_FINGERPRINT,
    }


async def test_a_mismatch_while_validating_credentials_is_not_reported_as_bad_auth(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """ "Invalid credentials" would send the user to retype a password that is fine."""
    mock_client.async_prepare = AsyncMock(
        side_effect=GwCertificateMismatch(PINNED_FINGERPRINT, SERVED)
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with _patch_client(mock_client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, CONF_AUTH_METHOD: AUTH_API_KEY}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )
    assert result["errors"] == {"base": "cert_mismatch"}


async def test_reconfigure_that_accepts_the_new_certificate_stores_it(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Having been warned, the user can still accept — and then it is pinned."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": config_entry.entry_id},
    )
    with _patch_client(mock_client), patch(_FLOW_PROBE, AsyncMock(return_value=SERVED)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
        assert result["step_id"] == "tls_fingerprint_changed"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "api_key"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_CERT_FINGERPRINT] == SERVED


async def test_an_unreachable_gateway_during_reconfigure_stays_in_reconfigure(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The form must name the step the user is actually in.

    Naming "user" here put the first-time-setup title above a form that was
    editing an existing entry, and routed the resubmission through the other
    flow's step — harmless today only because the two happen to be symmetric.
    """
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": config_entry.entry_id},
    )
    with (
        _patch_client(mock_client),
        patch(_FLOW_PROBE, AsyncMock(side_effect=GwConnectionError("down"))),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )

    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_the_same_failure_in_a_new_setup_stays_in_user(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """The other half of the same rule, so the fix cannot be a constant swap."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with (
        _patch_client(mock_client),
        patch(_FLOW_PROBE, AsyncMock(side_effect=GwConnectionError("down"))),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )

    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_the_recovered_reconfigure_can_still_be_submitted(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A renamed step is only right if the form it shows still leads somewhere."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": config_entry.entry_id},
    )
    connection = {**CONNECTION, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY}
    with _patch_client(mock_client):
        with patch(_FLOW_PROBE, AsyncMock(side_effect=GwConnectionError("down"))):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], connection)
        assert result["step_id"] == "reconfigure"
        with patch(_FLOW_PROBE, AsyncMock(return_value=SERVED)):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], connection)
            assert result["step_id"] == "tls_fingerprint_changed"
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
            assert result["step_id"] == "api_key"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_API_KEY: "test-key"}
            )
            await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
