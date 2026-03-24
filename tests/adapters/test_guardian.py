import os
from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.guardian import GuardianAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="guardian", terms=["keiji kaneko suit"])

GUARDIAN_RESPONSE = {
    "response": {
        "status": "ok",
        "results": [
            {
                "webTitle": "The Suit That Broke the Internet",
                "webUrl": "https://www.theguardian.com/fashion/2026/mar/23/kaneko-suit",
                "webPublicationDate": "2026-03-23T10:00:00Z",
                "sectionName": "Fashion",
                "fields": {
                    "trailText": "How a Fruit of the Loom collab became fashion's most wanted.",
                },
            },
            {
                "webTitle": "Athletic Formalwear Is Having a Moment",
                "webUrl": "https://www.theguardian.com/fashion/2026/mar/20/athletic-formal",
                "webPublicationDate": "2026-03-20T08:00:00Z",
                "sectionName": "Fashion",
                "fields": {"trailText": "From Kaneko to Zegna, menswear is rethinking the suit."},
            },
        ],
    }
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results_with_key():
    with patch.dict(os.environ, {"GUARDIAN_API_KEY": "fake-key"}):
        with patch("tracker.adapters.guardian.requests.get") as mock_get:
            mock_get.return_value = _mock_get(GUARDIAN_RESPONSE)
            results = GuardianAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "guardian:Fashion"
    assert results[0].source_type == "news"
    assert "kaneko-suit" in results[0].url


def test_no_api_key_returns_empty_and_sets_last_failed():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("GUARDIAN_API_KEY", None)
        adapter = GuardianAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_trail_text_used_as_snippet():
    with patch.dict(os.environ, {"GUARDIAN_API_KEY": "fake-key"}):
        with patch("tracker.adapters.guardian.requests.get") as mock_get:
            mock_get.return_value = _mock_get(GUARDIAN_RESPONSE)
            results = GuardianAdapter().fetch(SOURCE, TOPIC)
    assert "Fruit of the Loom" in results[0].snippet


def test_section_filter_passed_to_api():
    source = SourceConfig(
        source="guardian",
        terms=["kaneko suit"],
        filters={"section": "fashion"},
    )
    with patch.dict(os.environ, {"GUARDIAN_API_KEY": "fake-key"}):
        with patch("tracker.adapters.guardian.requests.get") as mock_get:
            mock_get.return_value = _mock_get({"response": {"results": []}})
            GuardianAdapter().fetch(source, TOPIC)
    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("section") == "fashion"


def test_from_date_filter_passed_to_api():
    source = SourceConfig(
        source="guardian",
        terms=["kaneko"],
        filters={"from_date": "2026-01-01"},
    )
    with patch.dict(os.environ, {"GUARDIAN_API_KEY": "fake-key"}):
        with patch("tracker.adapters.guardian.requests.get") as mock_get:
            mock_get.return_value = _mock_get({"response": {"results": []}})
            GuardianAdapter().fetch(source, TOPIC)
    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("from-date") == "2026-01-01"


def test_http_error_sets_last_failed():
    with patch.dict(os.environ, {"GUARDIAN_API_KEY": "fake-key"}):
        with patch("tracker.adapters.guardian.requests.get") as mock_get:
            mock_get.side_effect = Exception("connection error")
            adapter = GuardianAdapter()
            results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True
