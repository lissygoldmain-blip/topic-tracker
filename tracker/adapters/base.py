from __future__ import annotations

from abc import ABC, abstractmethod

from tracker.models import Result, SourceConfig, TopicConfig


class BaseAdapter(ABC):
    """All source adapters implement this interface."""

    source_type: str = "feeds"  # override in subclasses

    @abstractmethod
    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        """Fetch raw results for one source config entry. Must not raise on transient errors —
        log and return empty list instead."""
        ...
