"""Tests for SubstackAdapter (discovery and direct modes)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
import feedparser

import pytest

from tracker.adapters.substack import SubstackAdapter
from tracker.models import SourceConfig, TopicConfig


def make_topic(name="Test"):
    return TopicConfig(
        name=name,
        description="test",
        importance="low",
        urgency="low",
        source_categories=["feeds"],
        polling={},
        notifications={},
        llm_filter={"novelty_threshold": 0.55, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )


def make_source(terms=None, filters=None):
    return SourceConfig(source="substack", terms=terms or [], filters=filters or {})


def _fake_search_response(handles: list[str]):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = [{"subdomain": h} for h in handles]
    return mock


def _fake_feed(entries: list[dict]):
    """Build a minimal feedparser-like result."""
    mock_feed = MagicMock()
    mock_feed.feed.title = "Test Newsletter"
    mock_feed.bozo = False
    mock_entries = []
    for e in entries:
        entry = MagicMock()
        entry.link = e.get("link", "https://example.substack.com/p/post")
        entry.title = e.get("title", "Test Post")
        entry.summary = e.get("summary", "A short summary.")
        entry.published_parsed = e.get("published_parsed")
        mock_entries.append(entry)
    mock_feed.entries = mock_entries
    return mock_feed


def test_discovery_mode_searches_and_fetches():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(terms=["NYC theater"])

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_get.return_value = _fake_search_response(["theaternyc", "offbroadway"])
        mock_parse.return_value = _fake_feed([
            {"link": "https://theaternyc.substack.com/p/post1", "title": "A great show"},
        ])
        results = adapter.fetch(source, topic)

    # One search term → 2 handles found → 2 feeds parsed
    assert mock_parse.call_count == 2
    assert len(results) == 2  # 1 article × 2 feeds


def test_direct_mode_skips_search():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(filters={"feeds": ["https://myhandle.substack.com/feed"]})

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_parse.return_value = _fake_feed([
            {"link": "https://myhandle.substack.com/p/post1", "title": "Post 1"},
        ])
        results = adapter.fetch(source, topic)

    mock_get.assert_not_called()  # no search in direct mode
    assert len(results) == 1
    assert results[0].source == "substack"


def test_max_pubs_limits_newsletters_per_term():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(terms=["NYC arts"], filters={"max_pubs": 2})

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        # Search returns 5 handles, max_pubs=2 should cap at 2
        mock_get.return_value = _fake_search_response(
            ["pub1", "pub2", "pub3", "pub4", "pub5"]
        )
        mock_parse.return_value = _fake_feed([])
        adapter.fetch(source, topic)

    assert mock_parse.call_count == 2


def test_max_per_feed_limits_articles():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(filters={
        "feeds": ["https://myhandle.substack.com/feed"],
        "max_per_feed": 3,
    })

    entries = [
        {"link": f"https://myhandle.substack.com/p/post{i}", "title": f"Post {i}"}
        for i in range(10)
    ]
    with patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_parse.return_value = _fake_feed(entries)
        results = adapter.fetch(source, topic)

    assert len(results) == 3


def test_deduplicates_handles_across_terms():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(terms=["NYC theater", "NYC arts"])

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        # Both terms return the same handle
        mock_get.return_value = _fake_search_response(["same_newsletter"])
        mock_parse.return_value = _fake_feed([])
        adapter.fetch(source, topic)

    # Same handle from 2 terms → only 1 feed fetch
    assert mock_parse.call_count == 1


def test_search_error_sets_last_failed():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(terms=["NYC theater"])

    with patch("tracker.adapters.substack.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        results = adapter.fetch(source, topic)

    assert results == []
    assert adapter._last_failed is True


def test_bad_feed_skipped_gracefully():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(filters={"feeds": ["https://broken.substack.com/feed"]})

    bad_feed = MagicMock()
    bad_feed.bozo = True
    bad_feed.entries = []

    with patch("tracker.adapters.substack.feedparser.parse", return_value=bad_feed):
        results = adapter.fetch(source, topic)

    assert results == []


def test_result_fields_populated():
    adapter = SubstackAdapter()
    topic = make_topic()
    source = make_source(filters={"feeds": ["https://myhandle.substack.com/feed"]})

    with patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_parse.return_value = _fake_feed([{
            "link": "https://myhandle.substack.com/p/the-post",
            "title": "The Post Title",
            "summary": "Summary text here.",
            "published_parsed": (2026, 3, 24, 10, 0, 0, 0, 0, 0),
        }])
        results = adapter.fetch(source, topic)

    r = results[0]
    assert r.source == "substack"
    assert r.source_type == "feeds"
    assert r.title == "The Post Title"
    assert r.fetched_at.year == 2026
    assert r.raw["newsletter"] == "Test Newsletter"
