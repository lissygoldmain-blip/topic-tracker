from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

BSKY_SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"


class BlueskyAdapter(BaseAdapter):
    """
    Searches Bluesky posts via the public AT Protocol AppView.
    No credentials required — unauthenticated search on public posts.
    """

    source_type = "social"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        results = []
        for term in source_config.terms:
            try:
                resp = requests.get(
                    BSKY_SEARCH_URL,
                    params={"q": term, "limit": 25},
                    timeout=10,
                )
                resp.raise_for_status()
                for post in resp.json().get("posts", []):
                    handle = post.get("author", {}).get("handle", "")
                    uri = post.get("uri", "")
                    rkey = uri.rsplit("/", 1)[-1] if uri else ""
                    url = (
                        f"https://bsky.app/profile/{handle}/post/{rkey}"
                        if handle and rkey
                        else ""
                    )
                    record = post.get("record", {})
                    text = record.get("text", "")
                    raw_date = record.get("createdAt") or post.get("indexedAt")
                    fetched_at = datetime.now(timezone.utc)
                    if raw_date:
                        try:
                            fetched_at = datetime.fromisoformat(
                                raw_date.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                    results.append(
                        Result(
                            url=url,
                            title=text[:120] + ("…" if len(text) > 120 else ""),
                            snippet=text,
                            source="bluesky",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning("BlueskyAdapter error for term '%s': %s", term, exc)
        return results
