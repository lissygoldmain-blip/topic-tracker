from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.playbill_jobs import PlaybillJobsAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="playbill_jobs", terms=["stage manager"])

# Minimal Playbill jobs HTML with pb-tile-tag-job structure
PLAYBILL_HTML = """
<html><body>
<div id="job-listings">
  <div class="pb-tile-tag-job-paid">
    <a href="/job/stage-manager-lincoln-center-12345">
      <h3>Stage Manager — Lincoln Center</h3>
      <p class="company">Lincoln Center for the Performing Arts</p>
      <p class="desc">Full-time, IATSE. New York, NY.</p>
    </a>
  </div>
  <div class="pb-tile-tag-job-paid">
    <a href="/job/td-playwrights-99">
      <h3>Technical Director — Playwrights Horizons</h3>
      <p class="company">Playwrights Horizons</p>
    </a>
  </div>
</div>
</body></html>
"""

EMPTY_HTML = "<html><body><div id='job-listings'></div></body></html>"


def _mock_resp(html, status=200):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock(
        side_effect=None if status < 400 else Exception(f"HTTP {status}")
    )
    return resp


def test_returns_results():
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(PLAYBILL_HTML)
        results = PlaybillJobsAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "playbill_jobs"
    assert results[0].source_type == "jobs"


def test_relative_urls_made_absolute():
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(PLAYBILL_HTML)
        results = PlaybillJobsAdapter().fetch(SOURCE, TOPIC)
    assert results[0].url.startswith("https://playbill.com")


def test_title_extracted_from_heading():
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(PLAYBILL_HTML)
        results = PlaybillJobsAdapter().fetch(SOURCE, TOPIC)
    assert "Stage Manager" in results[0].title


def test_empty_listings_returns_empty():
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(EMPTY_HTML)
        results = PlaybillJobsAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_dedup_skips_repeated_urls():
    dupe_html = """<html><body><div id="job-listings">
      <div class="pb-tile-tag-job-paid"><a href="/job/abc"><h3>Job A</h3></a></div>
      <div class="pb-tile-tag-job-paid"><a href="/job/abc"><h3>Job A again</h3></a></div>
    </div></body></html>"""
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(dupe_html)
        results = PlaybillJobsAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 1


def test_term_passed_as_query_param():
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(EMPTY_HTML)
        PlaybillJobsAdapter().fetch(SOURCE, TOPIC)
    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("q") == "stage manager"


def test_http_error_sets_last_failed():
    with patch("tracker.adapters.playbill_jobs.requests.get") as mock_get:
        mock_get.side_effect = Exception("timeout")
        adapter = PlaybillJobsAdapter()
        results = adapter.fetch(SOURCE, TOPIC)
    assert results == []
    assert adapter._last_failed is True
