from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.adzuna import AdzunaAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="adzuna", terms=["stage manager"])

ADZUNA_RESPONSE = {
    "results": [
        {
            "redirect_url": "https://www.adzuna.com/jobs/details/1001",
            "title": "Stage Manager",
            "company": {"display_name": "Lincoln Center"},
            "description": "Lincoln Center seeks an experienced stage manager for upcoming productions.",
            "created": "2026-03-20T10:00:00Z",
            "salary_min": 60000,
            "salary_max": 80000,
        },
        {
            "redirect_url": "https://www.adzuna.com/jobs/details/1002",
            "title": "Production Stage Manager",
            "company": {"display_name": "Playwrights Horizons"},
            "description": "PSM for off-broadway season.",
            "created": "2026-03-18T08:00:00Z",
            "salary_min": None,
            "salary_max": None,
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


def test_returns_results_with_keys():
    with patch.dict(os.environ, {"ADZUNA_APP_ID": "test-id", "ADZUNA_APP_KEY": "test-key"}):
        with patch("tracker.adapters.adzuna.requests.get") as mock_get:
            mock_get.return_value = _mock_get(ADZUNA_RESPONSE)
            results = AdzunaAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "adzuna"
    assert results[0].source_type == "jobs"
    assert "1001" in results[0].url


def test_salary_appended_to_title():
    with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("tracker.adapters.adzuna.requests.get") as mock_get:
            mock_get.return_value = _mock_get(ADZUNA_RESPONSE)
            results = AdzunaAdapter().fetch(SOURCE, TOPIC)
    assert "$60,000" in results[0].title
    assert "$80,000" in results[0].title


def test_no_salary_no_range_suffix():
    with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("tracker.adapters.adzuna.requests.get") as mock_get:
            mock_get.return_value = _mock_get(ADZUNA_RESPONSE)
            results = AdzunaAdapter().fetch(SOURCE, TOPIC)
    assert "$" not in results[1].title


def test_company_prepended_to_snippet():
    with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("tracker.adapters.adzuna.requests.get") as mock_get:
            mock_get.return_value = _mock_get(ADZUNA_RESPONSE)
            results = AdzunaAdapter().fetch(SOURCE, TOPIC)
    assert results[0].snippet.startswith("Lincoln Center")


def test_no_keys_returns_empty_and_sets_last_failed():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("ADZUNA_APP_ID", None)
        os.environ.pop("ADZUNA_APP_KEY", None)
        adapter = AdzunaAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_http_error_sets_last_failed():
    with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("tracker.adapters.adzuna.requests.get") as mock_get:
            mock_get.side_effect = Exception("connection error")
            adapter = AdzunaAdapter()
            results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_country_filter_used_in_url():
    source = SourceConfig(
        source="adzuna", terms=["stage manager"], filters={"country": "gb"}
    )
    with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("tracker.adapters.adzuna.requests.get") as mock_get:
            mock_get.return_value = _mock_get({"results": []})
            AdzunaAdapter().fetch(source, TOPIC)
    url = mock_get.call_args.args[0]
    assert "/gb/" in url
