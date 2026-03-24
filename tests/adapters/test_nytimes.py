import os
from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.nytimes import NYTimesAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="nytimes", terms=["keiji kaneko suit"])

NYT_RESPONSE = {
    "status": "OK",
    "response": {
        "docs": [
            {
                "headline": {"main": "The Athletic Formal Suit Taking Over Menswear"},
                "abstract": "Fruit of the Loom's collaboration with Keiji Kaneko...",
                "web_url": "https://www.nytimes.com/2026/03/23/style/kaneko-suit.html",
                "pub_date": "2026-03-23T10:00:00+0000",
                "section_name": "Style",
            },
            {
                "headline": {"main": "Streetwear Meets Formal Wear"},
                "abstract": "A new generation of suits...",
                "web_url": "https://www.nytimes.com/2026/03/20/fashion/suits.html",
                "pub_date": "2026-03-20T08:00:00+0000",
                "section_name": "Fashion & Style",
            },
        ]
    },
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results_with_key():
    with patch.dict(os.environ, {"NYTIMES_API_KEY": "fake-key"}):
        with patch("tracker.adapters.nytimes.requests.get") as mock_get:
            mock_get.return_value = _mock_get(NYT_RESPONSE)
            results = NYTimesAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "nytimes:Style"
    assert results[0].source_type == "news"
    assert "kaneko-suit" in results[0].url


def test_no_api_key_returns_empty_and_sets_last_failed():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("NYTIMES_API_KEY", None)
        adapter = NYTimesAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_section_included_in_source_label():
    with patch.dict(os.environ, {"NYTIMES_API_KEY": "fake-key"}):
        with patch("tracker.adapters.nytimes.requests.get") as mock_get:
            mock_get.return_value = _mock_get(NYT_RESPONSE)
            results = NYTimesAdapter().fetch(SOURCE, TOPIC)
    assert results[1].source == "nytimes:Fashion & Style"


def test_no_section_falls_back_to_nytimes():
    no_section = {
        "status": "OK",
        "response": {
            "docs": [{
                "headline": {"main": "Test"},
                "abstract": "",
                "web_url": "https://nytimes.com/test",
                "pub_date": "2026-03-23T10:00:00+0000",
                "section_name": "",
            }]
        },
    }
    with patch.dict(os.environ, {"NYTIMES_API_KEY": "fake-key"}):
        with patch("tracker.adapters.nytimes.requests.get") as mock_get:
            mock_get.return_value = _mock_get(no_section)
            results = NYTimesAdapter().fetch(SOURCE, TOPIC)
    assert results[0].source == "nytimes"


def test_multiple_terms_adds_delay():
    source = SourceConfig(source="nytimes", terms=["term one", "term two"])
    with patch.dict(os.environ, {"NYTIMES_API_KEY": "fake-key"}):
        with patch("tracker.adapters.nytimes.requests.get") as mock_get:
            with patch("tracker.adapters.nytimes.time.sleep") as mock_sleep:
                mock_get.return_value = _mock_get({"status": "OK", "response": {"docs": []}})
                NYTimesAdapter().fetch(source, TOPIC)
    # Sleep called once (between term 0 and term 1, not before term 0)
    assert mock_sleep.call_count == 1


def test_http_error_sets_last_failed():
    with patch.dict(os.environ, {"NYTIMES_API_KEY": "fake-key"}):
        with patch("tracker.adapters.nytimes.requests.get") as mock_get:
            mock_get.side_effect = Exception("rate limited")
            adapter = NYTimesAdapter()
            results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True
