from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

INDEED_RSS_URL = "https://www.indeed.com/rss"
_HTML_TAG = re.compile(r"<[^>]+>")


class IndeedAdapter(BaseAdapter):
    """
    Searches Indeed job listings via their public RSS feed (no key required).

    source_type = "jobs" (30-day dedup window — listings go stale fast).

    Useful filters via source_config.filters:
        location:  location string (default "New York, NY")
        radius:    miles radius (default 25)
        fromage:   max days since posting (default 14)
        jt:        job type — fulltime | parttime | contract | internship | temporary
        sort:      "date" (default) | "relevance"
        limit:     results per term (default 25, max 25)
    """

    source_type = "jobs"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        location = source_config.filters.get("location", "New York, NY")
        radius = source_config.filters.get("radius", 25)
        fromage = source_config.filters.get("fromage", 14)
        jt = source_config.filters.get("jt", "")
        sort = source_config.filters.get("sort", "date")
        limit = min(source_config.filters.get("limit", 25), 25)
        results = []

        for term in source_config.terms:
            try:
                params: dict = {
                    "q": term,
                    "l": location,
                    "sort": sort,
                    "limit": limit,
                    "fromage": fromage,
                    "radius": radius,
                }
                if jt:
                    params["jt"] = jt

                url = f"{INDEED_RSS_URL}?{urlencode(params)}"
                feed = feedparser.parse(url)

                if feed.bozo and not feed.entries:
                    logger.warning("IndeedAdapter: feedparser error for term '%s'", term)
                    self._last_failed = True
                    continue

                for entry in feed.entries:
                    link = entry.get("link", "")
                    if not link:
                        continue

                    title = entry.get("title", "").strip()
                    raw_summary = entry.get("summary", "")
                    snippet = _HTML_TAG.sub("", raw_summary).strip()
                    snippet = snippet[:280] + "…" if len(snippet) > 280 else snippet

                    published = entry.get("published_parsed")
                    fetched_at = (
                        datetime(*published[:6], tzinfo=timezone.utc)
                        if published
                        else datetime.now(timezone.utc)
                    )

                    results.append(
                        Result(
                            url=link,
                            title=title,
                            snippet=snippet,
                            source="indeed",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw={"summary": raw_summary},
                        )
                    )
            except Exception as exc:
                logger.warning("IndeedAdapter error for term '%s': %s", term, exc)
                self._last_failed = True

        return results
