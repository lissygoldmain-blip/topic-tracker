from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.slickdeals import SlickdealsAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="slickdeals", terms=["formal suit"])


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


def test_returns_results():
    entry = _make_entry(
        "https://slickdeals.net/f/12345",
        "Formal Suit 60% Off at Nordstrom Rack",
        published_parsed=(2026, 3, 23, 10, 0, 0, 0, 0, 0),
    )
    with patch("tracker.adapters.slickdeals.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([entry])
        results = SlickdealsAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 1
    assert results[0].source == "slickdeals"
    assert results[0].source_type == "shopping"


def test_rss_url_contains_term():
    with patch("tracker.adapters.slickdeals.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        SlickdealsAdapter().fetch(SOURCE, TOPIC)
    url = mock_parse.call_args.args[0]
    assert "formal+suit" in url or "formal%20suit" in url or "formal suit" in url
    assert "rss=1" in url


def test_multiple_terms_each_queried():
    source = SourceConfig(source="slickdeals", terms=["suit", "blazer"])
    with patch("tracker.adapters.slickdeals.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        SlickdealsAdapter().fetch(source, TOPIC)
    assert mock_parse.call_count == 2


def test_error_returns_empty():
    with patch("tracker.adapters.slickdeals.feedparser.parse") as mock_parse:
        mock_parse.side_effect = Exception("timeout")
        results = SlickdealsAdapter().fetch(SOURCE, TOPIC)
    assert results == []
