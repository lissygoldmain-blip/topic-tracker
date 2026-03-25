"""
Escalation system for topics.

Manages the 'escalations' key inside the state dict (state.json).
All functions mutate `state` in-place. No I/O is performed here.
The poller is responsible for persisting state to disk.

When a result arrives with a tag that matches an escalation trigger,
the topic's urgency is temporarily bumped to a higher level for
`duration_hours`. After that window expires and auto_revert is True,
urgency returns to the original value from topics.yaml.

State shape (nested under state["escalations"][topic_name]):
  {
    "bumped_to":    "urgent",
    "expires_at":   "2026-03-27T12:00:00+00:00",
    "trigger_tag":  "drop_confirmed"
  }
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from tracker.models import Result, TopicConfig

logger = logging.getLogger(__name__)

# Urgency ordering — higher index = higher urgency
_URGENCY_RANK = {"low": 0, "medium": 1, "high": 2, "urgent": 3}


def effective_urgency(state: dict, topic: TopicConfig) -> str:
    """
    Return the topic's current effective urgency, accounting for active escalations.
    If an escalation has expired and auto_revert is True, clears it first.
    """
    entry = _get(state, topic.name)
    if entry is None:
        return topic.urgency

    expires_at = entry.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) >= exp:
                if topic.escalation.get("auto_revert", True):
                    _clear(state, topic.name)
                    logger.info(
                        "Escalation expired for topic '%s' — reverted to '%s'",
                        topic.name, topic.urgency,
                    )
                return topic.urgency
        except (ValueError, TypeError):
            pass

    bumped = entry.get("bumped_to", topic.urgency)
    # Never downgrade — if topic was already higher than the bump, keep original
    if _URGENCY_RANK.get(bumped, 0) > _URGENCY_RANK.get(topic.urgency, 0):
        return bumped
    return topic.urgency


def check_and_apply(state: dict, results: list[tuple[Result, TopicConfig]]) -> None:
    """
    Scan passed results for escalation-triggering tags and apply any matches.
    Call this after Stage1 filtering with the results that passed.
    Mutates state in-place.
    """
    for result, topic in results:
        triggers = topic.escalation.get("triggers", [])
        for trigger in triggers:
            tag = trigger.get("tag")
            if tag and tag in result.tags:
                bump_to = trigger.get("bump_to", topic.urgency)
                duration_hours = float(trigger.get("duration_hours", 24))
                _apply(state, topic.name, bump_to, duration_hours, tag)
                result.escalation_trigger = tag
                break  # first matching trigger wins per result


def _apply(
    state: dict,
    topic_name: str,
    bump_to: str,
    duration_hours: float,
    trigger_tag: str,
) -> None:
    """Record an escalation, extending the window if already escalated to the same level."""
    existing = _get(state, topic_name)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=duration_hours)
    ).isoformat()

    # Only upgrade, never downgrade an existing escalation
    if existing:
        existing_rank = _URGENCY_RANK.get(existing.get("bumped_to", "low"), 0)
        new_rank = _URGENCY_RANK.get(bump_to, 0)
        if new_rank < existing_rank:
            logger.info(
                "Escalation: topic '%s' already at '%s', ignoring lower bump to '%s'",
                topic_name, existing.get("bumped_to"), bump_to,
            )
            return
        # Same level → extend window; higher level → upgrade
        logger.info(
            "Escalation: topic '%s' bumped to '%s' for %.0fh (tag: %s)",
            topic_name, bump_to, duration_hours, trigger_tag,
        )
    else:
        logger.info(
            "Escalation: topic '%s' bumped to '%s' for %.0fh (tag: %s)",
            topic_name, bump_to, duration_hours, trigger_tag,
        )

    state.setdefault("escalations", {})[topic_name] = {
        "bumped_to": bump_to,
        "expires_at": expires_at,
        "trigger_tag": trigger_tag,
    }


def _get(state: dict, topic_name: str) -> dict | None:
    return state.get("escalations", {}).get(topic_name)


def _clear(state: dict, topic_name: str) -> None:
    state.get("escalations", {}).pop(topic_name, None)
