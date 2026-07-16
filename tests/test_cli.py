"""Tests for the CLI and its shared summary helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from aiounifigw import summary
from aiounifigw.auth import ApiKeyAuth, SessionAuth
from aiounifigw.cli import app
from aiounifigw.models import Device, Health, SysInfo

runner = CliRunner()


def _models(stat_device, stat_health, stat_sysinfo):  # type: ignore[no-untyped-def]
    gw = next(d for d in stat_device["data"] if d.get("type") == "udm")
    return (
        Device.from_api(gw),
        Health.from_api(stat_health["data"]),
        SysInfo.from_api(stat_sysinfo["data"]),
    )


def test_status_payload_shape(stat_device, stat_health, stat_sysinfo) -> None:  # type: ignore[no-untyped-def]
    device, health, sysinfo = _models(stat_device, stat_health, stat_sysinfo)
    payload = summary.status_payload(device, health, sysinfo)
    assert payload["console"]["model"] == "UDMA6A8"
    assert payload["internet"]["isp"] == "Example ISP"
    assert payload["active_wan"] == "WAN"
    assert payload["failover_active"] is False
    assert [w["id"] for w in payload["wans"]] == ["WAN", "WAN2"]
    assert payload["sfp_ports"][0]["part"] == "DAC-SFP10-1M"


def test_env_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFI_GW_HOST", raising=False)
    with pytest.raises(ValueError, match="UNIFI_GW_HOST"):
        summary.env_host()
    monkeypatch.setenv("UNIFI_GW_HOST", "gw.local")
    assert summary.env_host() == "gw.local"

    monkeypatch.delenv("UNIFI_GW_APIKEY", raising=False)
    monkeypatch.delenv("UNIFI_GW_USER", raising=False)
    monkeypatch.delenv("UNIFI_GW_PASS", raising=False)
    with pytest.raises(ValueError, match="APIKEY"):
        summary.env_auth()
    monkeypatch.setenv("UNIFI_GW_APIKEY", "k")
    assert isinstance(summary.env_auth(), ApiKeyAuth)
    monkeypatch.delenv("UNIFI_GW_APIKEY")
    monkeypatch.setenv("UNIFI_GW_USER", "admin")
    monkeypatch.setenv("UNIFI_GW_PASS", "pw")
    assert isinstance(summary.env_auth(), SessionAuth)

    monkeypatch.setenv("UNIFI_GW_VERIFY_SSL", "yes")
    assert summary.env_verify_ssl() is True
    monkeypatch.setenv("UNIFI_GW_VERIFY_SSL", "0")
    assert summary.env_verify_ssl() is False
    monkeypatch.setenv("UNIFI_GW_SITE", "branch")
    assert summary.env_site() == "branch"


def _patch_read(models: tuple[Any, Any, Any]) -> Any:
    return patch.multiple(
        "aiounifigw.cli",
        make_client=lambda _session: object(),
        read_all=AsyncMock(return_value=models),
    )


def test_cli_status_json(stat_device, stat_health, stat_sysinfo) -> None:  # type: ignore[no-untyped-def]
    with _patch_read(_models(stat_device, stat_health, stat_sysinfo)):
        result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0
    assert "UDMA6A8" in result.stdout
    assert "Example ISP" in result.stdout


def test_cli_status_table(stat_device, stat_health, stat_sysinfo) -> None:  # type: ignore[no-untyped-def]
    with _patch_read(_models(stat_device, stat_health, stat_sysinfo)):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "WAN uplinks" in result.stdout
    assert "Active WAN" in result.stdout


def test_cli_speedtest_confirmed() -> None:
    action = AsyncMock()
    with patch("aiounifigw.cli.make_action_client", return_value=action):
        result = runner.invoke(app, ["speedtest", "--yes"])
    assert result.exit_code == 0
    action.run_speedtest.assert_awaited_once()


def test_cli_speedtest_aborts_without_yes() -> None:
    with patch("aiounifigw.cli.make_action_client") as m:
        result = runner.invoke(app, ["speedtest"], input="n\n")
    assert result.exit_code != 0
    m.assert_not_called()
