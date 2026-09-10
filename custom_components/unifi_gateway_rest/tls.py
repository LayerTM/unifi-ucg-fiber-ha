"""Resolve a config entry's stored TLS trust into an aiohttp ssl argument."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
from homeassistant.const import CONF_VERIFY_SSL

from .aiounifigw import TlsMode, ssl_param
from .const import CONF_CERT_FINGERPRINT, CONF_TLS_MODE, DEFAULT_VERIFY_SSL


def tls_mode_of(data: Mapping[str, Any]) -> TlsMode:
    """The entry's TLS mode, deriving one for entries that predate the setting.

    An older entry stored only ``verify_ssl``. ``True`` meant CA verification and
    maps across exactly. ``False`` meant no verification, and is carried over
    *as* no verification rather than silently upgraded to a pinned certificate:
    pinning whatever the gateway happens to serve during an upgrade would record
    a certificate the user never saw, including a substituted one. The user is
    asked instead, through the repair issue raised at setup.
    """
    stored = data.get(CONF_TLS_MODE)
    if stored:
        return TlsMode(stored)
    if data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL):
        return TlsMode.CA
    return TlsMode.INSECURE


def ssl_for_entry(data: Mapping[str, Any]) -> bool | aiohttp.Fingerprint:
    """Build the per-request ``ssl`` argument for this entry's stored trust."""
    return ssl_param(tls_mode_of(data), data.get(CONF_CERT_FINGERPRINT))
