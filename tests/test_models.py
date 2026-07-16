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
    assert d.num_clients == 51
    assert d.cpu_percent == 20.9
    assert d.memory_percent == 74.8
    assert d.loadavg_1 == 1.99
    assert d.loadavg_15 == 2.77
    assert d.overheating is False


def test_device_temperatures(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    names = {t.name: t.value for t in d.temperatures}
    assert names == {"Local": 47.25, "CPU": 51.312, "PMIC": 55.812}


def test_device_storage(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    persistent = d.persistent_storage
    assert persistent is not None
    assert persistent.type == "eMMC"
    assert persistent.usage_percent == pytest.approx(17.3, abs=0.1)
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
    assert wan1.latency_ms == 27
    assert wan1.availability == 100.0
    assert wan1.uptime_s == 33423
    assert wan1.rx_rate_bps == 47835
    assert wan1.tx_rate_bps == 291538
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


def test_device_sfp_only_present_modules(stat_device: dict[str, Any]) -> None:
    d = Device.from_api(_gateway(stat_device))
    # port 6 has an empty cage (no module) -> skipped; port 7 has a DAC.
    assert [p.port_idx for p in d.sfp_ports] == [7]
    sfp = d.sfp_ports[0]
    assert sfp.present is True
    assert sfp.vendor == "Ubiquiti Inc."
    assert sfp.part == "DAC-SFP10-1M"
    assert sfp.rx_los is False
    assert sfp.tx_fault is False
    assert sfp.has_problem is False


def test_sfp_problem_detection(stat_device: dict[str, Any]) -> None:
    gw = _gateway(stat_device)
    gw["port_table"][1]["sfp_rx_los"] = True
    d = Device.from_api(gw)
    assert d.sfp_ports[0].has_problem is True


def test_device_uptime_since_uses_now(monkeypatch: pytest.MonkeyPatch, stat_device: dict) -> None:
    monkeypatch.setattr(models, "_now", lambda: 1_000_000.0)
    d = Device.from_api(_gateway(stat_device))
    expected = datetime.fromtimestamp(1_000_000 - 33507, tz=UTC)
    assert d.uptime_since == expected


def test_health_fields(stat_health: dict[str, Any]) -> None:
    h = Health.from_api(stat_health["data"])
    assert h.internet_up is True
    assert h.internet_status == "ok"
    assert h.internet_latency_ms == 37
    assert h.wan_status == "ok"
    assert h.isp.name == "Example ISP"
    assert h.isp.organization == "Example ISP"
    assert h.isp.asn == 64512
    assert h.isp.asn_label == "AS64512"
    assert h.num_wired == 26
    assert h.num_wireless == 27
    assert h.num_ap == 4
    assert h.num_switch == 5


def test_health_speedtest_idle(stat_health: dict[str, Any]) -> None:
    st = Health.from_api(stat_health["data"]).speedtest
    assert st.status == "Idle"
    assert st.in_progress is False
    assert st.last_run is None  # lastrun == 0 -> never
    assert st.ping_ms == 0


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
    assert st.download_mbps == 934.2
    assert st.upload_mbps == 221.8
    assert st.last_run == datetime.fromtimestamp(1_700_000_000, tz=UTC)


def test_health_speedtest_running() -> None:
    assert models.Speedtest.from_api({"speedtest_status": "Running"}).in_progress is True


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
