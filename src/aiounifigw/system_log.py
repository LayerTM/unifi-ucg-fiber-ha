"""The UniFi Network system log: entries, and a cursor that yields each one once.

The log is searched by time window; it has no "since this entry" query. Polling
it therefore means asking for a window that overlaps the previous one and
dropping what was already seen. :class:`SystemLogCursor` holds that state, so a
caller only asks it for the next window and hands back what the console said.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_PLACEHOLDER = re.compile(r"\{([A-Z0-9_]+)\}")

# How far back a window reaches before the newest entry already seen. The log is
# indexed by the console's clock; the overlap absorbs entries written late and
# a skew between the console and this host.
OVERLAP_MS = 5 * 60 * 1000
# On the first poll the cursor only learns where "now" is: nothing older than
# this is reported, so a restart never replays history.
INITIAL_LOOKBACK_MS = 60 * 60 * 1000
# How far past this host's clock a window reaches, for a console running ahead.
LOOKAHEAD_MS = 60 * 60 * 1000
PAGE_SIZE = 100


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _render(template: str, parameters: dict[str, Any]) -> str:
    """Fill ``{NAME}`` placeholders with each parameter's display name."""

    def name(match: re.Match[str]) -> str:
        param = parameters.get(match.group(1))
        shown = param.get("name") if isinstance(param, dict) else None
        return shown if isinstance(shown, str) and shown else match.group(0)

    return _PLACEHOLDER.sub(name, template)


@dataclass(frozen=True, slots=True)
class SystemLogEntry:
    """One system-log entry, its text rendered from the console's own template."""

    id: str
    timestamp_ms: int
    category: str  # e.g. "SECURITY", "INTERNET_AND_WAN"
    event: str  # e.g. "THREAT_BLOCKED", "ISP_HIGH_LATENCY"
    severity: str  # "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH"
    title: str
    message: str

    @property
    def occurred(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=UTC)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> SystemLogEntry | None:
        """Parse one entry; None when it lacks the id or time that identify it."""
        entry_id = _str(d.get("id"))
        ts = d.get("timestamp")
        if not entry_id or isinstance(ts, bool) or not isinstance(ts, int):
            return None
        params = d.get("parameters")
        params = params if isinstance(params, dict) else {}
        return cls(
            id=entry_id,
            timestamp_ms=ts,
            category=_str(d.get("category")),
            event=_str(d.get("event")),
            severity=_str(d.get("severity")),
            title=_render(_str(d.get("title_raw")), params),
            message=_render(_str(d.get("message_raw")), params),
        )


@dataclass(frozen=True, slots=True)
class SystemLog:
    """One page of a system-log search, newest first."""

    entries: tuple[SystemLogEntry, ...]
    total: int  # entries matching the search, across all pages

    @classmethod
    def from_api(cls, data: Any) -> SystemLog:
        d = data if isinstance(data, dict) else {}
        rows = d.get("data")
        parsed = (
            SystemLogEntry.from_api(r)
            for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict)
        )
        entries = sorted((e for e in parsed if e is not None), key=lambda e: -e.timestamp_ms)
        total = d.get("total_element_count")
        return cls(
            entries=tuple(entries),
            total=total if isinstance(total, int) and not isinstance(total, bool) else len(entries),
        )


@dataclass(slots=True)
class SystemLogCursor:
    """Yields every system-log entry once across overlapping polls."""

    _newest_ms: int | None = None
    _started: bool = False
    _seen: dict[str, int] = field(default_factory=dict)  # id -> timestamp_ms

    def window(self, now_ms: int) -> tuple[int, int]:
        """The ``(from, to)`` window, in epoch ms, to search next."""
        start = (
            self._newest_ms - OVERLAP_MS
            if self._newest_ms is not None
            else now_ms - INITIAL_LOOKBACK_MS
        )
        return start, now_ms + LOOKAHEAD_MS

    def advance(self, log: SystemLog) -> tuple[SystemLogEntry, ...]:
        """Record *log* and return its entries not reported before, oldest first.

        The first call reports nothing: it only fixes the starting point, so the
        history that existed before polling began is never replayed.
        """
        fresh = [e for e in log.entries if e.id not in self._seen]
        for entry in log.entries:
            self._seen[entry.id] = entry.timestamp_ms
        if log.entries:
            newest = log.entries[0].timestamp_ms
            self._newest_ms = newest if self._newest_ms is None else max(self._newest_ms, newest)
        if self._newest_ms is not None:
            floor = self._newest_ms - OVERLAP_MS
            self._seen = {i: ts for i, ts in self._seen.items() if ts >= floor}
        if not self._started:
            self._started = True
            return ()
        return tuple(sorted(fresh, key=lambda e: e.timestamp_ms))
