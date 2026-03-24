"""Tests for BioRxivAdapter (covers both biorxiv and medrxiv servers)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tracker.adapters.biorxiv import BioRxivAdapter
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


def make_source(source="biorxiv", terms=None, filters=None):
    return SourceConfig(source=source, terms=terms or [], filters=filters or {})


def _fake_response(papers, total=None):
    if total is None:
        total = len(papers)
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "collection": papers,
        "messages": [{"cursor": 0, "count": total}],
    }
    return mock


def _paper(doi="10.1101/2026.01.01.123456", title="Test Paper",
           abstract="This is an abstract.", authors="Alice Smith; Bob Jones",
           date="2026-03-01"):
    return {
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "date": date,
        "category": "neuroscience",
        "server": "biorxiv",
    }


def test_fetch_returns_results(tmp_path):
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source()

    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response([_paper()])
        results = adapter.fetch(source, topic)

    assert len(results) == 1
    assert results[0].source == "biorxiv"
    assert results[0].source_type == "science"
    assert results[0].title == "Test Paper"
    assert "biorxiv.org" in results[0].url
    assert "10.1101" in results[0].url


def test_medrxiv_source_name_and_url():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source(source="medrxiv")

    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        p = _paper()
        p["server"] = "medrxiv"
        mock_get.return_value = _fake_response([p])
        results = adapter.fetch(source, topic)

    assert results[0].source == "medrxiv"
    assert "medrxiv.org" in results[0].url


def test_term_filter_includes_matching_paper():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source(terms=["CRISPR"])

    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response([
            _paper(title="CRISPR gene editing study", abstract="We edited genes."),
            _paper(doi="10.1101/other", title="Unrelated paper", abstract="Nothing relevant."),
        ])
        results = adapter.fetch(source, topic)

    assert len(results) == 1
    assert "CRISPR" in results[0].title


def test_term_filter_case_insensitive():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source(terms=["crispr"])  # lowercase term

    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response([
            _paper(title="CRISPR editing", abstract=""),
        ])
        results = adapter.fetch(source, topic)

    assert len(results) == 1


def test_no_terms_returns_all_papers():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source(terms=[])  # no filter

    papers = [_paper(doi=f"10.1101/x{i}") for i in range(3)]
    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response(papers, total=3)
        results = adapter.fetch(source, topic)

    assert len(results) == 3


def test_max_results_cap():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source(filters={"max_results": 2})

    papers = [_paper(doi=f"10.1101/x{i}") for i in range(5)]
    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response(papers, total=5)
        results = adapter.fetch(source, topic)

    assert len(results) == 2


def test_http_error_sets_last_failed():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source()

    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.side_effect = Exception("connection error")
        results = adapter.fetch(source, topic)

    assert results == []
    assert adapter._last_failed is True


def test_author_formatting():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source()

    paper = _paper(authors="Alice A; Bob B; Carol C; Dave D")
    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response([paper])
        results = adapter.fetch(source, topic)

    # snippet is from abstract; authors are available via raw
    assert results[0].raw["authors"] == "Alice A; Bob B; Carol C; Dave D"


def test_date_parsed_correctly():
    adapter = BioRxivAdapter()
    topic = make_topic()
    source = make_source()

    with patch("tracker.adapters.biorxiv.requests.get") as mock_get:
        mock_get.return_value = _fake_response([_paper(date="2026-03-15")])
        results = adapter.fetch(source, topic)

    assert results[0].fetched_at.year == 2026
    assert results[0].fetched_at.month == 3
    assert results[0].fetched_at.day == 15
