from datetime import datetime, timezone

from tracker.models import Result, SourceConfig, TopicConfig


def test_result_defaults():
    r = Result(
        url="https://example.com",
        title="Test",
        snippet="Test snippet",
        source="google_news",
        source_type="news",
        topic_name="Test Topic",
        fetched_at=datetime.now(timezone.utc),
    )
    assert r.novelty_score is None
    assert r.tags == []
    assert r.notified_push is False
    assert r.notified_digest is False
    assert r.price is None
    assert r.raw == {}


def test_result_has_price_field():
    r = Result(
        url="http://x.com",
        title="Thing",
        snippet="",
        source="ebay",
        source_type="shopping",
        topic_name="Test",
        fetched_at=datetime.now(timezone.utc),
        price="$45.00",
    )
    assert r.price == "$45.00"


def test_result_price_defaults_to_none():
    r = Result(
        url="http://x.com",
        title="Thing",
        snippet="",
        source="ebay",
        source_type="shopping",
        topic_name="Test",
        fetched_at=datetime.now(timezone.utc),
    )
    assert r.price is None


def test_result_to_dict():
    now = datetime.now(timezone.utc)
    r = Result(
        url="https://example.com",
        title="Test",
        snippet="snippet",
        source="google_news",
        source_type="news",
        topic_name="Test Topic",
        fetched_at=now,
        novelty_score=0.8,
        tags=["noise"],
    )
    d = r.to_dict()
    assert d["url"] == "https://example.com"
    assert d["novelty_score"] == 0.8
    assert d["tags"] == ["noise"]


def test_source_config_defaults():
    s = SourceConfig(source="google_news", terms=["test query"])
    assert s.filters == {}
    assert s.subreddits == []


def test_topic_config_tiers():
    t = TopicConfig(
        name="Test",
        description="desc",
        importance="high",
        urgency="medium",
        source_categories=["news"],
        polling={"frequent": [], "discovery": [], "broad": []},
        notifications={"push": True, "email": "daily_digest", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.65, "semantic_dedup_threshold": 0.85, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )
    assert t.importance == "high"
    assert t.urgency == "medium"


def test_topic_config_sources_for_tier():
    t = TopicConfig(
        name="Test",
        description="desc",
        importance="high",
        urgency="medium",
        source_categories=["news"],
        polling={
            "frequent": [{"source": "google_news", "terms": ["kaneko"]}],
            "discovery": [],
            "broad": [],
        },
        notifications={},
        llm_filter={"novelty_threshold": 0.65, "semantic_dedup_threshold": 0.85, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )
    sources = t.sources_for_tier("frequent")
    assert len(sources) == 1
    assert sources[0].source == "google_news"
    assert "kaneko" in sources[0].terms
