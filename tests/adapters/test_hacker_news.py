from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.hacker_news import HackerNewsAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()

SOURCE = SourceConfig(source="hacker_news", terms=["keiji kaneko suit"])

HN_RESPONSE = {
    "hits": [
        {
            "objectID": "12345",
            "title": "Kaneko x Fruit of the Loom suit spotted on Grailed",
            "url": "https://grailed.com/listings/12345",
            "created_at": "2026-03-23T10:00:00.000Z",
            "story_text": None,
        },
        {
            "objectID": "67890",
            "title": "Ask HN: Anyone find the Kaneko suit?",
            "url": None,  # self-post — no external URL
            "created_at": "2026-03-22T08:00:00.000Z",
            "story_text": "Looking for this limited piece...",
        },
    ]
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results():
    with patch("tracker.adapters.hacker_news.requests.get") as mock_get:
        mock_get.return_value = _mock_get(HN_RESPONSE)
        results = HackerNewsAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].url == "https://grailed.com/listings/12345"
    assert results[0].title == "Kaneko x Fruit of the Loom suit spotted on Grailed"
    assert results[0].source == "hacker_news"
    assert results[0].source_type == "social"


def test_self_post_uses_hn_url():
    with patch("tracker.adapters.hacker_news.requests.get") as mock_get:
        mock_get.return_value = _mock_get(HN_RESPONSE)
        results = HackerNewsAdapter().fetch(SOURCE, TOPIC)
    # Second hit has no url → falls back to HN item URL
    assert results[1].url == "https://news.ycombinator.com/item?id=67890"
    assert results[1].snippet == "Looking for this limited piece..."


def test_http_error_returns_empty():
    with patch("tracker.adapters.hacker_news.requests.get") as mock_get:
        mock_get.side_effect = Exception("connection refused")
        results = HackerNewsAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_multiple_terms_each_queried():
    source = SourceConfig(source="hacker_news", terms=["term one", "term two"])
    with patch("tracker.adapters.hacker_news.requests.get") as mock_get:
        mock_get.return_value = _mock_get({"hits": []})
        HackerNewsAdapter().fetch(source, TOPIC)
    assert mock_get.call_count == 2


def test_bad_date_falls_back_to_now():
    data = {
        "hits": [
            {
                "objectID": "1",
                "title": "Test",
                "url": "https://example.com",
                "created_at": "not-a-date",
                "story_text": None,
            }
        ]
    }
    with patch("tracker.adapters.hacker_news.requests.get") as mock_get:
        mock_get.return_value = _mock_get(data)
        results = HackerNewsAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 1
    # Should not raise — just uses datetime.now()
    assert results[0].fetched_at is not None
