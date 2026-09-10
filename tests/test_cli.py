"""Tests for the CLI and its shared summary helpers."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from typer.testing import CliRunner

from _fake import TlsServer
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
    assert {p["port"] for p in payload["sfp_ports"]} == {6, 7}
    assert any(p["part"] == "DAC-SFP10-1M" for p in payload["sfp_ports"])


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

    monkeypatch.setenv("UNIFI_GW_SITE", "branch")
    assert summary.env_site() == "branch"
    monkeypatch.setenv("UNIFI_GW_PORT", "8443")
    assert summary.env_port() == 8443


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


# --- TLS trust for the developer tools, and the command that shows a fingerprint


def test_ssl_from_env_pins_when_a_fingerprint_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_GW_CERT_FINGERPRINT", "aa:" * 31 + "aa")
    monkeypatch.delenv("UNIFI_GW_VERIFY_SSL", raising=False)
    assert isinstance(summary.ssl_from_env(), aiohttp.Fingerprint)


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_ssl_from_env_verifies_against_the_ca_store(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.delenv("UNIFI_GW_CERT_FINGERPRINT", raising=False)
    monkeypatch.setenv("UNIFI_GW_VERIFY_SSL", value)
    assert summary.ssl_from_env() is True


def test_ssl_from_env_defaults_to_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Documented rather than accidental: these are developer tools."""
    monkeypatch.delenv("UNIFI_GW_CERT_FINGERPRINT", raising=False)
    monkeypatch.delenv("UNIFI_GW_VERIFY_SSL", raising=False)
    assert summary.ssl_from_env() is False


def test_a_pinned_fingerprint_wins_over_ca_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both set is not ambiguous: the specific certificate is the stronger claim."""
    monkeypatch.setenv("UNIFI_GW_CERT_FINGERPRINT", "aa:" * 31 + "aa")
    monkeypatch.setenv("UNIFI_GW_VERIFY_SSL", "1")
    assert isinstance(summary.ssl_from_env(), aiohttp.Fingerprint)


async def test_the_cli_prints_the_fingerprint_it_tells_people_to_compare(
    tls_server: TlsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The README sends people to this command, so it has to print the value.

    Against the generated certificate, what it prints must equal what the pinning
    path would accept — otherwise the instruction sends them to compare the wrong
    number.
    """
    monkeypatch.setenv("UNIFI_GW_HOST", "127.0.0.1")
    monkeypatch.setenv("UNIFI_GW_PORT", str(tls_server.port))
    # The command calls asyncio.run(), which cannot run inside this test's loop —
    # and a RuntimeError from that would look exactly like a failed connection.
    result = await asyncio.to_thread(CliRunner().invoke, app, ["fingerprint"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == tls_server.fingerprint


async def test_the_cli_fingerprint_reports_an_unreachable_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFI_GW_HOST", "127.0.0.1")
    monkeypatch.setenv("UNIFI_GW_PORT", "9")
    result = await asyncio.to_thread(CliRunner().invoke, app, ["fingerprint"])
    assert result.exit_code == 1
    # Exit 1 must come from the unreachable console, not from a broken harness.
    assert "could not read the certificate" in result.output


def test_a_failing_command_reports_on_stderr_not_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """README says `export VAR=$(unifi-gateway fingerprint)`.

    That idiom captures stdout and always exits 0, so an error printed to stdout
    would be exported as the fingerprint — and then pinned.
    """
    monkeypatch.setenv("UNIFI_GW_HOST", "127.0.0.1")
    monkeypatch.setenv("UNIFI_GW_PORT", "9")
    result = CliRunner().invoke(app, ["fingerprint"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "could not read the certificate" in result.stderr


def test_an_unusable_pinned_fingerprint_is_named_not_traced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed UNIFI_GW_CERT_FINGERPRINT is a user's typo, not a crash."""
    monkeypatch.setenv("UNIFI_GW_HOST", "127.0.0.1")
    monkeypatch.setenv("UNIFI_GW_APIKEY", "k")
    monkeypatch.setenv("UNIFI_GW_CERT_FINGERPRINT", "could not read the certificate")
    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 1
    assert "not a hex fingerprint" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_missing_host_is_named_not_traced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFI_GW_HOST", raising=False)
    result = CliRunner().invoke(app, ["fingerprint"])
    assert result.exit_code == 1
    assert "set UNIFI_GW_HOST" in result.stderr
