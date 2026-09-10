"""Tests for control-action error translation."""

from __future__ import annotations

import pytest
from custom_components.unifi_gateway_rest.aiounifigw import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwCertificateMismatch,
    GwConnectionError,
    GwError,
)
from custom_components.unifi_gateway_rest.errors import action_error
from homeassistant.exceptions import HomeAssistantError


@pytest.mark.parametrize(
    ("err", "key"),
    [
        (GwCertificateMismatch("ab:ab", "cd:cd"), "action_cert_mismatch"),
        (GwAuthError("x"), "action_auth_failed"),
        (GwCapabilityError("x"), "action_not_permitted"),
        (GwConnectionError("x"), "action_cannot_connect"),
        (GwApiError("x"), "action_failed"),
        (GwError("x"), "action_failed"),
    ],
)
def test_action_error_mapping(err: GwError, key: str) -> None:
    result = action_error(err)
    assert isinstance(result, HomeAssistantError)
    assert result.translation_key == key
    assert result.translation_domain == "unifi_gateway_rest"


def test_a_certificate_mismatch_is_not_reported_as_a_connection_failure() -> None:
    """It is a GwConnectionError subclass, so order in the mapping is the whole fix.

    "Could not reach the gateway" sends the user to check cables and credentials,
    while the truth is that something answered and was refused — and a repair is
    already waiting with both fingerprints.
    """
    result = action_error(GwCertificateMismatch("ab:ab", "cd:cd"))
    assert result.translation_key == "action_cert_mismatch"
    assert result.translation_key != "action_cannot_connect"


def test_every_action_error_key_has_text() -> None:
    """A translated error with no string renders as the raw key to the user."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components" / "unifi_gateway_rest"
    for name in ("strings.json", "translations/en.json"):
        exceptions = json.loads((root / name).read_text(encoding="utf-8"))["exceptions"]
        for key in (
            "action_cert_mismatch",
            "action_auth_failed",
            "action_not_permitted",
            "action_cannot_connect",
            "action_failed",
        ):
            assert exceptions[key]["message"].strip(), f"{name}: {key}"
