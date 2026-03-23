from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.generic_rss import GenericRSSAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(link, title, summary="", published_parsed=None):
    e = MagicMock()
    e.link = link
    e.title = title
    e.summary = summary
    if published_parsed is not None:
        e.published_parsed = published_parsed
    else:
        del e.published_parsed
    return e


def test_feeds_from_filters():
    source = SourceConfig(
        source="rss",
        filters={"feeds": ["https://brand.com/feed.rss", "https://other.com/rss"]},
    )
    with patch("tracker.adapters.generic_rss.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        GenericRSSAdapter().fetch(source, TOPIC)
    assert mock_parse.call_count == 2


def test_feeds_from_terms_fallback():
    source = SourceConfig(
        source="rss",
        terms=["https://brand.com/feed.rss"],
    )
    with patch("tracker.adapters.generic_rss.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        GenericRSSAdapter().fetch(source, TOPIC)
    assert mock_parse.call_count == 1
    assert mock_parse.call_args.args[0] == "https://brand.com/feed.rss"


def test_returns_results():
    entry = MagicMock()
    entry.link = "https://brand.com/article/1"
    entry.title = "New Drop Announced"
    entry.summary = "The brand just announced..."
    entry.published_parsed = (2026, 3, 23, 12, 0, 0, 0, 0, 0)

    source = SourceConfig(
        source="rss", filters={"feeds": ["https://brand.com/feed.rss"]}
    )
    with patch("tracker.adapters.generic_rss.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([entry])
        results = GenericRSSAdapter().fetch(source, TOPIC)

    assert len(results) == 1
    assert results[0].source == "rss"
    assert results[0].source_type == "feeds"
    assert results[0].url == "https://brand.com/article/1"


def test_error_returns_empty():
    source = SourceConfig(
        source="rss", filters={"feeds": ["https://bad.feed/rss"]}
    )
    with patch("tracker.adapters.generic_rss.feedparser.parse") as mock_parse:
        mock_parse.side_effect = Exception("timeout")
        results = GenericRSSAdapter().fetch(source, TOPIC)
    assert results == []


def test_published_date_parsed():
    entry = MagicMock()
    entry.link = "https://example.com/1"
    entry.title = "T"
    entry.summary = ""
    entry.published_parsed = (2026, 1, 15, 9, 30, 0, 0, 0, 0)

    source = SourceConfig(
        source="rss", filters={"feeds": ["https://example.com/rss"]}
    )
    with patch("tracker.adapters.generic_rss.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([entry])
        results = GenericRSSAdapter().fetch(source, TOPIC)

    assert results[0].fetched_at.year == 2026
    assert results[0].fetched_at.month == 1
    assert results[0].fetched_at.day == 15
