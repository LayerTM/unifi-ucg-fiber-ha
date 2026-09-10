"""Shared fixtures for the Home Assistant integration test-suite."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from custom_components.unifi_gateway_rest.aiounifigw import (
    Device,
    Health,
    SysInfo,
    SystemIdentity,
    TlsMode,
)
from custom_components.unifi_gateway_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_CERT_FINGERPRINT,
    CONF_SITE,
    CONF_TLS_MODE,
    DOMAIN,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_VERIFY_SSL,
)
from homeassistant.helpers import frame
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# Home Assistant announces every deprecated API it catches an integration using
# through one of three log channels, each with a fixed sentence of core's own:
#
#   helpers.frame.report_usage        "Detected that custom integration '<domain>' ..."
#   helpers.deprecation               "The deprecated <thing> was <used> from <domain> ..."
#   helpers.deprecation (substitute)  "'<old>' is deprecated. Please rename ..."
#
# Watching the channels rather than the APIs is what makes this general: an API
# core deprecates next year turns this suite red the first time the floating
# harness carries that release, in core's own words and naming the call site,
# without any test having been taught the name of that API in advance.
_DEPRECATION_SENTENCES = (
    "Detected that custom integration",
    "The deprecated ",
    "is deprecated. Please rename",
)

_OUR_PACKAGE = "custom_components.unifi_gateway_rest"


def ha_deprecation_reports(records: list[logging.LogRecord]) -> list[str]:
    """Return core's deprecation notices about this integration, in its own words."""
    found = []
    for record in records:
        if record.levelno < logging.WARNING:
            continue
        message = record.getMessage()
        if not any(sentence in message for sentence in _DEPRECATION_SENTENCES):
            continue
        # The frame and deprecation channels name the domain in the message; the
        # substitute channel logs under the reporting module instead.
        if DOMAIN in message or record.name.startswith(_OUR_PACKAGE):
            found.append(f"{record.name}: {message}")
    return found


class _RecordCollector(logging.Handler):
    """Keep every record of one test, whichever phase logged it."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.NOTSET)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def ha_deprecation_log() -> Iterator[list[logging.LogRecord]]:
    """Fail any test in which Home Assistant reports a deprecated API used here.

    A handler of its own rather than `caplog`, whose `records` are scoped to the
    phase asking for them: read from a teardown it answers with the teardown's
    records and stays empty however loudly the test body was warned.

    Core keeps a process-wide set of the notices it has already emitted so a
    running instance is not flooded; cleared here so every test reports
    independently and a failure names each call site, not only the run's first.
    """
    records: list[logging.LogRecord] = []
    handler = _RecordCollector(records)
    root = logging.getLogger()
    root.addHandler(handler)
    frame._REPORTED_INTEGRATIONS.clear()
    try:
        yield records
    finally:
        root.removeHandler(handler)
    reported = ha_deprecation_reports(records)
    assert not reported, "Home Assistant reports deprecated API usage:\n" + "\n".join(reported)


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Load the custom component for every test in this suite."""
    return None


@pytest.fixture
def gateway_models() -> dict[str, Any]:
    device_payload = _load("stat_device.json")
    gateway = next(d for d in device_payload["data"] if d.get("type") == "udm")
    return {
        "device": Device.from_api(gateway),
        "health": Health.from_api(_load("stat_health.json")["data"]),
        "sysinfo": SysInfo.from_api(_load("stat_sysinfo.json")["data"]),
        "identity": SystemIdentity.from_api(_load("api_system.json")),
    }


@pytest.fixture
def mock_client(gateway_models: dict[str, Any]) -> AsyncMock:
    """A GatewayClient mock returning canned models."""
    client = AsyncMock()
    client.async_prepare = AsyncMock(return_value=None)
    client.get_identity = AsyncMock(return_value=gateway_models["identity"])
    client.get_device = AsyncMock(return_value=gateway_models["device"])
    client.get_health = AsyncMock(return_value=gateway_models["health"])
    client.get_sysinfo = AsyncMock(return_value=gateway_models["sysinfo"])
    client.close = AsyncMock(return_value=None)
    return client


PINNED_FINGERPRINT = "ab:" * 31 + "ab"


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """An entry that pins the gateway's certificate — the shape new setups get."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="aa:bb:cc:00:11:22",
        title="UCG Fiber (192.0.2.10)",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 443,
            CONF_SITE: "default",
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: PINNED_FINGERPRINT,
            CONF_AUTH_METHOD: AUTH_API_KEY,
            CONF_API_KEY: "test-key",
        },
    )


@pytest.fixture
def legacy_config_entry() -> MockConfigEntry:
    """An entry created before pinning existed: verify_ssl only, and it was off.

    Kept as its own fixture rather than mutated in place, because the migration
    it exercises is a property of entries already on disk.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="aa:bb:cc:00:11:22",
        title="UCG Fiber (192.0.2.10)",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 443,
            CONF_SITE: "default",
            CONF_VERIFY_SSL: False,
            CONF_AUTH_METHOD: AUTH_API_KEY,
            CONF_API_KEY: "test-key",
        },
    )
