"""Shared fixtures for the Home Assistant integration test-suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from custom_components.unifi_gateway_rest.aiounifigw import (
    Device,
    Health,
    SysInfo,
    SystemIdentity,
)
from custom_components.unifi_gateway_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_SITE,
    DOMAIN,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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


@pytest.fixture
def config_entry() -> MockConfigEntry:
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
