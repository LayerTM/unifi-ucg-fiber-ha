"""The models against a UCG-Fiber on UniFi OS 6.0.17 / Network 11.0.102.

Network 11 moved its database to PostgreSQL, replaced the statistics engine and
cleared the statistics history. The fixtures under ``fixtures/network_11`` keep
the keys of the earlier UniFi OS 5.1 fixtures (all but the previous Network
version) as a gateway on the new firmware reports them, with synthetic values,
so these tests prove that every field the library reads is still there and still
parses into a value the sensors can show.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aiounifigw.models import Dashboard, Device, Health, SysInfo, SystemIdentity

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
    assert device.cpu_percent == 25.0
    assert device.memory_percent == 60.0
    assert device.memory_total == 3000000000
    assert {t.name: t.value for t in device.temperatures} == {
        "Local": 46.0,
        "CPU": 51.0,
        "PMIC": 54.0,
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
    assert (primary.availability, primary.latency_ms, primary.uptime_s) == (100.0, 20, 172000)
    assert (backup.availability, backup.latency_ms, backup.uptime_s) == (100.0, 35, 7200)


def test_wan_download_is_received_traffic(device: Device) -> None:
    """Download is what the WAN port receives.

    UniFi OS 6.0.17 fixed Sent and Received being swapped in its own Traffic
    Info view. The counters this library reads are the WAN port's own: received
    is download, and on a home uplink it is the larger total by far.
    """
    primary = device.wans[0]
    assert primary.rx_bytes == 1000000000000
    assert primary.tx_bytes == 50000000000
    assert primary.rx_bytes > 10 * primary.tx_bytes
    assert (primary.rx_rate_bps, primary.tx_rate_bps) == (250000, 50000)


def test_health_and_speedtest() -> None:
    health = Health.from_api(_load("stat_health.json")["data"])
    assert health.internet_status == "ok"
    assert health.wan_status == "ok"
    assert health.internet_latency_ms == 25
    test = health.speedtest
    assert test.status == "Success"
    assert (test.download_mbps, test.upload_mbps, test.ping_ms) == (400.0, 40.0, 25)
    assert test.last_run == datetime.fromtimestamp(1795000000, UTC)


def test_identity() -> None:
    identity = SystemIdentity.from_api(_load("api_system.json"))
    assert identity.model_shortname == "UCGF"
    assert identity.has_internet is True


def test_ips_rule_set(device: Device) -> None:
    """The threat-detection rule set: count and update time (sent in milliseconds)."""
    assert device.ips is not None
    assert device.ips.rule_count == 31000
    assert device.ips.updated == datetime.fromtimestamp(1790000000, UTC)
    assert device.ips.signature_type == "ET"
    assert device.ips.activating is False


def test_speedtest_names_the_wan_it_measured(device: Device) -> None:
    """Since Network 10.6 a speedtest may run on a WAN that is not the active one."""
    assert device.speedtest_ifname == "eth3"
    assert device.speedtest_wan is not None
    assert device.speedtest_wan.id == "WAN2"
    assert device.active_wan is not None
    assert device.active_wan.id == "WAN"


def test_dashboard_wan_quality_uses_the_last_complete_interval() -> None:
    """The newest five-minute interval is still filling, so the one before is used."""
    dashboard = Dashboard.from_api(_load("aggregated_dashboard.json"))
    primary = dashboard.wan_quality["WAN"]
    assert primary.interval_start == datetime.fromtimestamp(1795000300, UTC)
    assert primary.packet_loss_pct == 1.5
    assert (primary.latency_min_ms, primary.latency_avg_ms, primary.latency_max_ms) == (
        12.0,
        25.0,
        50.0,
    )
    assert dashboard.wan_quality["WAN2"].packet_loss_pct == 0.0


def test_dashboard_threat_detection() -> None:
    threat = Dashboard.from_api(_load("aggregated_dashboard.json")).threat_detection
    assert threat is not None
    assert (threat.enabled, threat.activating, threat.signatures, threat.threats) == (
        True,
        False,
        31000,
        2,
    )
    assert threat.rules_missing is False


def test_console_backup_from_the_session_payload() -> None:
    """The console's own schedule is only in the payload a session receives."""
    backup = SystemIdentity.from_api(_load("api_system_session.json")).backup
    assert backup is not None
    assert (backup.enabled, backup.frequency, backup.day_of_week, backup.hour) == (
        True,
        "weekly",
        3,
        2,
    )
    assert (backup.local_retention, backup.destinations) == (5, ("local",))
    assert SystemIdentity.from_api(_load("api_system.json")).backup is None
