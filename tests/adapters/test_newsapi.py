import os
from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.newsapi import NewsAPIAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="newsapi", terms=["keiji kaneko suit"])

NEWSAPI_RESPONSE = {
    "status": "ok",
    "totalResults": 2,
    "articles": [
        {
            "source": {"name": "Hypebeast"},
            "title": "Keiji Kaneko x Fruit of the Loom Collab Drops This Week",
            "description": "The athletic formal suit collaboration is finally here.",
            "url": "https://hypebeast.com/2026/3/kaneko-suit",
            "publishedAt": "2026-03-23T08:00:00Z",
        },
        {
            "source": {"name": "Highsnobiety"},
            "title": "Where to Buy the Kaneko Suit Before It Sells Out",
            "description": "Everything you need to know about the drop.",
            "url": "https://highsnobiety.com/kaneko",
            "publishedAt": "2026-03-22T14:00:00Z",
        },
    ],
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results_with_key():
    with patch.dict(os.environ, {"NEWSAPI_KEY": "fake-key"}):
        with patch("tracker.adapters.newsapi.requests.get") as mock_get:
            mock_get.return_value = _mock_get(NEWSAPI_RESPONSE)
            results = NewsAPIAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "newsapi:Hypebeast"
    assert results[0].source_type == "news"
    assert results[0].url == "https://hypebeast.com/2026/3/kaneko-suit"


def test_no_api_key_returns_empty_and_sets_last_failed():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("NEWSAPI_KEY", None)
        adapter = NewsAPIAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_http_error_sets_last_failed():
    with patch.dict(os.environ, {"NEWSAPI_KEY": "fake-key"}):
        with patch("tracker.adapters.newsapi.requests.get") as mock_get:
            mock_get.side_effect = Exception("rate limited")
            adapter = NewsAPIAdapter()
            results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_multiple_terms_each_queried():
    source = SourceConfig(source="newsapi", terms=["term one", "term two"])
    with patch.dict(os.environ, {"NEWSAPI_KEY": "fake-key"}):
        with patch("tracker.adapters.newsapi.requests.get") as mock_get:
            mock_get.return_value = _mock_get({"articles": []})
            NewsAPIAdapter().fetch(source, TOPIC)
    assert mock_get.call_count == 2


def test_source_name_included_in_source_field():
    with patch.dict(os.environ, {"NEWSAPI_KEY": "fake-key"}):
        with patch("tracker.adapters.newsapi.requests.get") as mock_get:
            mock_get.return_value = _mock_get(NEWSAPI_RESPONSE)
            results = NewsAPIAdapter().fetch(SOURCE, TOPIC)
    assert "Highsnobiety" in results[1].source
