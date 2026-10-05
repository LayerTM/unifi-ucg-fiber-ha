"""Tests for the exception hierarchy."""

from __future__ import annotations

from aiounifigw.exceptions import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwConnectionError,
    GwError,
    describe,
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


def test_describe_keeps_a_message() -> None:
    assert describe(OSError("Connection refused")) == "Connection refused"


def test_describe_never_returns_empty() -> None:
    assert describe(TimeoutError()) == "TimeoutError"
