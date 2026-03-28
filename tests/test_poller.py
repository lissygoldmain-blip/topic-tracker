"""
Tests for poller.py deduplication logic.

Key invariant: URLs are only written to seen_urls.json AFTER they pass Stage1.
Items that are fetched but not scored (quota exhaustion, filtered out) must
remain absent from the persistent seen set so they can be retried next run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tracker.models import Result, TopicConfig
from tracker.poller import run_poll
from tracker.storage import Storage


# ── helpers ──────────────────────────────────────────────────────────────────

def _result(url: str, topic_name: str = "Test Topic") -> Result:
    return Result(
        url=url,
        title="Test Title",
        snippet="Test snippet",
        source="test_source",
        source_type="news",
        topic_name=topic_name,
        fetched_at=datetime.now(timezone.utc),
    )


def _topic(name: str = "Test Topic", sources: list | None = None) -> TopicConfig:
    # urgency="high" → TIER_MAP maps tier_index=0 to "frequent"
    return TopicConfig(
        name=name,
        description="test",
        importance="high",
        urgency="high",
        source_categories=["news"],
        polling={
            "frequent": sources or [{"source": "test_source", "terms": ["test"]}],
            "discovery": [],
            "broad": [],
        },
        notifications={"push": False, "email": "never", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.5, "semantic_dedup_threshold": 0.85, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )


def _mock_adapter(results: list[Result]) -> MagicMock:
    """Return a mock adapter CLASS whose instance returns the given results."""
    cls = MagicMock()
    instance = cls.return_value
    instance._last_failed = False
    instance.fetch.return_value = results
    return cls


def _run(tmp_path, topics, stage1_passed):
    """
    Run the poller with controlled topics, adapters, and Stage1 output.

    stage1_passed: list of (Result, TopicConfig) that Stage1Filter.filter() returns.
    Returns the Storage object so callers can inspect seen state.
    """
    storage = Storage(data_dir=str(tmp_path))
    storage.load()

    mock_stage1_cls = MagicMock()
    mock_stage1_instance = mock_stage1_cls.return_value
    mock_stage1_instance.filter.return_value = stage1_passed
    mock_stage1_instance._quota_exhausted = False
    mock_stage1_instance.MAX_ITEMS_PER_RUN = 20
    mock_stage1_instance._items_scored_this_run = 0

    mock_cb = MagicMock()
    mock_cb.is_disabled.return_value = False

    mock_esc = MagicMock()
    mock_esc.effective_urgency.side_effect = lambda state, topic: topic.urgency

    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}), \
         patch("tracker.poller.load_topics", return_value=topics), \
         patch("tracker.poller.Storage", return_value=storage), \
         patch("tracker.poller.Stage1Filter", mock_stage1_cls), \
         patch("tracker.poller.cb", mock_cb), \
         patch("tracker.poller.esc", mock_esc):
        run_poll(tier_index=0, data_dir=str(tmp_path))

    return storage


# ── tests ─────────────────────────────────────────────────────────────────────

def test_passed_url_is_marked_seen(tmp_path):
    """A URL that passes Stage1 must be written to seen_urls.json."""
    r = _result("https://example.com/passes")
    topic = _topic()
    with patch.dict("tracker.poller.ADAPTERS", {"test_source": _mock_adapter([r])}):
        storage = _run(tmp_path, [topic], stage1_passed=[(r, topic)])
    assert storage.is_seen("https://example.com/passes")


def test_deferred_url_not_marked_seen(tmp_path):
    """
    If Stage1 returns [] (quota exhausted), fetched URLs must NOT end up in
    seen_urls.json — they should be eligible for re-scoring next run.
    """
    r = _result("https://example.com/deferred")
    topic = _topic()
    with patch.dict("tracker.poller.ADAPTERS", {"test_source": _mock_adapter([r])}):
        storage = _run(tmp_path, [topic], stage1_passed=[])
    assert not storage.is_seen("https://example.com/deferred")


def test_filtered_out_url_not_marked_seen(tmp_path):
    """
    A URL that Stage1 scores but rejects (low novelty) must NOT be marked seen,
    so it can be re-evaluated if the topic config changes.
    """
    r1 = _result("https://example.com/pass")
    r2 = _result("https://example.com/reject")
    topic = _topic()
    with patch.dict("tracker.poller.ADAPTERS", {"test_source": _mock_adapter([r1, r2])}):
        # Only r1 passes; r2 was scored but rejected
        storage = _run(tmp_path, [topic], stage1_passed=[(r1, topic)])
    assert storage.is_seen("https://example.com/pass")
    assert not storage.is_seen("https://example.com/reject")


def test_within_run_dedup_prevents_duplicate_scoring(tmp_path):
    """
    Two adapters returning the same URL in one run must only queue it once
    for Stage1 — not score it twice and waste quota.
    """
    shared_url = "https://example.com/shared"
    r = _result(shared_url)
    topic = _topic(sources=[
        {"source": "adapter_a", "terms": ["test"]},
        {"source": "adapter_b", "terms": ["test"]},
    ])

    mock_stage1_cls = MagicMock()
    mock_stage1_instance = mock_stage1_cls.return_value
    mock_stage1_instance._quota_exhausted = False
    mock_stage1_instance.MAX_ITEMS_PER_RUN = 20
    mock_stage1_instance._items_scored_this_run = 0
    # capture what Stage1 actually receives
    received: list[list] = []
    def capture_filter(items):
        received.append(list(items))
        return []
    mock_stage1_instance.filter.side_effect = capture_filter

    mock_cb = MagicMock()
    mock_cb.is_disabled.return_value = False
    mock_esc = MagicMock()
    mock_esc.effective_urgency.side_effect = lambda state, topic: topic.urgency

    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}), \
         patch("tracker.poller.load_topics", return_value=[topic]), \
         patch("tracker.poller.Storage", return_value=Storage(data_dir=str(tmp_path))), \
         patch("tracker.poller.Stage1Filter", mock_stage1_cls), \
         patch("tracker.poller.cb", mock_cb), \
         patch("tracker.poller.esc", mock_esc), \
         patch.dict("tracker.poller.ADAPTERS", {
             "adapter_a": _mock_adapter([r]),
             "adapter_b": _mock_adapter([r]),
         }):
        run_poll(tier_index=0, data_dir=str(tmp_path))

    # Stage1.filter() was called once with 1 item, not twice with the same URL
    all_items = [item for batch in received for item in batch]
    urls_sent = [res.url for res, _ in all_items]
    assert urls_sent.count(shared_url) == 1


def test_proportional_budget_caps_first_topic(tmp_path):
    """
    With a global cap of 2 and two topics each returning 5 items, each topic
    should receive at most ceil(2/2)=1 Gemini slot — the first topic must NOT
    eat both slots and leave the second topic with nothing.
    """
    topic_a = _topic("Topic A", sources=[{"source": "adapter_a", "terms": ["test"]}])
    topic_b = _topic("Topic B", sources=[{"source": "adapter_b", "terms": ["test"]}])

    results_a = [_result(f"https://a.com/{i}", "Topic A") for i in range(5)]
    results_b = [_result(f"https://b.com/{i}", "Topic B") for i in range(5)]

    mock_stage1_cls = MagicMock()
    mock_stage1_instance = mock_stage1_cls.return_value
    mock_stage1_instance._quota_exhausted = False
    mock_stage1_instance._items_scored_this_run = 0
    mock_stage1_instance.MAX_ITEMS_PER_RUN = 2  # tight cap: 1 item per topic

    received: list[list] = []
    def capture_filter(items):
        received.append(list(items))
        # Simulate scoring: each call advances the counter
        mock_stage1_instance._items_scored_this_run += len(items)
        return []
    mock_stage1_instance.filter.side_effect = capture_filter

    mock_cb = MagicMock()
    mock_cb.is_disabled.return_value = False
    mock_esc = MagicMock()
    mock_esc.effective_urgency.side_effect = lambda state, topic: topic.urgency

    storage = Storage(data_dir=str(tmp_path))
    storage.load()

    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}), \
         patch("tracker.poller.load_topics", return_value=[topic_a, topic_b]), \
         patch("tracker.poller.Storage", return_value=storage), \
         patch("tracker.poller.Stage1Filter", mock_stage1_cls), \
         patch("tracker.poller.cb", mock_cb), \
         patch("tracker.poller.esc", mock_esc), \
         patch.dict("tracker.poller.ADAPTERS", {
             "adapter_a": _mock_adapter(results_a),
             "adapter_b": _mock_adapter(results_b),
         }):
        run_poll(tier_index=0, data_dir=str(tmp_path))

    # Each batch passed to filter() must be at most 1 item (ceil(2/2)=1 per topic)
    for batch in received:
        assert len(batch) <= 1, f"Batch exceeded per-topic budget: {len(batch)} items"
    # Both topics must have had a chance — filter() called at least twice (once per topic)
    assert len(received) >= 2
