from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://slickdeals.net/newsearch.php"
_TIMEOUT = 15


class SlickdealsAdapter(BaseAdapter):
    """
    Searches Slickdeals deal posts via their public RSS search endpoint.
    No credentials required.

    Returns deal threads matching each term in source_config.terms.
    """

    source_type = "shopping"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        results = []
        for term in source_config.terms:
            params = urlencode({
                "mode": "frontpage",
                "searcharea": "deals",
                "q": term,
                "rss": "1",
            })
            url = f"{_SEARCH_URL}?{params}"
            try:
                resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
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
                            source="slickdeals",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=published,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "SlickdealsAdapter error for term '%s': %s", term, exc
                )
        return results
