import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

from tracker.models import Result, TopicConfig
from tracker.pipeline.stage1 import Stage1Filter


def make_topic(threshold=0.65, tags=None):
    return TopicConfig(
        name="Test",
        description="test",
        importance="high",
        urgency="medium",
        source_categories=["news"],
        polling={"frequent": [], "discovery": [], "broad": []},
        notifications={"push": True, "email": "never", "novelty_push_threshold": 0.7},
        llm_filter={
            "novelty_threshold": threshold,
            "semantic_dedup_threshold": 0.85,
            "tags": tags or ["noise", "new_listing"],
        },
        escalation={"triggers": [], "auto_revert": True},
    )


def make_result(url="https://example.com"):
    return Result(
        url=url,
        title="Test Title",
        snippet="Test snippet",
        source="google_news",
        source_type="news",
        topic_name="Test",
        fetched_at=datetime.now(timezone.utc),
    )


def fake_gemini_response(score: float, tags: list[str]):
    mock = MagicMock()
    mock.text = json.dumps({
        "novelty_score": score,
        "is_relevant": score >= 0.5,
        "preliminary_tags": tags,
        "reasoning": "test reason",
    })
    return mock


def test_high_score_result_passes():
    topic = make_topic(threshold=0.65)
    result = make_result()
    with patch("tracker.pipeline.stage1.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value = fake_gemini_response(0.9, ["new_listing"])
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(result, topic)])
    assert len(passed) == 1
    assert passed[0][0].novelty_score == 0.9


def test_low_score_result_filtered_out():
    topic = make_topic(threshold=0.65)
    result = make_result()
    with patch("tracker.pipeline.stage1.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value = fake_gemini_response(0.3, ["noise"])
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(result, topic)])
    assert len(passed) == 0


def test_json_parse_failure_skips_item():
    topic = make_topic()
    result = make_result()
    with patch("tracker.pipeline.stage1.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        bad_response = MagicMock()
        bad_response.text = "not valid json {{{"
        mock_model.generate_content.return_value = bad_response
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(result, topic)])
    assert len(passed) == 0


def test_multiple_items_filtered_independently():
    topic = make_topic(threshold=0.65)
    results = [make_result(url=f"https://example.com/{i}") for i in range(3)]
    scores = [0.9, 0.3, 0.8]

    def side_effect(*args, **kwargs):
        idx = mock_model.generate_content.call_count - 1
        return fake_gemini_response(scores[idx], ["noise"])

    # _last_request_at starts at 0.0 in __init__. In production, the first
    # monotonic() call returns a large number so elapsed >> interval → no sleep.
    # Simulate that: start at 1000.0, then advance by 5.1s per item (> 5.0s interval).
    # Each item calls monotonic() twice: once for elapsed check, once to record the time.
    monotonic_values = iter([1000.0, 1000.0, 1005.1, 1005.1, 1010.2, 1010.2])
    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep") as mock_sleep, \
         patch("tracker.pipeline.stage1.time.monotonic", side_effect=monotonic_values):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.side_effect = side_effect
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(r, topic) for r in results])

    assert len(passed) == 2
    assert mock_sleep.call_count == 0  # all elapsed times exceed _REQUEST_INTERVAL


def test_rate_limit_429_retries_with_parsed_delay():
    """On a 429 with 'retry in Xs', _score should sleep that delay + 2s then retry."""
    topic = make_topic()
    result = make_result()
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("429 Too Many Requests: retry in 5s, please wait")
        return fake_gemini_response(0.8, [])

    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep") as mock_sleep, \
         patch("tracker.pipeline.stage1.time.monotonic", return_value=100.0):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.side_effect = side_effect
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(result, topic)])

    assert len(passed) == 1
    # First sleep: rate limit pacing (0s elapsed on first item, _last_request_at=0 → big elapsed)
    # Second sleep: 429 retry — parsed delay is 5s + 2s = 7s
    rate_limit_sleep = next(
        (c.args[0] for c in mock_sleep.call_args_list if c.args[0] > 1), None
    )
    assert rate_limit_sleep is not None
    assert abs(rate_limit_sleep - 7.0) < 0.1


def test_rate_limit_429_no_retry_hint_aborts_batch():
    """On a 429 without a retry hint (daily quota exhausted), abort immediately — no sleep."""
    topic = make_topic()
    results = [make_result(url=f"https://example.com/{i}") for i in range(3)]

    def side_effect(*args, **kwargs):
        raise Exception("429 quota exceeded")  # no "retry in Xs"

    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep") as mock_sleep, \
         patch("tracker.pipeline.stage1.time.monotonic", return_value=100.0):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.side_effect = side_effect
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(r, topic) for r in results])

    assert passed == []
    assert f._quota_exhausted is True
    # Should NOT have slept a long backoff — aborts immediately
    long_sleeps = [c.args[0] for c in mock_sleep.call_args_list if c.args[0] >= 30]
    assert long_sleeps == []


