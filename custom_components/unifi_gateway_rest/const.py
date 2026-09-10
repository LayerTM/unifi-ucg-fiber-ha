"""Constants for the UniFi Gateway (non-invasive) integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

from .aiounifigw import TlsMode

DOMAIN: Final = "unifi_gateway_rest"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

# The platforms that exist only while controls are switched on. Stated here so
# the setup that creates them and the cleanup that removes them cannot disagree,
# and so a future control entity on another platform is covered by adding it
# here rather than by remembering to edit two places.
CONTROL_PLATFORMS: Final = (Platform.BUTTON,)

# Entities this integration used to create and no longer does, by the suffix of
# their unique id. A registry entry outlives the platform that stopped providing
# it, so without this an upgrade leaves the entity on the device page forever,
# permanently unavailable. Withdrawing another entity is one line here.
WITHDRAWN_UNIQUE_ID_SUFFIXES: Final = ("_speedtest_in_progress",)

# config-entry keys (host/port/username/password/api_key/verify_ssl reuse HA consts)
CONF_AUTH_METHOD: Final = "auth_method"
AUTH_API_KEY: Final = "api_key"
AUTH_PASSWORD: Final = "password"

CONF_SITE: Final = "site"
DEFAULT_SITE: Final = "default"

# Opt-in control (write) operations. Off by default — the integration is
# read-only unless the user explicitly enables controls with write-capable auth.
CONF_ENABLE_CONTROLS: Final = "enable_controls"
DEFAULT_ENABLE_CONTROLS: Final = False

DEFAULT_PORT: Final = 443

# TLS trust. The gateway's certificate is self-signed, so the choice is between
# pinning it and not checking at all; pinning is the default. CONF_VERIFY_SSL is
# still read once, to migrate entries created before this existed.
CONF_TLS_MODE: Final = "tls_mode"
CONF_CERT_FINGERPRINT: Final = "cert_fingerprint"
DEFAULT_TLS_MODE: Final = TlsMode.FINGERPRINT
ISSUE_CERT_MISMATCH: Final = "cert_mismatch"
ISSUE_TLS_INSECURE: Final = "tls_insecure"

DEFAULT_VERIFY_SSL: Final = False
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 3600

MANUFACTURER: Final = "Ubiquiti"
