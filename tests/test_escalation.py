"""Tests for tracker/escalation.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tracker.escalation import check_and_apply, effective_urgency
from tracker.models import Result, TopicConfig


def make_topic(urgency="medium", triggers=None, auto_revert=True):
    return TopicConfig(
        name="Test Topic",
        description="test",
        importance="high",
        urgency=urgency,
        source_categories=["news"],
        polling={},
        notifications={},
        llm_filter={"novelty_threshold": 0.65, "tags": []},
        escalation={
            "triggers": triggers or [],
            "auto_revert": auto_revert,
        },
    )


def make_result(tags=None, url="https://example.com"):
    return Result(
        url=url,
        title="Test",
        snippet="test",
        source="google_news",
        source_type="news",
        topic_name="Test Topic",
        fetched_at=datetime.now(timezone.utc),
        tags=tags or [],
    )


# ─── effective_urgency ───────────────────────────────────────────────────────

def test_no_escalation_returns_topic_urgency():
    state = {}
    topic = make_topic(urgency="low")
    assert effective_urgency(state, topic) == "low"


def test_active_escalation_returns_bumped_urgency():
    state = {
        "escalations": {
            "Test Topic": {
                "bumped_to": "urgent",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                "trigger_tag": "drop_confirmed",
            }
        }
    }
    topic = make_topic(urgency="medium")
    assert effective_urgency(state, topic) == "urgent"


def test_expired_escalation_auto_reverts():
    state = {
        "escalations": {
            "Test Topic": {
                "bumped_to": "urgent",
                "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "trigger_tag": "drop_confirmed",
            }
        }
    }
    topic = make_topic(urgency="medium", auto_revert=True)
    assert effective_urgency(state, topic) == "medium"
    # Entry should be cleared from state
    assert "Test Topic" not in state.get("escalations", {})


def test_expired_escalation_no_auto_revert_keeps_bump():
    state = {
        "escalations": {
            "Test Topic": {
                "bumped_to": "urgent",
                "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "trigger_tag": "drop_confirmed",
            }
        }
    }
    topic = make_topic(urgency="medium", auto_revert=False)
    # Without auto_revert, expired escalation is NOT cleared — stays bumped
    assert effective_urgency(state, topic) == "medium"


def test_bump_lower_than_current_urgency_ignored():
    """If topic is already 'high', a bump to 'medium' should not downgrade."""
    state = {}
    topic = make_topic(urgency="high")
    # Manually put a lower-urgency escalation in state
    state["escalations"] = {
        "Test Topic": {
            "bumped_to": "medium",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "trigger_tag": "some_tag",
        }
    }
    # effective_urgency should return "high" (original), not "medium"
    assert effective_urgency(state, topic) == "high"


# ─── check_and_apply ─────────────────────────────────────────────────────────

def test_matching_tag_triggers_escalation():
    state = {}
    topic = make_topic(
        urgency="medium",
        triggers=[{"tag": "drop_confirmed", "bump_to": "urgent", "duration_hours": 72}],
    )
    result = make_result(tags=["drop_confirmed"])
    check_and_apply(state, [(result, topic)])

    assert state["escalations"]["Test Topic"]["bumped_to"] == "urgent"
    assert result.escalation_trigger == "drop_confirmed"


def test_no_matching_tag_no_escalation():
    state = {}
    topic = make_topic(
        triggers=[{"tag": "drop_confirmed", "bump_to": "urgent", "duration_hours": 72}]
    )
    result = make_result(tags=["noise"])
    check_and_apply(state, [(result, topic)])

    assert "escalations" not in state
    assert result.escalation_trigger is None


def test_first_matching_trigger_wins():
    """When a result has multiple tags, only the first matching trigger applies."""
    state = {}
    topic = make_topic(
        urgency="low",
        triggers=[
            {"tag": "upcoming_drop", "bump_to": "high", "duration_hours": 48},
            {"tag": "drop_confirmed", "bump_to": "urgent", "duration_hours": 72},
        ],
    )
    result = make_result(tags=["upcoming_drop", "drop_confirmed"])
    check_and_apply(state, [(result, topic)])

    assert state["escalations"]["Test Topic"]["bumped_to"] == "high"
    assert result.escalation_trigger == "upcoming_drop"


def test_higher_urgency_upgrade_replaces_lower():
    """A new trigger with higher urgency should upgrade an existing escalation."""
    state = {
        "escalations": {
            "Test Topic": {
                "bumped_to": "high",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                "trigger_tag": "upcoming_drop",
            }
        }
    }
    topic = make_topic(
        triggers=[{"tag": "drop_confirmed", "bump_to": "urgent", "duration_hours": 72}]
    )
    result = make_result(tags=["drop_confirmed"])
    check_and_apply(state, [(result, topic)])

    assert state["escalations"]["Test Topic"]["bumped_to"] == "urgent"


def test_lower_urgency_does_not_downgrade():
    """A new trigger with lower urgency should not replace a higher existing one."""
    state = {
        "escalations": {
            "Test Topic": {
                "bumped_to": "urgent",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                "trigger_tag": "drop_confirmed",
            }
        }
    }
    topic = make_topic(
        triggers=[{"tag": "upcoming_drop", "bump_to": "high", "duration_hours": 48}]
    )
    result = make_result(tags=["upcoming_drop"])
    check_and_apply(state, [(result, topic)])

    # Should still be "urgent", not downgraded to "high"
    assert state["escalations"]["Test Topic"]["bumped_to"] == "urgent"


def test_escalation_duration_stored_correctly():
    state = {}
    topic = make_topic(
        triggers=[{"tag": "drop_confirmed", "bump_to": "urgent", "duration_hours": 72}]
    )
    result = make_result(tags=["drop_confirmed"])

    before = datetime.now(timezone.utc)
    check_and_apply(state, [(result, topic)])
    after = datetime.now(timezone.utc)

    expires = datetime.fromisoformat(state["escalations"]["Test Topic"]["expires_at"])
    assert (expires - before).total_seconds() > 71 * 3600
    assert (expires - after).total_seconds() < 73 * 3600


def test_multiple_topics_escalated_independently():
    state = {}
    topic_a = make_topic(urgency="low")
    topic_a = TopicConfig(
        name="Topic A", description="", importance="low", urgency="low",
        source_categories=[], polling={}, notifications={},
        llm_filter={"novelty_threshold": 0.65, "tags": []},
        escalation={"triggers": [{"tag": "new_listing", "bump_to": "high", "duration_hours": 24}],
                    "auto_revert": True},
    )
    topic_b = TopicConfig(
        name="Topic B", description="", importance="low", urgency="low",
        source_categories=[], polling={}, notifications={},
        llm_filter={"novelty_threshold": 0.65, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )
    result_a = make_result(tags=["new_listing"], url="https://a.com")
    result_a.topic_name = "Topic A"
    result_b = make_result(tags=["noise"], url="https://b.com")
    result_b.topic_name = "Topic B"

    check_and_apply(state, [(result_a, topic_a), (result_b, topic_b)])

    assert "Topic A" in state.get("escalations", {})
    assert "Topic B" not in state.get("escalations", {})
