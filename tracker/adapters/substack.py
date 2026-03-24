from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

# Substack's undocumented public search endpoint — no auth required
_SEARCH_URL = "https://substack.com/api/v1/search"
_FEED_URL = "https://{handle}.substack.com/feed"


class SubstackAdapter(BaseAdapter):
    """
    Discovers and reads Substack newsletters by topic.

    Two modes:

    1. Discovery mode (terms provided):
       Searches Substack for publications matching each term, then fetches
       the RSS feed from the top matching newsletters. Good for finding new
       voices automatically.

    2. Direct mode (filters.feeds provided):
       Reads specific Substack RSS feeds directly, bypassing search.
       Equivalent to GenericRSSAdapter but labeled as "substack" source.

    source_type = "feeds" (90-day dedup window).

    Useful filters via source_config.filters:
        feeds:         list of full Substack RSS URLs (direct mode)
        max_pubs:      max publications to read per search term (default 5)
        max_per_feed:  max articles per newsletter (default 10)
    """

    source_type = "feeds"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False

        direct_feeds: list[str] = source_config.filters.get("feeds", [])
        max_per_feed = int(source_config.filters.get("max_per_feed", 10))
        if direct_feeds:
            return self._read_feeds(direct_feeds, topic, max_per_feed=max_per_feed)

        # Discovery mode: search for publications matching each term
        max_pubs = int(source_config.filters.get("max_pubs", 5))

        feed_urls: list[str] = []
        seen_handles: set[str] = set()

        for term in source_config.terms:
            try:
                resp = requests.get(
                    _SEARCH_URL,
                    params={"q": term, "type": "publication"},
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                resp.raise_for_status()
                data = resp.json()

                # Response is a list of publication objects; handle is in
                # the 'subdomain' field (the part before .substack.com)
                publications = data if isinstance(data, list) else data.get("publications", [])
                count = 0
                for pub in publications:
                    handle = pub.get("subdomain") or pub.get("handle") or pub.get("slug")
                    if not handle or handle in seen_handles:
                        continue
                    seen_handles.add(handle)
                    feed_urls.append(_FEED_URL.format(handle=handle))
                    count += 1
                    if count >= max_pubs:
                        break

            except Exception as exc:
                logger.warning("SubstackAdapter search error for term '%s': %s", term, exc)
                self._last_failed = True

        return self._read_feeds(feed_urls, topic, max_per_feed=max_per_feed)

    def _read_feeds(
        self, feed_urls: list[str], topic: TopicConfig, max_per_feed: int = 10
    ) -> list[Result]:
        results: list[Result] = []
        for url in feed_urls:
            try:
                feed = feedparser.parse(url)
                if feed.bozo and not feed.entries:
                    logger.warning("SubstackAdapter: bad feed at '%s'", url)
                    continue

                # Extract newsletter name from feed metadata
                newsletter_name = getattr(feed.feed, "title", url)

                for entry in feed.entries[:max_per_feed]:
                    pub_parsed = getattr(entry, "published_parsed", None)
                    published = (
                        datetime(*pub_parsed[:6], tzinfo=timezone.utc)
                        if pub_parsed
                        else datetime.now(timezone.utc)
                    )
                    link = getattr(entry, "link", "")
                    title = getattr(entry, "title", "")
                    summary = getattr(entry, "summary", "")
                    if not link or not title:
                        continue
                    results.append(
                        Result(
                            url=link,
                            title=title,
                            snippet=summary[:280] + "…" if len(summary) > 280 else summary,
                            source="substack",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=published,
                            raw={"newsletter": newsletter_name, "feed_url": url},
                        )
                    )
            except Exception as exc:
                logger.warning("SubstackAdapter feed error for '%s': %s", url, exc)
                self._last_failed = True

        return results
