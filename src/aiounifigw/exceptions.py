"""Exception hierarchy for aiounifigw."""

from __future__ import annotations


def describe(err: BaseException) -> str:
    """Text for a caught exception that is never empty.

    Several of the failures this library wraps carry no message at all — most
    visibly ``TimeoutError()`` — and interpolating them verbatim leaves an error
    that names no cause. Fall back to the exception's type name.
    """
    return str(err) or type(err).__name__


class GwError(Exception):
    """Base error for all aiounifigw failures."""


class GwConnectionError(GwError):
    """Network / TLS / timeout failure talking to the console."""


class GwAuthError(GwError):
    """Authentication failed or the session/key is no longer valid."""


class GwApiError(GwError):
    """The API returned an unexpected status or body."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GwCapabilityError(GwError):
    """The active auth method is not permitted to use this endpoint."""
