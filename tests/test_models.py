"""Tests for the typed models against sanitized fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aiounifigw import models
from aiounifigw.models import Device, Health, SysInfo, SystemIdentity


def _gateway(stat_device: dict[str, Any]) -> dict[str, Any]:
    return next(d for d in stat_device["data"] if d.get("type") == "udm")


def test_device_core_fields(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    assert d.model == "UDMA6A8"
    assert d.type == "udm"
    assert d.name == "UCG Fiber"
    assert d.firmware_version == "5.1.19.33549"
    assert d.online is True
    assert d.num_clients == 40
    assert d.cpu_percent == 20.0
    assert d.memory_percent == 50.0
    assert d.loadavg_1 == 1.5
    assert d.loadavg_15 == 2.5
    assert d.overheating is False


def test_device_temperatures(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    names = {t.name: t.value for t in d.temperatures}
    assert names == {"Local": 45.0, "CPU": 50.0, "PMIC": 55.0}


def test_device_storage(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    persistent = d.persistent_storage
    assert persistent is not None
    assert persistent.type == "eMMC"
    assert persistent.usage_percent == pytest.approx(20.0, abs=0.1)
    assert persistent.available == persistent.size - persistent.used


def test_device_wans(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    assert [w.id for w in d.wans] == ["WAN", "WAN2"]
    wan1 = d.wans[0]
    assert wan1.up is True
    assert wan1.is_active is True
    assert wan1.media == "2.5GE"
    assert wan1.speed == 2500
    assert wan1.max_speed == 10000
    # latency/availability/uptime come from uptime_stats, not the wan block
    assert wan1.latency_ms == 20
    assert wan1.availability == 100.0
    assert wan1.uptime_s == 86000
    assert wan1.rx_rate_bps == 125000
    assert wan1.tx_rate_bps == 25000
    assert d.active_wan is wan1
    assert d.failover_active is False


def test_device_failover_when_backup_active(stat_device: dict[str, Any]) -> None:
    gw = _gateway(stat_device)
    gw["wan1"]["is_uplink"] = False
    gw["wan2"]["is_uplink"] = True
    d = Device.from_api(gw)
    assert d.active_wan is not None
    assert d.active_wan.id == "WAN2"
    assert d.failover_active is True


def test_device_sfp_both_ports(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    # both physical SFP+ ports are surfaced; port 6 is empty, port 7 has a DAC.
    assert [p.port_idx for p in d.sfp_ports] == [6, 7]
    empty = d.sfp_ports[0]
    assert empty.present is False
    assert empty.part == ""
    assert empty.has_problem is False
    module = d.sfp_ports[1]
    assert module.present is True
    assert module.vendor == "Ubiquiti Inc."
    assert module.part == "DAC-SFP10-1M"
    assert module.rx_los is False
    assert module.tx_fault is False
    assert module.has_problem is False


def test_sfp_problem_detection(stat_device: dict[str, Any]) -> None:
    gw = _gateway(stat_device)
    gw["port_table"][1]["sfp_rx_los"] = True  # port 7 (the populated one)
    d = Device.from_api(gw)
    port7 = next(p for p in d.sfp_ports if p.port_idx == 7)
    assert port7.has_problem is True
    # an empty port never reports a problem
    port6 = next(p for p in d.sfp_ports if p.port_idx == 6)
    assert port6.has_problem is False


def test_device_uptime_since_uses_now(monkeypatch: pytest.MonkeyPatch, stat_device: dict) -> None:
    monkeypatch.setattr(models, "_now", lambda: 1_000_000.0)
    d = Device.from_api(_gateway(stat_device))
    expected = datetime.fromtimestamp(1_000_000 - 86400, tz=UTC)
    assert d.uptime_since == expected


def test_health_fields(stat_health: dict[str, Any]) -> None:
    h = Health.from_api(stat_health["data"])
    assert h.internet_up is True
    assert h.internet_status == "ok"
    assert h.internet_latency_ms == 25
    assert h.wan_status == "ok"
    assert h.isp.name == "Example ISP"
    assert h.isp.organization == "Example ISP"
    assert h.isp.asn == 64512
    assert h.isp.asn_label == "AS64512"
    assert h.num_wired == 20
    assert h.num_wireless == 20
    assert h.num_guest == 0
    assert h.num_iot == 5
    assert h.num_ap == 4
    assert h.num_switch == 4


def test_health_speedtest_idle(stat_health: dict[str, Any]) -> None:
    st = Health.from_api(stat_health["data"]).speedtest
    assert st.status == "Idle"
    assert st.last_run is None  # lastrun == 0 -> never
    # The gateway reports zeros after a restart; they are not a measurement.
    assert st.download_mbps is None
    assert st.upload_mbps is None
    assert st.ping_ms is None


def test_health_speedtest_completed() -> None:
    st = models.Speedtest.from_api(
        {
            "speedtest_status": "Success",
            "xput_down": 934.2,
            "xput_up": 221.8,
            "speedtest_ping": 6,
            "speedtest_lastrun": 1_700_000_000,
        }
    )
    assert st.status == "Success"
    assert st.download_mbps == 934.2
    assert st.upload_mbps == 221.8
    assert st.last_run == datetime.fromtimestamp(1_700_000_000, tz=UTC)


def test_vpn(stat_health: dict[str, Any]) -> None:
    vpn = Health.from_api(stat_health["data"]).vpn
    assert vpn.site_to_site_enabled is False
    assert vpn.remote_enabled is True
    assert vpn.remote_active == 2
    assert vpn.remote_inactive == 3


def test_health_empty_input() -> None:
    h = Health.from_api(None)
    assert h.internet_up is False
    assert h.isp.name == ""
    assert h.isp.asn is None
    assert h.isp.asn_label is None


def test_sysinfo(stat_sysinfo: dict[str, Any]) -> None:
    s = SysInfo.from_api(stat_sysinfo["data"])
    assert s.netapp_version == "10.5.62"
    assert s.name == "UCG Fiber"
    assert s.console_version == "5.1.19"
    assert s.previous_version == "10.5.54"
    assert s.update_available is False


def test_sysinfo_accepts_bare_dict(stat_sysinfo: dict[str, Any]) -> None:
    s = SysInfo.from_api(stat_sysinfo["data"][0])
    assert s.netapp_version == "10.5.62"


def test_system_identity(api_system: dict[str, Any]) -> None:
    ident = SystemIdentity.from_api(api_system)
    assert ident.mac == "aa:bb:cc:00:11:22"
    assert ident.name == "UCG Fiber"
    assert ident.model_shortname == "UCGF"
    assert ident.has_internet is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.99", 1.99), (5, 5.0), (True, 0.0), (None, 0.0), ("bad", 0.0)],
)
def test_float_coercion(raw: Any, expected: float) -> None:
    assert models._f(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5000", 5000), (-1, -1), (3.7, 3), (True, None), ("x", None), (None, None)],
)
def test_int_coercion(raw: Any, expected: int | None) -> None:
    assert models._i(raw) == expected


def test_epoch_and_uptime_edges() -> None:
    assert models._epoch(0) is None
    assert models._epoch(None) is None
    assert models._uptime(-1) is None
    assert models._uptime(None) is None


def test_ips_signatures_parsed(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    assert d.ips is not None
    assert d.ips.rule_count == 30000
    assert d.ips.updated == datetime.fromtimestamp(1780000000, UTC)


@pytest.mark.parametrize(
    ("raw", "count", "updated"),
    [
        ({"rule_count": 0, "update_time": 0}, 0, None),
        ({"rule_count": "12", "update_time": "1780000000500"}, 12, 1780000000.5),
        ({"rule_count": True, "update_time": None}, None, None),
    ],
)
def test_ips_signatures_edges(
    stat_device: dict[str, Any], raw: dict[str, Any], count: int | None, updated: float | None
) -> None:
    gw = {**_gateway(stat_device), "ids_ips_signature": raw}
    ips = Device.from_api(gw).ips
    assert ips is not None
    assert ips.rule_count == count
    assert ips.updated == (datetime.fromtimestamp(updated, UTC) if updated else None)
    assert ips.activating is False


def test_ips_absent_without_threat_detection(stat_device: dict[str, Any]) -> None:
    gw = {k: v for k, v in _gateway(stat_device).items() if k != "ids_ips_signature"}
    assert Device.from_api(gw).ips is None


def test_speedtest_wan_unknown_before_network_10_6(stat_device: dict[str, Any]) -> None:
    """Older firmware does not say which interface a speedtest used."""
    d = Device.from_api(_gateway(stat_device))
    assert d.speedtest_ifname == ""
    assert d.speedtest_wan is None


@pytest.mark.parametrize(("ifname", "wan_id"), [("eth0", "WAN"), ("eth3", "WAN2"), ("eth9", None)])
def test_speedtest_wan_resolves_by_interface(
    stat_device: dict[str, Any], ifname: str, wan_id: str | None
) -> None:
    gw = {**_gateway(stat_device), "speedtest-status": {"interface_name": ifname}}
    wan = Device.from_api(gw).speedtest_wan
    assert (wan.id if wan else None) == wan_id


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"backupSchedule": "x"}, None),
        ({"autoBackupEnabled": "yes", "backupSchedule": {}}, (False, "", None, ())),
        (
            {
                "autoBackupEnabled": True,
                "backupSchedule": {
                    "frequency": "MONTHLY",
                    "dayOfMonth": 28,
                    "destinations": [1, "cloud"],
                },
            },
            (True, "monthly", None, ("cloud",)),
        ),
    ],
)
def test_console_backup_edges(payload: dict[str, Any], expected: tuple[Any, ...] | None) -> None:
    backup = SystemIdentity.from_api(payload).backup
    if expected is None:
        assert backup is None
    else:
        assert backup is not None
        assert (backup.enabled, backup.frequency, backup.hour, backup.destinations) == expected
