"""Repair flows for the TLS trust of a UniFi Gateway entry.

Two things can go wrong with a pinned certificate, and neither is an
authentication problem, so neither belongs in the reauth flow:

* the gateway now serves a different certificate — it was reissued, or something
  is impersonating it. Only the user can tell those apart, so both fingerprints
  are shown and accepting the new one is an explicit act.
* the entry predates pinning and still verifies nothing. It keeps working; this
  offers the one-time step that starts pinning.

Both flows obey the same two rules, which pull in opposite directions and are
easy to satisfy one at a time and get wrong together:

1. **Pin only what was shown.** Reading the certificate again on confirmation and
   storing that would record something the user never compared.
2. **Never pin what is no longer served.** A repair can sit in the notification
   list for days; the certificate behind it may be long gone.

So confirmation re-reads the certificate and compares it against the one on
screen: equal, it is pinned; different, the form comes back showing the new one,
and nothing is stored until the user has seen the value being accepted.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .aiounifigw import GwConnectionError, TlsMode, async_probe_fingerprint
from .const import (
    CONF_CERT_FINGERPRINT,
    CONF_TLS_MODE,
    DEFAULT_PORT,
    DOMAIN,
    ISSUE_CERT_MISMATCH,
)


class _PinCertificateFlow(RepairsFlow):
    """Shared behaviour: show a certificate, confirm it, pin it, reload."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id
        self._shown: str | None = None

    @property
    def _entry(self) -> ConfigEntry | None:
        return self.hass.config_entries.async_get_entry(self._entry_id)

    async def _async_current_fingerprint(self, entry: ConfigEntry) -> str | None:
        """What the gateway is serving right now, or None if it cannot be read."""
        try:
            return await async_probe_fingerprint(
                entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT)
            )
        except GwConnectionError:
            return None

    async def _async_pin(self, entry: ConfigEntry, fingerprint: str) -> FlowResult:
        self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_TLS_MODE: TlsMode.FINGERPRINT,
                CONF_CERT_FINGERPRINT: fingerprint,
            },
        )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_create_entry(data={})

    def _async_show(self, step_id: str, placeholders: dict[str, str]) -> FlowResult:
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema({}), description_placeholders=placeholders
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        raise NotImplementedError  # pragma: no cover - both subclasses implement it

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()


class CertMismatchRepairFlow(_PinCertificateFlow):
    """Accept a certificate that replaced the pinned one."""

    def __init__(self, entry_id: str, expected: str, got: str) -> None:
        super().__init__(entry_id)
        self._expected = expected
        self._shown = got

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self._entry
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        if user_input is None:
            return self._async_show(
                "confirm", {"expected": self._expected, "got": self._shown or ""}
            )
        current = await self._async_current_fingerprint(entry)
        if current is None:
            return self.async_abort(reason="cannot_connect")
        if current != self._shown:
            # Moved again between the notification and the click. Show the value
            # actually on offer rather than storing one nobody looked at.
            self._shown = current
            return self._async_show("confirm", {"expected": self._expected, "got": current})
        return await self._async_pin(entry, current)


class TlsInsecureRepairFlow(_PinCertificateFlow):
    """Start pinning on an entry that currently verifies nothing."""

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self._entry
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        current = await self._async_current_fingerprint(entry)
        if current is None:
            return self.async_abort(reason="cannot_connect")
        if user_input is not None and current == self._shown:
            return await self._async_pin(entry, current)
        self._shown = current
        return self._async_show("confirm", {"fingerprint": current})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Build the flow for one of this integration's repair issues."""
    payload = data or {}
    entry_id = str(payload.get("entry_id", ""))
    if issue_id.startswith(ISSUE_CERT_MISMATCH):
        return CertMismatchRepairFlow(
            entry_id, str(payload.get("expected", "")), str(payload.get("fingerprint", ""))
        )
    return TlsInsecureRepairFlow(entry_id)


__all__ = ["DOMAIN", "async_create_fix_flow"]
