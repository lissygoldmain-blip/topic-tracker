from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.pubmed import PubMedAdapter, _parse_pubmed_date
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="pubmed", terms=["CRISPR gene editing"])

# Minimal NCBI esearch response
ESEARCH_RESPONSE = {
    "esearchresult": {
        "idlist": ["39000001", "39000002"],
    }
}

# Minimal NCBI esummary response
ESUMMARY_RESPONSE = {
    "result": {
        "39000001": {
            "title": "CRISPR-Cas9 off-target effects in clinical trials",
            "source": "Nature Medicine",
            "pubdate": "2026 Mar 15",
            "authors": [
                {"name": "Zhang F"},
                {"name": "Doudna JA"},
                {"name": "Liu D"},
                {"name": "Bhatt D"},
            ],
        },
        "39000002": {
            "title": "Base editing for sickle cell disease",
            "source": "New England Journal of Medicine",
            "pubdate": "2026 Feb",
            "authors": [{"name": "Komor A"}],
        },
    }
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results():
    with patch("tracker.adapters.pubmed.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_get(ESEARCH_RESPONSE),
            _mock_get(ESUMMARY_RESPONSE),
        ]
        results = PubMedAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "pubmed"
    assert results[0].source_type == "science"
    assert "39000001" in results[0].url


def test_et_al_truncates_authors():
    with patch("tracker.adapters.pubmed.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_get(ESEARCH_RESPONSE),
            _mock_get(ESUMMARY_RESPONSE),
        ]
        results = PubMedAdapter().fetch(SOURCE, TOPIC)
    # pmid 39000001 has 4 authors — should be truncated
    assert "et al." in results[0].snippet


def test_single_author_no_et_al():
    with patch("tracker.adapters.pubmed.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_get(ESEARCH_RESPONSE),
            _mock_get(ESUMMARY_RESPONSE),
        ]
        results = PubMedAdapter().fetch(SOURCE, TOPIC)
    # pmid 39000002 has only 1 author
    assert "et al." not in results[1].snippet


def test_no_pmids_skips_summary():
    empty_search = {"esearchresult": {"idlist": []}}
    with patch("tracker.adapters.pubmed.requests.get") as mock_get:
        mock_get.return_value = _mock_get(empty_search)
        results = PubMedAdapter().fetch(SOURCE, TOPIC)
    assert results == []
    # Only one call — esearch only, no esummary
    assert mock_get.call_count == 1


def test_http_error_sets_last_failed():
    with patch("tracker.adapters.pubmed.requests.get") as mock_get:
        mock_get.side_effect = Exception("connection refused")
        adapter = PubMedAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True


def test_api_key_included_when_set():
    with patch("tracker.adapters.pubmed.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_get(ESEARCH_RESPONSE),
            _mock_get(ESUMMARY_RESPONSE),
        ]
        with patch("tracker.adapters.pubmed.os.environ") as mock_env:
            mock_env.get = MagicMock(return_value="test-ncbi-key")
            adapter = PubMedAdapter()
            adapter.fetch(SOURCE, TOPIC)
    # First call params should include api_key
    call_params = mock_get.call_args_list[0].kwargs.get("params", {})
    assert call_params.get("api_key") == "test-ncbi-key"


# ── date parser unit tests ───────────────────────────────────────────────────

def test_parse_full_date():
    dt = _parse_pubmed_date("2026 Mar 15")
    assert dt.year == 2026
    assert dt.month == 3
    assert dt.day == 15


def test_parse_year_month():
    dt = _parse_pubmed_date("2026 Feb")
    assert dt.year == 2026
    assert dt.month == 2
    assert dt.day == 1


def test_parse_year_only():
    dt = _parse_pubmed_date("2025")
    assert dt.year == 2025
    assert dt.month == 1
    assert dt.day == 1


def test_parse_invalid_falls_back():
    from datetime import timezone
    dt = _parse_pubmed_date("Epub ahead of print")
    # Should return a plausible now() rather than crash
    assert dt.tzinfo == timezone.utc
