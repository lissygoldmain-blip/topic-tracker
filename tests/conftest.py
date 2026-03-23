import pytest

from tracker.models import TopicConfig


@pytest.fixture
def basic_topic():
    return TopicConfig(
        name="Test Topic",
        description="A test topic",
        importance="high",
        urgency="medium",
        source_categories=["news"],
        polling={
            "frequent": [{"source": "google_news", "terms": ["test"]}],
            "discovery": [],
            "broad": [],
        },
        notifications={"push": False, "email": "never", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.65, "semantic_dedup_threshold": 0.85, "tags": ["noise"]},
        escalation={"triggers": [], "auto_revert": True},
    )


def make_full_topic(name="Test Topic"):
    return TopicConfig(
        name=name,
        description="test description",
        importance="high",
        urgency="medium",
        source_categories=["shopping"],
        polling={"frequent": [], "discovery": [], "broad": []},
        notifications={"push": True, "email": "weekly_digest", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.65, "semantic_dedup_threshold": 0.85, "tags": ["noise"]},
        escalation={"triggers": [], "auto_revert": True},
    )
