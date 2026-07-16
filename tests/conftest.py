"""Shared fixtures for the aiounifigw test-suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def stat_device() -> dict[str, Any]:
    return _load("stat_device.json")


@pytest.fixture
def stat_health() -> dict[str, Any]:
    return _load("stat_health.json")


@pytest.fixture
def stat_sysinfo() -> dict[str, Any]:
    return _load("stat_sysinfo.json")


@pytest.fixture
def api_system() -> dict[str, Any]:
    return _load("api_system.json")
