"""Tests for the exception hierarchy."""

from __future__ import annotations

from aiounifigw.exceptions import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwConnectionError,
    GwError,
)


def test_hierarchy() -> None:
    for exc in (GwConnectionError, GwAuthError, GwApiError, GwCapabilityError):
        assert issubclass(exc, GwError)


def test_api_error_status() -> None:
    err = GwApiError("boom", status=502)
    assert err.status == 502
    assert str(err) == "boom"


def test_api_error_status_default_none() -> None:
    assert GwApiError("x").status is None
