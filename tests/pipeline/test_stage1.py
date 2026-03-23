import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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

    with patch("tracker.pipeline.stage1.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.side_effect = side_effect
        f = Stage1Filter(api_key="fake")
        passed = f.filter([(r, topic) for r in results])

    assert len(passed) == 2
