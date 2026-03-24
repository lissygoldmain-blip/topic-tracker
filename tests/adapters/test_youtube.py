import os
from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.youtube import YouTubeAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="youtube", terms=["keiji kaneko suit"])

YT_RESPONSE = {
    "items": [
        {
            "id": {"videoId": "abc123"},
            "snippet": {
                "title": "Keiji Kaneko x Fruit of the Loom Suit Review",
                "description": "I finally got my hands on this legendary collab...",
                "channelTitle": "MenswearChannel",
                "publishedAt": "2026-03-20T12:00:00Z",
            },
        },
        {
            "id": {"videoId": "def456"},
            "snippet": {
                "title": "Unboxing the Athletic Formal Suit",
                "description": "Opening the box live...",
                "channelTitle": "FashionVlog",
                "publishedAt": "2026-03-18T09:00:00Z",
            },
        },
    ]
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results_with_key():
    with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
        with patch("tracker.adapters.youtube.requests.get") as mock_get:
            mock_get.return_value = _mock_get(YT_RESPONSE)
            results = YouTubeAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "youtube"
    assert results[0].source_type == "video"
    assert results[0].url == "https://www.youtube.com/watch?v=abc123"


def test_no_api_key_returns_empty_and_sets_last_failed():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("YOUTUBE_API_KEY", None)
        adapter = YouTubeAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_http_error_sets_last_failed():
    with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
        with patch("tracker.adapters.youtube.requests.get") as mock_get:
            mock_get.side_effect = Exception("quota exceeded")
            adapter = YouTubeAdapter()
            results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_multiple_terms_each_queried():
    source = SourceConfig(source="youtube", terms=["term one", "term two"])
    with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
        with patch("tracker.adapters.youtube.requests.get") as mock_get:
            mock_get.return_value = _mock_get({"items": []})
            YouTubeAdapter().fetch(source, TOPIC)
    assert mock_get.call_count == 2


def test_video_url_constructed_correctly():
    with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
        with patch("tracker.adapters.youtube.requests.get") as mock_get:
            mock_get.return_value = _mock_get(YT_RESPONSE)
            results = YouTubeAdapter().fetch(SOURCE, TOPIC)
    assert "watch?v=abc123" in results[0].url
