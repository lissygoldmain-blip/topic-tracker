from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
_TIMEOUT = 15


class GoogleNewsAdapter(BaseAdapter):
    source_type = "news"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        results = []
        for term in source_config.terms:
            try:
                params = urlencode({"q": term, "hl": "en-US", "gl": "US", "ceid": "US:en"})
                url = f"{GOOGLE_NEWS_URL}?{params}"
                response = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                feed = feedparser.parse(response.content)
                for entry in feed.entries:
                    published = datetime.now(timezone.utc)
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    results.append(
                        Result(
                            url=getattr(entry, "link", ""),
                            title=getattr(entry, "title", ""),
                            snippet=getattr(entry, "summary", ""),
                            source="google_news",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=published,
                        )
                    )
            except Exception as e:
                logger.warning("GoogleNewsAdapter error for term '%s': %s", term, e)
        return results
