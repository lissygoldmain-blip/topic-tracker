from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


class YouTubeAdapter(BaseAdapter):
    """
    Searches YouTube via the Data API v3.
    Requires YOUTUBE_API_KEY environment variable.

    Quota cost: 100 units per search request.
    Free tier: 10,000 units/day → 100 searches/day.
    """

    source_type = "video"

    def __init__(self) -> None:
        self._api_key = os.environ.get("YOUTUBE_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        if not self._api_key:
            logger.warning("YouTubeAdapter: YOUTUBE_API_KEY not set, skipping")
            self._last_failed = True
            return []

        results = []
        for term in source_config.terms:
            try:
                resp = requests.get(
                    YT_SEARCH_URL,
                    params={
                        "part": "snippet",
                        "q": term,
                        "type": "video",
                        "maxResults": 10,
                        "order": "date",
                        "key": self._api_key,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                for item in resp.json().get("items", []):
                    video_id = item.get("id", {}).get("videoId", "")
                    snippet = item.get("snippet", {})
                    raw_date = snippet.get("publishedAt")
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
                            url=f"https://www.youtube.com/watch?v={video_id}",
                            title=snippet.get("title", ""),
                            snippet=snippet.get("description", ""),
                            source="youtube",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning("YouTubeAdapter error for term '%s': %s", term, exc)
                self._last_failed = True
        return results
