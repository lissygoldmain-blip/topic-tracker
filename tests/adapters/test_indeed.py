from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.indeed import IndeedAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="indeed", terms=["stage manager NYC"])

_ENTRY_1 = {
    "link": "https://www.indeed.com/viewjob?jk=abc123",
    "title": "Stage Manager – Lincoln Center (New York, NY)",
    "summary": "<p>Lincoln Center seeks an experienced <b>Stage Manager</b> for spring season.</p>",
    "published_parsed": (2026, 3, 20, 10, 0, 0, 0, 0, 0),
}

_ENTRY_2 = {
    "link": "https://www.indeed.com/viewjob?jk=def456",
    "title": "Production Stage Manager – Playwrights Horizons",
    "summary": "PSM for off-broadway productions.",
    "published_parsed": (2026, 3, 18, 8, 0, 0, 0, 0, 0),
}

FAKE_FEED = MagicMock()
FAKE_FEED.bozo = False
FAKE_FEED.entries = [_ENTRY_1, _ENTRY_2]

EMPTY_FEED = MagicMock()
EMPTY_FEED.bozo = False
EMPTY_FEED.entries = []


def test_returns_results():
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=FAKE_FEED):
        results = IndeedAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "indeed"
    assert results[0].source_type == "jobs"
    assert "abc123" in results[0].url


def test_html_stripped_from_snippet():
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=FAKE_FEED):
        results = IndeedAdapter().fetch(SOURCE, TOPIC)
    assert "<p>" not in results[0].snippet
    assert "<b>" not in results[0].snippet
    assert "Lincoln Center" in results[0].snippet


def test_empty_feed_returns_empty():
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=EMPTY_FEED):
        results = IndeedAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_bozo_feed_sets_last_failed():
    bozo = MagicMock()
    bozo.bozo = True
    bozo.entries = []
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=bozo):
        adapter = IndeedAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_exception_sets_last_failed():
    with patch("tracker.adapters.indeed.feedparser.parse", side_effect=Exception("timeout")):
        adapter = IndeedAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_location_filter_in_url():
    source = SourceConfig(
        source="indeed",
        terms=["lighting designer"],
        filters={"location": "Brooklyn, NY", "fromage": 7},
    )
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=EMPTY_FEED) as mock_parse:
        IndeedAdapter().fetch(source, TOPIC)
    url = mock_parse.call_args.args[0]
    assert "Brooklyn" in url
    assert "fromage=7" in url


def test_limit_capped_at_25():
    source = SourceConfig(
        source="indeed", terms=["director"], filters={"limit": 100}
    )
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=EMPTY_FEED) as mock_parse:
        IndeedAdapter().fetch(source, TOPIC)
    url = mock_parse.call_args.args[0]
    assert "limit=25" in url


def test_published_date_parsed():
    from datetime import timezone
    with patch("tracker.adapters.indeed.feedparser.parse", return_value=FAKE_FEED):
        results = IndeedAdapter().fetch(SOURCE, TOPIC)
    assert results[0].fetched_at.year == 2026
    assert results[0].fetched_at.month == 3
    assert results[0].fetched_at.tzinfo == timezone.utc
