"""Config flow for the UniFi Gateway integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .aiounifigw import (
    ApiKeyAuth,
    GatewayClient,
    GwAuthError,
    GwCapabilityError,
    GwCertificateMismatch,
    GwConnectionError,
    SessionAuth,
    SystemIdentity,
    TlsMode,
    async_probe_fingerprint,
)
from .aiounifigw.auth import AbstractAuth
from .const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_CERT_FINGERPRINT,
    CONF_ENABLE_CONTROLS,
    CONF_SITE,
    CONF_TLS_MODE,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SITE,
    DEFAULT_TLS_MODE,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .tls import ssl_for_entry, tls_mode_of

_LOGGER = logging.getLogger(__name__)

_API_KEY_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})
_PASSWORD_SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})


def _auth_from_input(method: str, user_input: dict[str, Any]) -> AbstractAuth:
    if method == AUTH_API_KEY:
        return ApiKeyAuth(user_input[CONF_API_KEY])
    return SessionAuth(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])


def _tls_default(defaults: dict[str, Any]) -> str:
    """Preselect the entry's current mode, or the pinning default for a new one."""
    return str(tls_mode_of(defaults)) if defaults else str(DEFAULT_TLS_MODE)


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Host / port / site / TLS / auth-method form, optionally prefilled."""
    d = defaults or {}
    host = (
        vol.Required(CONF_HOST, default=d[CONF_HOST]) if CONF_HOST in d else vol.Required(CONF_HOST)
    )
    return vol.Schema(
        {
            host: str,
            vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Required(CONF_SITE, default=d.get(CONF_SITE, DEFAULT_SITE)): str,
            vol.Required(CONF_TLS_MODE, default=_tls_default(d)): SelectSelector(
                SelectSelectorConfig(
                    options=[TlsMode.FINGERPRINT, TlsMode.CA, TlsMode.INSECURE],
                    translation_key="tls_mode",
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_AUTH_METHOD, default=d.get(CONF_AUTH_METHOD, AUTH_API_KEY)): (
                SelectSelector(
                    SelectSelectorConfig(
                        options=[AUTH_API_KEY, AUTH_PASSWORD],
                        translation_key="auth_method",
                        mode=SelectSelectorMode.LIST,
                    )
                )
            ),
        }
    )


class UnifiGatewayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Gateway."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GatewayOptionsFlow()

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect host / port / site / TLS and the chosen auth method."""
        if user_input is not None:
            self._data.update(user_input)
            return await self._after_connection()
        return self.async_show_form(step_id="user", data_schema=_connection_schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host / port / site / TLS / credentials for an existing entry."""
        if user_input is not None:
            self._data.update(user_input)
            return await self._after_connection()
        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure", data_schema=_connection_schema(dict(entry.data))
        )

    async def _after_connection(self) -> ConfigFlowResult:
        """Pin the certificate first when asked to, then collect credentials."""
        if self._data[CONF_TLS_MODE] == TlsMode.FINGERPRINT:
            return await self.async_step_tls_fingerprint()
        self._data.pop(CONF_CERT_FINGERPRINT, None)
        return await self._credentials_step()

    async def _credentials_step(self) -> ConfigFlowResult:
        if self._data[CONF_AUTH_METHOD] == AUTH_API_KEY:
            return await self.async_step_api_key()
        return await self.async_step_password()

    async def async_step_tls_fingerprint_changed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Same step, shown when the certificate differs from the stored one."""
        return await self.async_step_tls_fingerprint(user_input)

    async def async_step_tls_fingerprint(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the certificate the gateway is serving and have the user accept it.

        Nothing is trusted by reading it: the fingerprint is displayed so the
        person setting this up can compare it with the console's own UI. Only
        after they submit does it become the one certificate this entry accepts.
        """
        if user_input is not None:
            return await self._credentials_step()
        try:
            fingerprint = await async_probe_fingerprint(
                self._data[CONF_HOST], self._data[CONF_PORT]
            )
        except GwConnectionError:
            return self.async_show_form(
                step_id="user",
                data_schema=_connection_schema(self._data),
                errors={"base": "cannot_connect"},
            )
        # Reconfiguring an already-pinned entry must say so when the certificate
        # is not the one on file. Without it, someone who opened reconfigure to
        # change an API key during an impersonation would accept a stranger's
        # certificate with nothing on screen to notice.
        previous = self._previous_fingerprint()
        self._data[CONF_CERT_FINGERPRINT] = fingerprint
        return self.async_show_form(
            step_id="tls_fingerprint_changed"
            if previous and previous != fingerprint
            else "tls_fingerprint",
            data_schema=vol.Schema({}),
            description_placeholders={"fingerprint": fingerprint, "previous": previous or ""},
        )

    def _previous_fingerprint(self) -> str | None:
        """The fingerprint already stored for this entry, when reconfiguring one."""
        if self.source != SOURCE_RECONFIGURE:
            return None
        entry = self._get_reconfigure_entry()
        stored = entry.data.get(CONF_CERT_FINGERPRINT)
        return str(stored) if stored else None

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate an API key."""
        return await self._auth_step("api_key", AUTH_API_KEY, _API_KEY_SCHEMA, user_input)

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate a local account."""
        return await self._auth_step("password", AUTH_PASSWORD, _PASSWORD_SCHEMA, user_input)

    async def _auth_step(
        self,
        step_id: str,
        method: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._data, CONF_AUTH_METHOD: method, **user_input}
            try:
                identity = await self._probe(data, _auth_from_input(method, user_input))
            except GwCertificateMismatch:
                errors["base"] = "cert_mismatch"
            except GwAuthError:
                errors["base"] = "invalid_auth"
            except GwConnectionError:
                errors["base"] = "cannot_connect"
            except GwCapabilityError:
                errors["base"] = "insufficient_permissions"
            except Exception:
                _LOGGER.exception("Unexpected error validating UniFi Gateway connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(identity.mac)
                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), data=data
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=_title(identity, data), data=data)
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication when credentials stop working."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        method = self._data.get(CONF_AUTH_METHOD, AUTH_API_KEY)
        schema = _API_KEY_SCHEMA if method == AUTH_API_KEY else _PASSWORD_SCHEMA
        if user_input is not None:
            data = {**self._data, **user_input}
            try:
                identity = await self._probe(data, _auth_from_input(method, user_input))
            except GwCertificateMismatch:
                errors["base"] = "cert_mismatch"
            except GwAuthError:
                errors["base"] = "invalid_auth"
            except GwConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during UniFi Gateway reauth")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(identity.mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    async def _probe(self, data: dict[str, Any], auth: AbstractAuth) -> SystemIdentity:
        """Validate connectivity + auth; return the device identity (for unique_id)."""
        # The per-request ssl argument decides the trust, so the shared session
        # is the ordinary verifying one; passing a Fingerprint makes aiohttp use
        # its unverified context for that request alone.
        session = async_get_clientsession(self.hass)
        client = GatewayClient(
            session,
            data[CONF_HOST],
            auth,
            site=data.get(CONF_SITE, DEFAULT_SITE),
            port=data[CONF_PORT],
            use_ssl=True,
            ssl=ssl_for_entry(data),
        )
        await client.async_prepare()
        identity = await client.get_identity()
        await client.get_device()  # confirm the gateway is reachable with this auth
        return identity


def _title(identity: SystemIdentity, data: dict[str, Any]) -> str:
    name = identity.name or "UniFi Gateway"
    return f"{name} ({data[CONF_HOST]})"


class GatewayOptionsFlow(OptionsFlow):
    """Options: poll interval and opt-in control (write) entities."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_CONTROLS,
                    default=options.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
