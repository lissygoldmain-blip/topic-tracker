"""Tests for SubstackAdapter (discovery and direct modes)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _mock_response(content=b"<feed />"):
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


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


def _discovery_get(handles):
    """side_effect for requests.get: search → handles, feed → plain bytes."""
    def _get(url, **kwargs):
        if "api/v1/search" in url:
            return _fake_search_response(handles)
        return _mock_response()
    return _get


def test_discovery_mode_searches_and_fetches():
    adapter = SubstackAdapter()
    source = make_source(terms=["NYC theater"])

    with patch("tracker.adapters.substack.requests.get",
               side_effect=_discovery_get(["theaternyc", "offbroadway"])), \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_parse.return_value = _fake_feed([
            {"link": "https://theaternyc.substack.com/p/post1", "title": "A great show"},
        ])
        results = adapter.fetch(source, make_topic())

    # One search term → 2 handles found → 2 feeds parsed
    assert mock_parse.call_count == 2
    assert len(results) == 2  # 1 article × 2 feeds


def test_direct_mode_skips_search():
    adapter = SubstackAdapter()
    source = make_source(filters={"feeds": ["https://myhandle.substack.com/feed"]})

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _fake_feed([
            {"link": "https://myhandle.substack.com/p/post1", "title": "Post 1"},
        ])
        results = adapter.fetch(source, make_topic())

    # In direct mode, no Substack search endpoint is called
    call_urls = [c[0][0] for c in mock_get.call_args_list]
    assert not any("api/v1/search" in u for u in call_urls)
    assert len(results) == 1
    assert results[0].source == "substack"


def test_max_pubs_limits_newsletters_per_term():
    adapter = SubstackAdapter()
    source = make_source(terms=["NYC arts"], filters={"max_pubs": 2})

    with patch("tracker.adapters.substack.requests.get",
               side_effect=_discovery_get(["pub1", "pub2", "pub3", "pub4", "pub5"])), \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_parse.return_value = _fake_feed([])
        adapter.fetch(source, make_topic())

    # 5 handles returned but max_pubs=2 → only 2 feeds fetched
    assert mock_parse.call_count == 2


def test_max_per_feed_limits_articles():
    adapter = SubstackAdapter()
    source = make_source(filters={
        "feeds": ["https://myhandle.substack.com/feed"],
        "max_per_feed": 3,
    })

    entries = [
        {"link": f"https://myhandle.substack.com/p/post{i}", "title": f"Post {i}"}
        for i in range(10)
    ]
    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _fake_feed(entries)
        results = adapter.fetch(source, make_topic())

    assert len(results) == 3


def test_deduplicates_handles_across_terms():
    adapter = SubstackAdapter()
    source = make_source(terms=["NYC theater", "NYC arts"])

    with patch("tracker.adapters.substack.requests.get",
               side_effect=_discovery_get(["same_newsletter"])), \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_parse.return_value = _fake_feed([])
        adapter.fetch(source, make_topic())

    # Same handle from 2 terms → only 1 feed fetch
    assert mock_parse.call_count == 1


def test_search_error_sets_last_failed():
    adapter = SubstackAdapter()
    source = make_source(terms=["NYC theater"])

    with patch("tracker.adapters.substack.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        results = adapter.fetch(source, make_topic())

    assert results == []
    assert adapter._last_failed is True


def test_bad_feed_skipped_gracefully():
    adapter = SubstackAdapter()
    source = make_source(filters={"feeds": ["https://broken.substack.com/feed"]})

    bad_feed = MagicMock()
    bad_feed.bozo = True
    bad_feed.entries = []

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse", return_value=bad_feed):
        mock_get.return_value = _mock_response()
        results = adapter.fetch(source, make_topic())

    assert results == []


def test_result_fields_populated():
    adapter = SubstackAdapter()
    source = make_source(filters={"feeds": ["https://myhandle.substack.com/feed"]})

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _fake_feed([{
            "link": "https://myhandle.substack.com/p/the-post",
            "title": "The Post Title",
            "summary": "Summary text here.",
            "published_parsed": (2026, 3, 24, 10, 0, 0, 0, 0, 0),
        }])
        results = adapter.fetch(source, make_topic())

    r = results[0]
    assert r.source == "substack"
    assert r.source_type == "feeds"
    assert r.title == "The Post Title"
    assert r.published_at is not None
    assert r.published_at.year == 2026
    assert r.published_at.month == 3
    assert r.raw["newsletter"] == "Test Newsletter"


def test_fetch_uses_timeout():
    """requests.get must always be called with a timeout to prevent hanging."""
    adapter = SubstackAdapter()
    source = make_source(filters={"feeds": ["https://myhandle.substack.com/feed"]})

    with patch("tracker.adapters.substack.requests.get") as mock_get, \
         patch("tracker.adapters.substack.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _fake_feed([])
        adapter.fetch(source, make_topic())

    _, kwargs = mock_get.call_args
    assert "timeout" in kwargs
    assert kwargs["timeout"] > 0
