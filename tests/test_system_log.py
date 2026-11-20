"""System-log parsing, the search the client sends, and the cursor that reports each entry once."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from _fake import FakeSession
from aiounifigw import ApiKeyAuth, GatewayClient
from aiounifigw.const import SYSTEM_LOG_CATEGORIES
from aiounifigw.system_log import (
    INITIAL_LOOKBACK_MS,
    LOOKAHEAD_MS,
    MAX_PAGES,
    OVERLAP_MS,
    PAGE_SIZE,
    SystemLog,
    SystemLogCursor,
)

_FX = Path(__file__).parent / "fixtures" / "network_11" / "system_log.json"
URL = "https://gw.local/proxy/network/v2/api/site/default/system-log/all"
T = 1795000000000


def _payload() -> dict[str, Any]:
    return json.loads(_FX.read_text(encoding="utf-8"))


def _row(entry_id: str, ts: int) -> dict[str, Any]:
    return {"id": entry_id, "timestamp": ts, "category": "SECURITY", "event": "THREAT_BLOCKED"}


def _log(*rows: dict[str, Any]) -> SystemLog:
    return SystemLog.from_api({"data": list(rows)})


def test_entries_are_rendered_from_their_templates() -> None:
    log = SystemLog.from_api(_payload())
    assert log.total == 3
    assert [e.event for e in log.entries] == ["THREAT_BLOCKED", "ISP_HIGH_LATENCY", "ADMIN_ACCESS"]
    latency = log.entries[1]
    assert latency.title == "WAN1 High Latency Detected"
    assert latency.message == (
        "Internet connection WAN1 Example ISP on port 5 is experiencing high latency."
    )
    assert (latency.category, latency.severity) == ("INTERNET_AND_WAN", "MEDIUM")
    assert latency.occurred.timestamp() == (T + 60000) / 1000


def test_a_placeholder_without_a_parameter_is_kept() -> None:
    entry = SystemLog.from_api(
        {"data": [{**_row("a", T), "message_raw": "{GONE} left", "parameters": {"GONE": "x"}}]}
    ).entries[0]
    assert entry.message == "{GONE} left"


@pytest.mark.parametrize(
    "row",
    [
        {"timestamp": T},
        {"id": "a"},
        {"id": "a", "timestamp": True},
        {"id": "", "timestamp": T},
        "x",
    ],
)
def test_an_entry_without_id_or_time_is_dropped(row: Any) -> None:
    assert SystemLog.from_api({"data": [row]}).entries == ()


@pytest.mark.parametrize("payload", [None, [], {}, {"data": "x"}])
def test_a_malformed_page_is_empty(payload: Any) -> None:
    log = SystemLog.from_api(payload)
    assert (log.entries, log.total) == ((), 0)


def test_entries_are_ordered_newest_first() -> None:
    log = _log(_row("old", T), _row("new", T + 1))
    assert [e.id for e in log.entries] == ["new", "old"]


def test_the_first_poll_replays_nothing() -> None:
    cursor = SystemLogCursor()
    assert cursor.window(T) == (T - INITIAL_LOOKBACK_MS, T + LOOKAHEAD_MS)
    assert cursor.advance(_log(_row("a", T - 10), _row("b", T - 5))) == ()


def test_each_entry_is_reported_once_oldest_first() -> None:
    cursor = SystemLogCursor()
    cursor.advance(_log(_row("a", T)))
    assert cursor.window(T + 99) == (T - OVERLAP_MS, T + 99 + LOOKAHEAD_MS)

    fresh = cursor.advance(_log(_row("c", T + 20), _row("b", T + 10), _row("a", T)))
    assert [e.id for e in fresh] == ["b", "c"]
    # the overlapping window returns them again: nothing is reported twice
    assert cursor.advance(_log(_row("c", T + 20), _row("b", T + 10))) == ()
    assert cursor.window(T + 999)[0] == T + 20 - OVERLAP_MS


def test_an_empty_first_poll_still_starts_the_cursor() -> None:
    cursor = SystemLogCursor()
    assert cursor.advance(_log()) == ()
    assert [e.id for e in cursor.advance(_log(_row("a", T)))] == ["a"]


def test_entries_older_than_the_window_are_forgotten() -> None:
    cursor = SystemLogCursor()
    cursor.advance(_log(_row("a", T)))
    cursor.advance(_log(_row("z", T + 2 * OVERLAP_MS)))
    # "a" fell out of the window, so a console replaying it would report it anew
    assert [e.id for e in cursor.advance(_log(_row("a", T)))] == ["a"]


async def test_the_client_sends_a_read_query() -> None:
    s = FakeSession()
    s.add("POST", URL, payload=_payload())
    client = GatewayClient(s, "gw.local", ApiKeyAuth("k"), ssl=False)  # type: ignore[arg-type]
    log = await client.get_system_log(T, T + 60000)
    assert len(log.entries) == 3
    method, url, kwargs = s.requests[-1]
    assert (method, url) == ("POST", URL)
    assert kwargs["json"] == {
        "timestampFrom": T,
        "timestampTo": T + 60000,
        "pageNumber": 0,
        "pageSize": PAGE_SIZE,
        "categories": list(SYSTEM_LOG_CATEGORIES),
    }
    assert "CLIENT_DEVICES" not in kwargs["json"]["categories"]


def _page_payload(ids: range, total: int) -> dict[str, Any]:
    return {"data": [_row(f"e{i}", T + i) for i in reversed(ids)], "total_element_count": total}


async def test_a_window_is_read_page_by_page_and_reported_once() -> None:
    """250 entries over three pages: every one is reported once, oldest first."""
    s = FakeSession()
    for ids in (range(150, 250), range(50, 150), range(0, 50)):  # newest page first
        s.add("POST", URL, payload=_page_payload(ids, 250))
    client = GatewayClient(s, "gw.local", ApiKeyAuth("k"), ssl=False)  # type: ignore[arg-type]

    cursor = SystemLogCursor()
    cursor.advance(_log())  # started before the burst
    log = await client.get_system_log_window(T, T + 1000)
    assert [r[2]["json"]["pageNumber"] for r in s.requests] == [0, 1, 2]
    fresh = cursor.advance(log)
    assert [e.id for e in fresh] == [f"e{i}" for i in range(250)]
    assert cursor.advance(log) == ()


async def test_past_the_page_cap_the_newest_are_kept_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    s = FakeSession()
    for page in range(MAX_PAGES):
        top = 700 - page * PAGE_SIZE
        s.add("POST", URL, payload=_page_payload(range(top - PAGE_SIZE, top), 700))
    client = GatewayClient(s, "gw.local", ApiKeyAuth("k"), ssl=False)  # type: ignore[arg-type]

    cursor = SystemLogCursor()
    cursor.advance(_log())
    log = await client.get_system_log_window(T, T + 1000)
    assert len(s.requests) == MAX_PAGES
    with caplog.at_level(logging.WARNING, logger="aiounifigw.system_log"):
        fresh = cursor.advance(log)
    assert [e.id for e in fresh] == [f"e{i}" for i in range(200, 700)]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage().startswith("200 older system-log entries")


async def test_a_short_window_reads_one_page() -> None:
    s = FakeSession()
    s.add("POST", URL, payload=_page_payload(range(3), 3))
    client = GatewayClient(s, "gw.local", ApiKeyAuth("k"), ssl=False)  # type: ignore[arg-type]
    assert len((await client.get_system_log_window(T, T + 1)).entries) == 3
    assert len(s.requests) == 1


def test_an_entry_on_two_pages_is_kept_once() -> None:
    merged = SystemLog.merged([_log(_row("b", T + 1), _row("a", T)), _log(_row("a", T))])
    assert [e.id for e in merged.entries] == ["b", "a"]
