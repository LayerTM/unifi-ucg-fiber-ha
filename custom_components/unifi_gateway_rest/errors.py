"""Translate library errors into user-facing Home Assistant errors."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .aiounifigw import (
    GwAuthError,
    GwCapabilityError,
    GwCertificateMismatch,
    GwConnectionError,
    GwError,
)
from .const import DOMAIN


def action_error(err: GwError) -> HomeAssistantError:
    """Map a control-action failure to a translated HomeAssistantError."""
    if isinstance(err, GwCertificateMismatch):
        # Before GwConnectionError, its base class. "Could not reach the gateway"
        # is what a mismatch would otherwise say, and that reading sends the user
        # to check cables and credentials while the integration is refusing to
        # talk to something that is answering — and while a repair is waiting
        # with both fingerprints.
        key = "action_cert_mismatch"
    elif isinstance(err, GwAuthError):
        key = "action_auth_failed"
    elif isinstance(err, GwCapabilityError):
        key = "action_not_permitted"
    elif isinstance(err, GwConnectionError):
        key = "action_cannot_connect"
    else:
        key = "action_failed"
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)
