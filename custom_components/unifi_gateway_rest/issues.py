"""Repair issues this integration raises.

Its own module because both setup and the coordinator raise the certificate
issue, and the coordinator importing the package root would be a cycle.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .aiounifigw import GwCertificateMismatch
from .const import DOMAIN, ISSUE_CERT_MISMATCH


def raise_cert_mismatch(
    hass: HomeAssistant, entry: ConfigEntry, err: GwCertificateMismatch
) -> None:
    """Raise the repair that shows both fingerprints and offers the new one."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_CERT_MISMATCH,
        translation_placeholders={
            "host": entry.data[CONF_HOST],
            "expected": err.expected,
            "got": err.got,
        },
        data={
            "entry_id": entry.entry_id,
            "expected": err.expected,
            "fingerprint": err.got,
        },
    )


def clear_cert_mismatch(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Withdraw the certificate repair; a no-op when none is raised."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}")
