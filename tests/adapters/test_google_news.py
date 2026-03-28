from unittest.mock import MagicMock, patch

from tracker.adapters.google_news import GoogleNewsAdapter
from tracker.models import SourceConfig, TopicConfig


def make_feed_entry(title="Kaneko Suit Available Again", link="https://example.com/kaneko-suit",
                    summary="The Fruit of the Loom suit is back in stock"):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = summary
    entry.published_parsed = (2026, 3, 23, 10, 0, 0, 0, 0, 0)
    return entry


def make_feed(entries=None):
    feed = MagicMock()
    feed.entries = entries or []
    return feed


def make_topic():
    return TopicConfig(
        name="Keiji Kaneko suit",
        description="test",
        importance="high",
        urgency="medium",
        source_categories=["news"],
        polling={"frequent": [], "discovery": [], "broad": []},
        notifications={"push": True, "email": "weekly_digest", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.65, "semantic_dedup_threshold": 0.85, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )


def _mock_response(content=b"<feed />"):
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_returns_results():
    with patch("tracker.adapters.google_news.requests.get") as mock_get, \
         patch("tracker.adapters.google_news.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = make_feed([make_feed_entry()])
        adapter = GoogleNewsAdapter()
        source = SourceConfig(source="google_news", terms=["Keiji Kaneko suit"])
        results = adapter.fetch(source, make_topic())

    assert len(results) == 1
    assert results[0].title == "Kaneko Suit Available Again"
    assert results[0].url == "https://example.com/kaneko-suit"
    assert results[0].source == "google_news"
    assert results[0].source_type == "news"
    assert results[0].topic_name == "Keiji Kaneko suit"


def test_fetch_multiple_terms():
    with patch("tracker.adapters.google_news.requests.get") as mock_get, \
         patch("tracker.adapters.google_news.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = make_feed([make_feed_entry()])
        adapter = GoogleNewsAdapter()
        source = SourceConfig(source="google_news", terms=["Kaneko", "Fruit of Loom"])
        results = adapter.fetch(source, make_topic())

    # Two terms = two requests + two feedparser calls
    assert len(results) == 2
    assert mock_get.call_count == 2
    assert mock_parse.call_count == 2


def test_fetch_returns_empty_on_network_error():
    with patch("tracker.adapters.google_news.requests.get") as mock_get:
        mock_get.side_effect = Exception("timeout")
        adapter = GoogleNewsAdapter()
        source = SourceConfig(source="google_news", terms=["test"])
        results = adapter.fetch(source, make_topic())

    assert results == []


def test_fetch_empty_feed_returns_empty():
    with patch("tracker.adapters.google_news.requests.get") as mock_get, \
         patch("tracker.adapters.google_news.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = make_feed([])
        adapter = GoogleNewsAdapter()
        source = SourceConfig(source="google_news", terms=["test"])
        results = adapter.fetch(source, make_topic())

    assert results == []


def test_fetch_uses_google_news_url():
    """The URL built and passed to requests.get must point to news.google.com with the search term."""
    with patch("tracker.adapters.google_news.requests.get") as mock_get, \
         patch("tracker.adapters.google_news.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = make_feed([])
        adapter = GoogleNewsAdapter()
        source = SourceConfig(source="google_news", terms=["kaneko suit"])
        adapter.fetch(source, make_topic())

    call_url = mock_get.call_args[0][0]
    assert "news.google.com" in call_url
    assert "kaneko+suit" in call_url or "kaneko%20suit" in call_url or "kaneko suit" in call_url


def test_fetch_uses_timeout():
    """requests.get must always be called with a timeout to prevent hanging."""
    with patch("tracker.adapters.google_news.requests.get") as mock_get, \
         patch("tracker.adapters.google_news.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = make_feed([])
        GoogleNewsAdapter().fetch(
            SourceConfig(source="google_news", terms=["test"]), make_topic()
        )

    _, kwargs = mock_get.call_args
    assert "timeout" in kwargs
    assert kwargs["timeout"] > 0
