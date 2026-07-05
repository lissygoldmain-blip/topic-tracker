"""Source-health detection for the weekly digest.

Catches the silent-death failure mode that let Reddit and Health rot unnoticed:
a source stops returning items but its swallowed errors never trip the circuit
breaker, so both item counts and breaker state lag reality. We derive health
straight from the item store instead — the freshest item per source is ground
truth.

Two failure modes, both actionable in a weekly glance:
  - "missing": a source declared in topics.yaml that has produced zero items
    (e.g. the Semantic Scholar endpoint bug, or Bluesky with no app-password).
  - "silent":  a source with items, but whose newest item is older than the
    stale window (e.g. Reddit 429ing on the CI IP while old items linger).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def source_health(
    index: dict[str, list[dict]],
    configured_sources: set[str],
    now: datetime,
    stale_days: int = 7,
) -> list[dict]:
    """Return only the problem sources, sorted by source name.

    Each entry: {"source": str, "status": "silent"|"missing", "last_seen": datetime|None}
    """
    newest: dict[str, datetime] = {}
    for items in index.values():
        for it in items:
            src = it.get("source")
            ts = it.get("fetched_at")
            if not src or not ts:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:  # ponytail: assume UTC for legacy naive stamps
                ts = ts.replace(tzinfo=timezone.utc)
            if src not in newest or ts > newest[src]:
                newest[src] = ts

    cutoff = now - timedelta(days=stale_days)
    problems: list[dict] = []
    for src in configured_sources:
        if src not in newest:
            problems.append({"source": src, "status": "missing", "last_seen": None})
    for src, ts in newest.items():
        # ponytail: only nag about sources still in topics.yaml — a removed source
        # going stale is expected, not a regression worth an email line.
        if src in configured_sources and ts < cutoff:
            problems.append({"source": src, "status": "silent", "last_seen": ts})

    problems.sort(key=lambda p: p["source"])
    return problems
