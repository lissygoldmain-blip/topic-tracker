from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.arxiv import ArxivAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="arxiv", terms=["CRISPR base editing"])

# Minimal feedparser-style parsed feed
_ENTRY_1 = {
    "id": "https://arxiv.org/abs/2603.00001",
    "title": "Precision base editing corrects monogenic disease mutations",
    "summary": "We demonstrate a high-fidelity base editor that corrects point mutations "
               "in patient-derived iPSCs with minimal off-target activity.",
    "authors": [{"name": "Komor AC"}, {"name": "Liu D"}, {"name": "Zhang X"}, {"name": "Li Y"}],
    "published_parsed": (2026, 3, 20, 0, 0, 0, 0, 0, 0),
    "tags": [{"term": "q-bio.GN"}, {"term": "q-bio.BM"}],
}

_ENTRY_2 = {
    "id": "https://arxiv.org/abs/2603.00002",
    "title": "Off-target landscape of adenine base editors",
    "summary": "Short summary.",
    "authors": [{"name": "Rees HA"}],
    "published_parsed": (2026, 3, 18, 0, 0, 0, 0, 0, 0),
    "tags": [{"term": "q-bio.GN"}],
}

FAKE_FEED = MagicMock()
FAKE_FEED.bozo = False
FAKE_FEED.entries = [_ENTRY_1, _ENTRY_2]

EMPTY_FEED = MagicMock()
EMPTY_FEED.bozo = False
EMPTY_FEED.entries = []


def test_returns_results():
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=FAKE_FEED):
        results = ArxivAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "arxiv"
    assert results[0].source_type == "science"
    assert "2603.00001" in results[0].url


def test_et_al_truncates_four_authors():
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=FAKE_FEED):
        results = ArxivAdapter().fetch(SOURCE, TOPIC)
    # _ENTRY_1 has 4 authors — snippet should include "et al."
    assert "et al." in results[0].snippet


def test_single_author_no_et_al():
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=FAKE_FEED):
        results = ArxivAdapter().fetch(SOURCE, TOPIC)
    assert "et al." not in results[1].snippet


def test_category_filter_in_query():
    source = SourceConfig(
        source="arxiv",
        terms=["sickle cell"],
        filters={"categories": ["q-bio.GN", "q-bio.BM"]},
    )
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=EMPTY_FEED) as mock_parse:
        ArxivAdapter().fetch(source, TOPIC)
    url_called = mock_parse.call_args.args[0]
    assert "cat%3Aq-bio.GN" in url_called or "cat:q-bio.GN" in url_called


def test_empty_feed_returns_empty():
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=EMPTY_FEED):
        results = ArxivAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_bozo_feed_sets_last_failed():
    bozo_feed = MagicMock()
    bozo_feed.bozo = True
    bozo_feed.entries = []
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=bozo_feed):
        adapter = ArxivAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_exception_sets_last_failed():
    with patch("tracker.adapters.arxiv.feedparser.parse", side_effect=Exception("timeout")):
        adapter = ArxivAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_published_date_parsed():
    from datetime import timezone
    with patch("tracker.adapters.arxiv.feedparser.parse", return_value=FAKE_FEED):
        results = ArxivAdapter().fetch(SOURCE, TOPIC)
    assert results[0].fetched_at.year == 2026
    assert results[0].fetched_at.month == 3
    assert results[0].fetched_at.tzinfo == timezone.utc
