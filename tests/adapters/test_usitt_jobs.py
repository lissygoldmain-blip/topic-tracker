from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.usitt_jobs import USITTJobsAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="usitt_jobs", terms=["lighting designer"])

USITT_HTML = """
<html><body>
<section class="avail-jobs_section">
  <div class="avail-jobs_chart-list w-dyn-items">
    <div class="avail-jobs_chart-row w-dyn-item">
      <a href="/resources/jobs/lighting-designer-steppenwolf-42">
        <h4>Lighting Designer</h4>
        <span class="company">Steppenwolf Theatre</span>
        <span class="location">Chicago, IL</span>
      </a>
    </div>
    <div class="avail-jobs_chart-row w-dyn-item">
      <a href="/resources/jobs/td-guthrie-99">
        <h4>Technical Director</h4>
        <span class="company">Guthrie Theater</span>
      </a>
    </div>
  </div>
</section>
</body></html>
"""

EMPTY_HTML = "<html><body></body></html>"


def _mock_resp(html, status=200):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock(
        side_effect=None if status < 400 else Exception(f"HTTP {status}")
    )
    return resp


def test_returns_results():
    with patch("tracker.adapters.usitt_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(USITT_HTML)
        results = USITTJobsAdapter().fetch(SOURCE, TOPIC)
    assert len(results) >= 1
    assert results[0].source == "usitt_jobs"
    assert results[0].source_type == "jobs"


def test_term_filtering_applied():
    # "lighting designer" should match first job, not second
    with patch("tracker.adapters.usitt_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(USITT_HTML)
        results = USITTJobsAdapter().fetch(SOURCE, TOPIC)
    titles = [r.title for r in results]
    assert any("Lighting" in t for t in titles)
    assert not any("Technical Director" in t for t in titles)


def test_no_terms_returns_all():
    source = SourceConfig(source="usitt_jobs", terms=[])
    with patch("tracker.adapters.usitt_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(USITT_HTML)
        results = USITTJobsAdapter().fetch(source, TOPIC)
    assert len(results) == 2


def test_relative_urls_made_absolute():
    source = SourceConfig(source="usitt_jobs", terms=[])
    with patch("tracker.adapters.usitt_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(USITT_HTML)
        results = USITTJobsAdapter().fetch(source, TOPIC)
    assert all(r.url.startswith("https://www.usitt.org") for r in results)


def test_empty_page_returns_empty():
    with patch("tracker.adapters.usitt_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(EMPTY_HTML)
        results = USITTJobsAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_http_error_sets_last_failed():
    with patch("tracker.adapters.usitt_jobs.requests.get") as mock_get:
        mock_get.side_effect = Exception("connection refused")
        adapter = USITTJobsAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True
