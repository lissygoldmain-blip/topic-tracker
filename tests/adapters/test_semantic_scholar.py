"""Tests for SemanticScholarAdapter."""
from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tracker.adapters.semantic_scholar import SemanticScholarAdapter
from tracker.models import SourceConfig, TopicConfig


def make_topic(name="Test"):
    return TopicConfig(
        name=name,
        description="test",
        importance="high",
        urgency="low",
        source_categories=["science"],
        polling={},
        notifications={},
        llm_filter={"novelty_threshold": 0.65, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )


def make_source(terms=None, filters=None):
    return SourceConfig(source="semantic_scholar", terms=terms or [], filters=filters or {})


def _fake_response(papers):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"data": papers, "total": len(papers)}
    return mock


def _paper(paper_id="abc123", title="Test Paper", abstract="An abstract.",
           authors=None, year=2026):
    return {
        "paperId": paper_id,
        "title": title,
        "abstract": abstract,
        "authors": authors or [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
        "year": year,
        "externalIds": {"DOI": "10.1234/test"},
        "citationCount": 5,
        "url": f"https://www.semanticscholar.org/paper/{paper_id}",
        "openAccessPdf": None,
    }


def test_fetch_returns_results():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["large language model"])

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([_paper()])
        results = adapter.fetch(source, topic)

    assert len(results) == 1
    assert results[0].source == "semantic_scholar"
    assert results[0].source_type == "science"
    assert results[0].title == "Test Paper"
    assert "semanticscholar.org" in results[0].url


def test_one_request_per_term():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["term1", "term2", "term3"])

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([_paper()])
        results = adapter.fetch(source, topic)

    assert mock_get.call_count == 3


def test_api_key_sent_as_header():
    adapter = SemanticScholarAdapter()
    adapter._api_key = "test_key_123"
    topic = make_topic()
    source = make_source(terms=["llm"])

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([])
        adapter.fetch(source, topic)

    call_kwargs = mock_get.call_args[1]
    assert call_kwargs["headers"]["x-api-key"] == "test_key_123"


def test_no_api_key_sends_no_auth_header():
    adapter = SemanticScholarAdapter()
    adapter._api_key = ""
    topic = make_topic()
    source = make_source(terms=["llm"])

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([])
        adapter.fetch(source, topic)

    call_kwargs = mock_get.call_args[1]
    assert "x-api-key" not in call_kwargs["headers"]


def test_year_filter_passed_to_api():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["llm"], filters={"year": 2025})

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([])
        adapter.fetch(source, topic)

    call_params = mock_get.call_args[1]["params"]
    assert call_params["year"] == 2025


def test_papers_missing_id_or_title_skipped():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["test"])

    papers = [
        _paper(paper_id="good1", title="Good Paper"),
        {"paperId": "", "title": "No ID", "abstract": "", "authors": [], "year": 2026,
         "externalIds": {}, "citationCount": 0, "url": None, "openAccessPdf": None},
        {"paperId": "no_title", "title": "", "abstract": "", "authors": [], "year": 2026,
         "externalIds": {}, "citationCount": 0, "url": None, "openAccessPdf": None},
    ]
    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response(papers)
        results = adapter.fetch(source, topic)

    assert len(results) == 1
    assert results[0].title == "Good Paper"


def test_http_error_sets_last_failed():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["llm"])

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        results = adapter.fetch(source, topic)

    assert results == []
    assert adapter._last_failed is True


def test_year_sets_fetched_at():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["test"])

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([_paper(year=2024)])
        results = adapter.fetch(source, topic)

    assert results[0].fetched_at.year == 2024


def test_open_access_pdf_stored_in_raw():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["test"])

    paper = _paper()
    paper["openAccessPdf"] = {"url": "https://arxiv.org/pdf/2101.12345"}

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([paper])
        results = adapter.fetch(source, topic)

    assert results[0].raw["openAccessPdf"] == "https://arxiv.org/pdf/2101.12345"


def test_limit_filter_respected():
    adapter = SemanticScholarAdapter()
    topic = make_topic()
    source = make_source(terms=["test"], filters={"limit": 5})

    with patch("tracker.adapters.semantic_scholar.requests.get") as mock_get:
        mock_get.return_value = _fake_response([])
        adapter.fetch(source, topic)

    call_params = mock_get.call_args[1]["params"]
    assert call_params["limit"] == 5
