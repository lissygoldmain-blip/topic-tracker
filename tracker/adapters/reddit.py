from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

_AGENT = "topic-tracker/1.0 (personal use; contact via GitHub)"
_SUBREDDIT_RSS = "https://www.reddit.com/r/{subreddit}/new.rss"
_SEARCH_RSS = "https://www.reddit.com/search.rss"


class RedditAdapter(BaseAdapter):
    """
    Reads Reddit via public RSS feeds — no credentials required.

    Subreddit feeds: fetches /new.rss for each entry in source_config.subreddits.
    Keyword search:  fetches /search.rss?q={term}&sort=new for each term.
    """

    source_type = "social"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        results = []

        for subreddit in source_config.subreddits:
            url = _SUBREDDIT_RSS.format(subreddit=subreddit)
            results.extend(self._parse_feed(url, topic))

        for term in source_config.terms:
            url = f"{_SEARCH_RSS}?q={term}&sort=new&limit=25"
            results.extend(self._parse_feed(url, topic))

        return results

    def _parse_feed(self, url: str, topic: TopicConfig) -> list[Result]:
        try:
            feed = feedparser.parse(url, agent=_AGENT)
            out = []
            for entry in feed.entries:
                published = datetime.now(timezone.utc)
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(
                        *entry.published_parsed[:6], tzinfo=timezone.utc
                    )
                out.append(
                    Result(
                        url=getattr(entry, "link", ""),
                        title=getattr(entry, "title", ""),
                        snippet=getattr(entry, "summary", ""),
                        source="reddit",
                        source_type=self.source_type,
                        topic_name=topic.name,
                        fetched_at=published,
                    )
                )
            return out
        except Exception as exc:
            logger.warning("RedditAdapter error for '%s': %s", url, exc)
            return []
