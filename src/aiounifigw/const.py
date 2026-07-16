"""Constants: endpoint paths, defaults, header names.

All telemetry is read from the *classic* UniFi Network application API
(``/proxy/network/api/s/<site>/stat/*``), which — unlike the newer API-key
"Integration API" (``/integration/v1``) — exposes the full per-WAN, speedtest,
temperature and SFP payload. The classic endpoint is reachable with *either* an
API key (``X-API-Key``) or a local-account session (CSRF + ``TOKEN`` cookie).
"""

from __future__ import annotations

from typing import Final

DEFAULT_PORT: Final = 443
DEFAULT_TIMEOUT: Final = 15
# UniFi OS consoles ship a self-signed certificate, so certificate verification
# is OFF by default for local access. Callers on a trusted LAN can override with
# verify_ssl=True (and a pinned CA) — surfaced as an option in the HA config flow.
DEFAULT_VERIFY_SSL: Final = False
DEFAULT_SITE: Final = "default"

# UniFi OS core
PATH_LOGIN: Final = "/api/auth/login"
PATH_SYSTEM: Final = "/api/system"  # console identity (mac/name/shortname)

# UniFi Network application (reverse-proxied), classic API. `{site}` is the
# internal site name (usually "default").
PATH_SITES: Final = "/proxy/network/api/self/sites"
PATH_STAT_DEVICE: Final = "/proxy/network/api/s/{site}/stat/device"
PATH_STAT_HEALTH: Final = "/proxy/network/api/s/{site}/stat/health"
PATH_STAT_SYSINFO: Final = "/proxy/network/api/s/{site}/stat/sysinfo"

# Write / action endpoint (devmgr command channel). Payloads follow the
# well-established UniFi controller convention; they are NOT triggered during
# read-only operation and require a write-capable auth (session, or a
# write-scoped API key).
PATH_CMD_DEVMGR: Final = "/proxy/network/api/s/{site}/cmd/devmgr"

# Device `type` values that identify a UniFi OS gateway/console in /stat/device.
GATEWAY_TYPES: Final = frozenset({"ugw", "uxg", "ucg", "udm"})

HEADER_API_KEY: Final = "X-API-Key"
HEADER_CSRF: Final = "X-CSRF-Token"
HEADER_CSRF_UPDATED: Final = "X-Updated-CSRF-Token"
COOKIE_TOKEN: Final = "TOKEN"
