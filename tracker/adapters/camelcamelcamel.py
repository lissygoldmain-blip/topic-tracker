from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

_CCC_RSS = "https://camelcamelcamel.com/product/{asin}.rss"
_AGENT = "topic-tracker/1.0 (personal price tracking)"


class CamelCamelCamelAdapter(BaseAdapter):
    """
    Tracks Amazon price drops via CamelCamelCamel RSS feeds.
    No credentials required — uses public per-ASIN RSS feeds.

    Configure ASINs in source_config.filters['asins'] (list of strings).
    ASINs are the 10-character Amazon product identifiers, e.g. "B09XXXXX".

    Example topics.yaml entry:
        - source: camelcamelcamel
          filters:
            asins:
              - B09XXXXXXX
              - B0AXXXXXXX
    """

    source_type = "shopping"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        asins: list[str] = source_config.filters.get("asins", [])
        results = []
        for asin in asins:
            url = _CCC_RSS.format(asin=asin)
            try:
                feed = feedparser.parse(url, agent=_AGENT)
                for entry in feed.entries:
                    published = datetime.now(timezone.utc)
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(
                            *entry.published_parsed[:6], tzinfo=timezone.utc
                        )
                    results.append(
                        Result(
                            url=getattr(entry, "link", ""),
                            title=getattr(entry, "title", ""),
                            snippet=getattr(entry, "summary", ""),
                            source="camelcamelcamel",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=published,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "CamelCamelCamelAdapter error for ASIN '%s': %s", asin, exc
                )
        return results
