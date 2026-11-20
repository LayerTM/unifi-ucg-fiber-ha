"""The models against a UCG-Fiber on UniFi OS 6.0.17 / Network 11.0.102.

Network 11 moved its database to PostgreSQL, replaced the statistics engine and
cleared the statistics history. The fixtures under ``fixtures/network_11`` keep
the keys of the earlier UniFi OS 5.1 fixtures (all but the previous Network
version), with the values a gateway on the new firmware returned, so these tests
prove two things: every field the
library reads is still there, and what the new statistics engine puts in it is
still a value the sensors can show.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aiounifigw.models import Device, Health, SysInfo, SystemIdentity

_FX = Path(__file__).parent / "fixtures" / "network_11"


def _load(name: str) -> Any:
    return json.loads((_FX / name).read_text(encoding="utf-8"))


@pytest.fixture
def device() -> Device:
    data = _load("stat_device.json")["data"]
    return Device.from_api(next(d for d in data if d.get("type") == "udm"))


def test_versions() -> None:
    sysinfo = SysInfo.from_api(_load("stat_sysinfo.json")["data"])
    assert sysinfo.netapp_version == "11.0.102"
    assert sysinfo.console_version == "6.0.17"


def test_console(device: Device) -> None:
    assert device.firmware_version == "6.0.17.36539"
    assert device.online is True
    assert device.cpu_percent == 24.5
    assert device.memory_percent == 66.6
    assert device.memory_total == 3027685376
    assert {t.name: t.value for t in device.temperatures} == {
        "Local": 46.062,
        "CPU": 50.187,
        "PMIC": 54.875,
    }
    assert [s.name for s in device.storage] == ["Backup", "Temporary"]


def test_wan_statistics_survive_the_new_engine(device: Device) -> None:
    """Availability, latency and uptime come from `uptime_stats`, which 11.0 rebuilt."""
    primary, backup = device.wans
    assert (primary.id, primary.is_active, backup.id, backup.is_active) == (
        "WAN",
        True,
        "WAN2",
        False,
    )
    for wan in device.wans:
        assert wan.availability is not None and 0.0 <= wan.availability <= 100.0
        assert wan.latency_ms is not None and 0 < wan.latency_ms < 1000
        assert wan.uptime_s is not None and wan.uptime_s > 0
    assert (primary.availability, primary.latency_ms, primary.uptime_s) == (100.0, 22, 634515)
    assert (backup.availability, backup.latency_ms, backup.uptime_s) == (100.0, 37, 14892)


def test_wan_download_is_received_traffic(device: Device) -> None:
    """Download is what the WAN port receives.

    UniFi OS 6.0.17 fixed Sent and Received being swapped in its own Traffic
    Info view. The counters this library reads keep their direction across that
    update: on a home uplink the received total is the larger one by far, and it
    is in the captures from both firmware generations. (The sent total here is
    the captured one divided by ten: at twelve digits the repository's secret
    scan cannot tell it from a bare hardware address. The captured ratio is 12.5.)
    """
    primary = device.wans[0]
    assert primary.rx_bytes == 1989173135933
    assert primary.tx_bytes == 15847907688
    assert primary.rx_bytes > 10 * primary.tx_bytes
    assert (primary.rx_rate_bps, primary.tx_rate_bps) == (257152, 51161)


def test_health_and_speedtest() -> None:
    health = Health.from_api(_load("stat_health.json")["data"])
    assert health.internet_status == "ok"
    assert health.wan_status == "ok"
    assert health.internet_latency_ms == 40
    test = health.speedtest
    assert test.status == "Success"
    assert (test.download_mbps, test.upload_mbps, test.ping_ms) == (30.0, 37.0, 28)
    assert test.last_run == datetime.fromtimestamp(1795111416, UTC)


def test_identity() -> None:
    identity = SystemIdentity.from_api(_load("api_system.json"))
    assert identity.model_shortname == "UCGF"
    assert identity.has_internet is True