def test_items_capped_at_max_per_run():
    """Items exceeding MAX_ITEMS_PER_RUN are silently deferred (truncated)."""
    topic = make_topic()
    n = Stage1Filter.MAX_ITEMS_PER_RUN + 10
    items = [(make_result(url=f"https://example.com/{i}"), topic) for i in range(n)]

    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep"), \
         patch("tracker.pipeline.stage1.time.monotonic", return_value=100.0):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value = fake_gemini_response(0.9, [])
        f = Stage1Filter(api_key="fake")
        f.filter(items)

    assert mock_model.generate_content.call_count == Stage1Filter.MAX_ITEMS_PER_RUN


def test_global_cap_applies_across_multiple_filter_calls():
    """MAX_ITEMS_PER_RUN is a per-run budget shared across all filter() calls (i.e. all topics)."""
    topic = make_topic()
    # First call uses up the full budget
    items_a = [(make_result(url=f"https://a.com/{i}"), topic) for i in range(Stage1Filter.MAX_ITEMS_PER_RUN)]
    # Second call (simulating a second topic) should be skipped entirely
    items_b = [(make_result(url=f"https://b.com/{i}"), topic) for i in range(5)]

    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep"), \
         patch("tracker.pipeline.stage1.time.monotonic", return_value=100.0):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value = fake_gemini_response(0.9, [])
        f = Stage1Filter(api_key="fake")
        f.filter(items_a)
        result_b = f.filter(items_b)

    assert result_b == []
    assert mock_model.generate_content.call_count == Stage1Filter.MAX_ITEMS_PER_RUN


def test_global_cap_partial_remaining_budget():
    """Second filter() call uses only the remaining budget slots, not the full cap."""
    topic = make_topic()
    first_batch = Stage1Filter.MAX_ITEMS_PER_RUN - 5
    items_a = [(make_result(url=f"https://a.com/{i}"), topic) for i in range(first_batch)]
    # Only 5 slots remain — 10 items offered but only 5 should be scored
    items_b = [(make_result(url=f"https://b.com/{i}"), topic) for i in range(10)]

    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep"), \
         patch("tracker.pipeline.stage1.time.monotonic", return_value=100.0):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value = fake_gemini_response(0.9, [])
        f = Stage1Filter(api_key="fake")
        f.filter(items_a)
        f.filter(items_b)

    assert mock_model.generate_content.call_count == Stage1Filter.MAX_ITEMS_PER_RUN


def test_retry_429_also_fails_aborts_quota():
    """If the retry attempt also returns 429 (even with a hint), treat as daily quota exhausted.

    This is the key fix for the 43-minute hang: Gemini includes retry hints on daily quota
    errors too, so 'hint present' no longer means 'just RPM throttling'. If the retry still
    fails, we abort immediately rather than looping through all remaining items.
    """
    topic = make_topic()
    results = [make_result(url=f"https://example.com/{i}") for i in range(3)]

    def side_effect(*args, **kwargs):
        raise Exception("429 Too Many Requests: retry in 60s, please wait")

    with patch("tracker.pipeline.stage1.genai") as mock_genai, \
         patch("tracker.pipeline.stage1.time.sleep") as mock_sleep, \
         patch("tracker.pipeline.stage1.time.monotonic", return_value=100.0):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.side_effect = side_effect
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(r, topic) for r in results])

    assert passed == []
    assert f._quota_exhausted is True
    # All 3 attempts are made for the first item (each gets a 60s retry hint,
    # which is < 300s so not immediately treated as RPD exhaustion). After
    # attempt 2 (the last), the code falls through to the quota-abort path.
    # Items 2 and 3 are never attempted.
    assert mock_model.generate_content.call_count == 3
    # Two retry sleeps: attempt 0→1 and attempt 1→2 (each 62s).
    long_sleeps = [c.args[0] for c in mock_sleep.call_args_list if c.args[0] >= 30]
    assert len(long_sleeps) == 2
    assert all(abs(s - 62.0) < 0.1 for s in long_sleeps)


# ── Configurable cap tests ────────────────────────────────────────────────────


def test_max_items_constructor_param():
    """Constructor param overrides the class-level default."""
    with patch("tracker.pipeline.stage1.genai"):
        f = Stage1Filter(api_key="fake", max_items_per_run=5)
    assert f.MAX_ITEMS_PER_RUN == 5


def test_max_items_env_var():
    """STAGE1_MAX_ITEMS_PER_RUN env var sets the cap when no constructor param given."""
    env = os.environ.copy()
    os.environ["STAGE1_MAX_ITEMS_PER_RUN"] = "7"
    try:
        with patch("tracker.pipeline.stage1.genai"):
            f = Stage1Filter(api_key="fake")
        assert f.MAX_ITEMS_PER_RUN == 7
    finally:
        if "STAGE1_MAX_ITEMS_PER_RUN" in env:
            os.environ["STAGE1_MAX_ITEMS_PER_RUN"] = env["STAGE1_MAX_ITEMS_PER_RUN"]
        else:
            del os.environ["STAGE1_MAX_ITEMS_PER_RUN"]


def test_max_items_class_default_unchanged():
    """Instance-level overrides don't mutate the class-level constant."""
    with patch("tracker.pipeline.stage1.genai"):
        Stage1Filter(api_key="fake", max_items_per_run=999)
    assert Stage1Filter.MAX_ITEMS_PER_RUN == 20
