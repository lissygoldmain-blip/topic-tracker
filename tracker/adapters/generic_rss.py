from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

_TIMEOUT = 15


class GenericRSSAdapter(BaseAdapter):
    """
    Reads any RSS/Atom feed URL. Feed URLs are specified either via
    source_config.filters['feeds'] (list of URLs) or source_config.terms
    (each term treated as a feed URL).

    Useful for brand blogs, newsletters, Substacks, or any source that
    publishes an RSS/Atom feed.
    """

    source_type = "feeds"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        feed_urls: list[str] = (
            source_config.filters.get("feeds") or source_config.terms
        )
        results = []
        for url in feed_urls:
            try:
                response = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                feed = feedparser.parse(response.content)
                now = datetime.now(timezone.utc)
                for entry in feed.entries:
                    published_at = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published_at = datetime(
                            *entry.published_parsed[:6], tzinfo=timezone.utc
                        )
                    results.append(
                        Result(
                            url=getattr(entry, "link", ""),
                            title=getattr(entry, "title", ""),
                            snippet=getattr(entry, "summary", ""),
                            source="rss",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=now,
                            published_at=published_at,
                        )
                    )
            except Exception as exc:
                logger.warning("GenericRSSAdapter error for '%s': %s", url, exc)
        return results
