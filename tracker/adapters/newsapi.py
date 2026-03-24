from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

NEWSAPI_URL = "https://newsapi.org/v2/everything"


class NewsAPIAdapter(BaseAdapter):
    """
    Fetches news articles via NewsAPI.org.
    Requires NEWSAPI_KEY environment variable.

    Free developer tier: 100 requests/day, 1-month article history.
    Register at https://newsapi.org/register
    """

    source_type = "news"

    def __init__(self) -> None:
        self._api_key = os.environ.get("NEWSAPI_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        if not self._api_key:
            logger.warning("NewsAPIAdapter: NEWSAPI_KEY not set, skipping")
            self._last_failed = True
            return []

        results = []
        for term in source_config.terms:
            try:
                resp = requests.get(
                    NEWSAPI_URL,
                    params={
                        "q": term,
                        "sortBy": "publishedAt",
                        "pageSize": 20,
                        "apiKey": self._api_key,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                for article in resp.json().get("articles", []):
                    raw_date = article.get("publishedAt")
                    fetched_at = datetime.now(timezone.utc)
                    if raw_date:
                        try:
                            fetched_at = datetime.fromisoformat(
                                raw_date.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                    source_name = article.get("source", {}).get("name", "newsapi")
                    results.append(
                        Result(
                            url=article.get("url", ""),
                            title=article.get("title", ""),
                            snippet=article.get("description", "") or "",
                            source=f"newsapi:{source_name}",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning("NewsAPIAdapter error for term '%s': %s", term, exc)
                self._last_failed = True
        return results
