from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsAdapter(BaseAdapter):
    source_type = "social"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        results = []
        for term in source_config.terms:
            try:
                resp = requests.get(
                    HN_SEARCH_URL,
                    params={"query": term, "tags": "story", "hitsPerPage": 20},
                    timeout=10,
                )
                resp.raise_for_status()
                for hit in resp.json().get("hits", []):
                    object_id = hit.get("objectID", "")
                    url = hit.get("url") or (
                        f"https://news.ycombinator.com/item?id={object_id}"
                    )
                    fetched_at = datetime.now(timezone.utc)
                    raw_date = hit.get("created_at")
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
                            title=hit.get("title", ""),
                            snippet=hit.get("story_text") or "",
                            source="hacker_news",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "HackerNewsAdapter error for term '%s': %s", term, exc
                )
        return results
