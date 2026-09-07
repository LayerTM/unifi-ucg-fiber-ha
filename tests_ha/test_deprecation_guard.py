"""The guard that keeps this integration off deprecated Home Assistant APIs.

`conftest.ha_deprecation_log` fails any test in which core reports a deprecated
API used here. A guard is a claim about what it can see, so this module checks
both halves of that claim: that it fires on a real report, and that the
sentences it watches for are still the ones core writes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.unifi_gateway_rest.aiounifigw import Capabilities
from custom_components.unifi_gateway_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import _DEPRECATION_SENTENCES, ha_deprecation_reports

# Each sentence the guard matches, against the format string core builds it
# from. Core rewording one is how this guard would go blind: it would keep
# passing while seeing nothing, which is indistinguishable from clean code.
_CORE_FORMATS = {
    "Detected that custom integration": ("helpers/frame.py", "Detected that %sintegration"),
    "The deprecated ": ("helpers/deprecation.py", "The deprecated %s %s was"),
    "is deprecated. Please rename": ("helpers/deprecation.py", "is deprecated. Please rename"),
}


def test_watched_sentences_are_still_the_ones_core_writes() -> None:
    """Every sentence the guard looks for is still built by core."""
    core = Path(frame.__file__).parents[1]
    assert set(_CORE_FORMATS) == set(_DEPRECATION_SENTENCES), (
        "a watched sentence has no known origin in core; add it to _CORE_FORMATS"
    )
    for sentence, (relative, fmt) in _CORE_FORMATS.items():
        source = (core / relative).read_text(encoding="utf-8")
        assert fmt in source, f"core no longer builds {sentence!r} — the guard is now blind"


async def test_guard_sees_a_real_deprecation_report(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    ha_deprecation_log: list[logging.LogRecord],
) -> None:
    """A genuine core deprecation report about this integration is detected."""
    config_entry.add_to_hass(hass)
    with _patch_client(mock_client):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    frame.report_usage(
        "used an API deprecated for the purpose of this test",
        breaks_in_ha_version="2027.8",
        integration_domain=DOMAIN,
    )

    reported = ha_deprecation_reports(ha_deprecation_log)
    assert reported, "the guard did not see a report core had just logged"
    assert any(DOMAIN in line for line in reported)

    # Proven; cleared so the autouse guard does not fail this test on its own proof.
    ha_deprecation_log.clear()


def test_guard_stays_silent_on_unrelated_warnings() -> None:
    """Warnings that are neither deprecations nor ours do not trip the guard."""
    unrelated = [
        _record(logging.WARNING, "homeassistant.core", f"Something slow in {DOMAIN}"),
        _record(logging.WARNING, "aiohttp.client", "The deprecated thing was used from elsewhere"),
        _record(
            logging.INFO,
            "homeassistant.helpers.frame",
            f"Detected that custom integration '{DOMAIN}' did",
        ),
    ]
    assert ha_deprecation_reports(unrelated) == []


def _patch_client(client: AsyncMock) -> Any:
    return patch.multiple(
        "custom_components.unifi_gateway_rest",
        GatewayClient=lambda *a, **k: client,
        probe=AsyncMock(return_value=Capabilities(device=True, health=True, sysinfo=True)),
    )


def _record(level: int, name: str, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 0, message, None, None)
