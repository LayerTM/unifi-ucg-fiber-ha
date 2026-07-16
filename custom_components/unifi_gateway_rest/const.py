"""Constants for the UniFi Gateway (non-invasive) integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "unifi_gateway_rest"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

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
DEFAULT_VERIFY_SSL: Final = False
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 3600

MANUFACTURER: Final = "Ubiquiti"
