from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceConfig:
    source: str
    terms: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    subreddits: list[str] = field(default_factory=list)


@dataclass
class Result:
    url: str
    title: str
    snippet: str
    source: str           # e.g. "google_news", "ebay"
    source_type: str      # "news", "shopping", "social", "video", "feeds"
    topic_name: str
    fetched_at: datetime

    # Shopping adapters
    price: str | None = None

    # Set by LLM pipeline
    novelty_score: float | None = None
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    escalation_trigger: str | None = None
    action_url: str | None = None

    # Raw source data
    raw: dict = field(default_factory=dict)

    # Notification tracking
    notified_push: bool = False
    notified_digest: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Result":
        fetched_at = data.get("fetched_at")
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at)
        elif fetched_at is None:
            fetched_at = datetime.now()
        return cls(
            url=data["url"],
            title=data["title"],
            snippet=data.get("snippet", ""),
            source=data["source"],
            source_type=data["source_type"],
            topic_name=data["topic_name"],
            fetched_at=fetched_at,
            price=data.get("price"),
            novelty_score=data.get("novelty_score"),
            summary=data.get("summary"),
            tags=data.get("tags", []),
            escalation_trigger=data.get("escalation_trigger"),
            action_url=data.get("action_url"),
            notified_push=data.get("notified_push", False),
            notified_digest=data.get("notified_digest", False),
        )

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source": self.source,
            "source_type": self.source_type,
            "topic_name": self.topic_name,
            "fetched_at": self.fetched_at.isoformat(),
            "price": self.price,
            "novelty_score": self.novelty_score,
            "summary": self.summary,
            "tags": self.tags,
            "escalation_trigger": self.escalation_trigger,
            "action_url": self.action_url,
            "notified_push": self.notified_push,
            "notified_digest": self.notified_digest,
        }


@dataclass
class TopicConfig:
    name: str
    description: str
    importance: str       # "high" | "low"
    urgency: str          # "urgent" | "high" | "medium" | "low"
    source_categories: list[str]
    polling: dict[str, list[dict]]
    notifications: dict[str, Any]
    llm_filter: dict[str, Any]
    escalation: dict[str, Any]

    def sources_for_tier(self, tier: str) -> list[SourceConfig]:
        """Return SourceConfig objects for the given tier name ('frequent'|'discovery'|'broad')."""
        raw = self.polling.get(tier, [])
        return [SourceConfig(**entry) for entry in raw]

    @property
    def novelty_threshold(self) -> float:
        return self.llm_filter.get("novelty_threshold", 0.65)

    @property
    def novelty_push_threshold(self) -> float:
        return self.notifications.get("novelty_push_threshold", 0.7)

    @property
    def tags(self) -> list[str]:
        return self.llm_filter.get("tags", [])
