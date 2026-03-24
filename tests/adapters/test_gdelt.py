from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.gdelt import GDELTAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="gdelt", terms=["keiji kaneko suit"])

GDELT_RESPONSE = {
    "articles": [
        {
            "url": "https://hypebeast.com/2026/3/kaneko",
            "title": "Keiji Kaneko Suit Drop Coverage",
            "domain": "hypebeast.com",
            "seendate": "20260323T100000Z",
        },
        {
            "url": "https://highsnobiety.com/kaneko",
            "title": "Athletic Formal Wear Trend",
            "domain": "highsnobiety.com",
            "seendate": "20260322T080000Z",
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


def test_returns_results():
    with patch("tracker.adapters.gdelt.requests.get") as mock_get:
        mock_get.return_value = _mock_get(GDELT_RESPONSE)
        results = GDELTAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "gdelt"
    assert results[0].source_type == "news"
    assert results[0].url == "https://hypebeast.com/2026/3/kaneko"


def test_date_parsed_from_gdelt_format():
    with patch("tracker.adapters.gdelt.requests.get") as mock_get:
        mock_get.return_value = _mock_get(GDELT_RESPONSE)
        results = GDELTAdapter().fetch(SOURCE, TOPIC)
    assert results[0].fetched_at.year == 2026
    assert results[0].fetched_at.month == 3
    assert results[0].fetched_at.day == 23


def test_http_error_returns_empty():
    with patch("tracker.adapters.gdelt.requests.get") as mock_get:
        mock_get.side_effect = Exception("connection error")
        results = GDELTAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_multiple_terms_each_queried():
    source = SourceConfig(source="gdelt", terms=["kaneko", "fruit of the loom"])
    with patch("tracker.adapters.gdelt.requests.get") as mock_get:
        mock_get.return_value = _mock_get({"articles": []})
        GDELTAdapter().fetch(source, TOPIC)
    assert mock_get.call_count == 2


def test_sourcelang_filter_passed_to_api():
    source = SourceConfig(
        source="gdelt",
        terms=["kaneko suit"],
        filters={"sourcelang": "japanese"},
    )
    with patch("tracker.adapters.gdelt.requests.get") as mock_get:
        mock_get.return_value = _mock_get({"articles": []})
        GDELTAdapter().fetch(source, TOPIC)
    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("sourcelang") == "japanese"
