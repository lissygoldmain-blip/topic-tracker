"""Tests for tracker/health.py — silent-source detection for the digest."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tracker.health import source_health

NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def _item(source: str, days_ago: float) -> dict:
    return {
        "source": source,
        "fetched_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def test_healthy_source_not_flagged():
    index = {"Topic A": [_item("google_news", 0.1), _item("google_news", 1)]}
    assert source_health(index, {"google_news"}, NOW) == []


def test_silent_source_flagged():
    # reddit-style: has items but newest is stale (swallowed 429s, breaker blind)
    index = {"Topic A": [_item("reddit", 9), _item("reddit", 12)]}
    problems = source_health(index, {"reddit"}, NOW, stale_days=7)
    assert len(problems) == 1
    assert problems[0]["source"] == "reddit"
    assert problems[0]["status"] == "silent"
    assert problems[0]["last_seen"] is not None


def test_configured_but_never_produced_flagged():
    # semantic_scholar-style: configured, zero items in the store
    index = {"Topic A": [_item("google_news", 0.1)]}
    problems = source_health(index, {"google_news", "semantic_scholar"}, NOW)
    assert [p["source"] for p in problems] == ["semantic_scholar"]
    assert problems[0]["status"] == "missing"
    assert problems[0]["last_seen"] is None


def test_unconfigured_source_in_store_is_ignored():
    # a source no longer in topics.yaml shouldn't nag even if stale
    index = {"Topic A": [_item("gdelt", 30)]}
    assert source_health(index, set(), NOW) == []


def test_naive_timestamp_does_not_crash():
    index = {"Topic A": [{"source": "rss", "fetched_at": "2026-06-10T00:00:00"}]}
    problems = source_health(index, {"rss"}, NOW, stale_days=7)
    assert problems[0]["status"] == "silent"


def test_results_sorted_by_source():
    index = {"T": [_item("zzz", 30), _item("aaa", 30)]}
    problems = source_health(index, {"zzz", "aaa"}, NOW)
    assert [p["source"] for p in problems] == ["aaa", "zzz"]
