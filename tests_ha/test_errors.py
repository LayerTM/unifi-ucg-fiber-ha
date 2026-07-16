"""Tests for control-action error translation."""

from __future__ import annotations

import pytest
from custom_components.unifi_gateway_rest.aiounifigw import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwConnectionError,
    GwError,
)
from custom_components.unifi_gateway_rest.errors import action_error
from homeassistant.exceptions import HomeAssistantError


@pytest.mark.parametrize(
    ("err", "key"),
    [
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
