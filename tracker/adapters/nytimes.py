from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

NYT_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"

# Free tier: 5 requests/minute — pace multi-term fetches conservatively
_REQUEST_DELAY_SECS = 13  # ~4.5 req/min, safely under the 5/min cap


class NYTimesAdapter(BaseAdapter):
    """
    Searches NYTimes articles via the Article Search API v2.
    Requires NYTIMES_API_KEY (free at developer.nytimes.com, 500 req/day).

    Rate limit: 5 requests/minute — the adapter adds a short delay between
    terms to stay safely under the cap.
    """

    source_type = "news"

    def __init__(self) -> None:
        self._api_key = os.environ.get("NYTIMES_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        if not self._api_key:
            logger.warning("NYTimesAdapter: NYTIMES_API_KEY not set, skipping")
            self._last_failed = True
            return []

        results = []
        for i, term in enumerate(source_config.terms):
            if i > 0:
                time.sleep(_REQUEST_DELAY_SECS)
            try:
                resp = requests.get(
                    NYT_URL,
                    params={
                        "q": term,
                        "sort": "newest",
                        "fl": "headline,abstract,web_url,pub_date,section_name",
                        "api-key": self._api_key,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                docs = resp.json().get("response", {}).get("docs", [])
                for doc in docs:
                    raw_date = doc.get("pub_date", "")
                    fetched_at = datetime.now(timezone.utc)
                    if raw_date:
                        try:
                            fetched_at = datetime.fromisoformat(
                                raw_date.replace("+0000", "+00:00")
                            )
                        except ValueError:
                            pass
                    section = doc.get("section_name", "")
                    source_label = f"nytimes:{section}" if section else "nytimes"
                    results.append(
                        Result(
                            url=doc.get("web_url", ""),
                            title=doc.get("headline", {}).get("main", ""),
                            snippet=doc.get("abstract", "") or "",
                            source=source_label,
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning("NYTimesAdapter error for term '%s': %s", term, exc)
                self._last_failed = True
        return results
