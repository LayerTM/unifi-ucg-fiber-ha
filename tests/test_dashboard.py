"""The v2 site dashboard: interval choice, threat state and absent widgets."""

from __future__ import annotations

from typing import Any

import pytest

from aiounifigw.models import Dashboard, ThreatDetection


def _row(ts: int, loss: float) -> dict[str, Any]:
    return {"timestamp": ts, "avg_packet_loss_pct": loss, "max_latency_ms": 40.0}


def _dash(history: list[dict[str, Any]], end: int | None) -> Dashboard:
    meta = {"end_timestamp": end} if end is not None else {}
    return Dashboard.from_api(
        {
            "dashboard_meta": meta,
            "wan_activity": {"activity_by_network_group": {"WAN": {"history": history}}},
        }
    )


@pytest.mark.parametrize(
    ("history", "end", "loss"),
    [
        # newest interval still running -> the one before it
        ([_row(0, 1.0), _row(300_000, 5.0)], 400_000, 1.0),
        # newest interval complete -> it
        ([_row(0, 1.0), _row(300_000, 5.0)], 600_000, 5.0),
        # unordered input is ordered by time first
        ([_row(300_000, 5.0), _row(0, 1.0)], 400_000, 1.0),
        # a single interval is all there is
        ([_row(0, 2.0)], 100_000, 2.0),
        # no end time reported -> the newest
        ([_row(0, 1.0), _row(300_000, 5.0)], None, 5.0),
    ],
)
def test_interval_choice(history: list[dict[str, Any]], end: int | None, loss: float) -> None:
    assert _dash(history, end).wan_quality["WAN"].packet_loss_pct == loss


def test_wan_without_samples_is_left_out() -> None:
    assert _dash([{"avg_packet_loss_pct": 1.0}], 1).wan_quality == {}
    assert _dash([], 1).wan_quality == {}


@pytest.mark.parametrize("payload", [None, [], {}, {"wan_activity": "x", "cybersecure": 1}])
def test_malformed_payload_degrades_to_empty(payload: Any) -> None:
    dashboard = Dashboard.from_api(payload)
    assert dashboard.wan_quality == {}
    assert dashboard.threat_detection is None


@pytest.mark.parametrize(
    ("enabled", "activating", "signatures", "missing"),
    [
        (True, False, 0, True),
        (True, True, 0, False),  # a new rule set is being applied
        (False, False, 0, False),  # threat detection is off
        (True, False, 31000, False),
        (True, False, None, False),  # count not reported
    ],
)
def test_rules_missing(
    enabled: bool, activating: bool, signatures: int | None, missing: bool
) -> None:
    threat = ThreatDetection.from_api(
        {"ips_enabled": enabled, "is_activating": activating, "signatures": signatures}
    )
    assert threat.rules_missing is missing
