"""Diagnostics support for the UniFi Gateway integration."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import GatewayConfigEntry

CONFIG_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME, CONF_HOST}
# Device-identifying / network PII that must never appear in a shared diagnostic.
DATA_REDACT = {"mac", "ip", "wan_ip"}


def _plain(obj: Any) -> Any:
    """Dataclass -> JSON-native dict/list (tuples become lists, datetimes strings).

    ``async_redact_data`` recurses into dicts and lists but not tuples, and
    ``dataclasses.asdict`` emits tuples for tuple-typed fields (wans, sfp_ports),
    which would leave nested PII (WAN IP) unredacted — so normalize first.
    """
    return json.loads(json.dumps(asdict(obj), default=str))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GatewayConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    caps = coordinator.capabilities
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), CONFIG_REDACT),
            "options": dict(entry.options),
            "unique_id_set": entry.unique_id is not None,
        },
        "capabilities": {
            "device": caps.device,
            "health": caps.health,
            "sysinfo": caps.sysinfo,
        },
        "device": async_redact_data(_plain(data.device), DATA_REDACT),
        "health": async_redact_data(_plain(data.health), DATA_REDACT) if data.health else None,
        "sysinfo": _plain(data.sysinfo) if data.sysinfo else None,
    }
