from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

GUARDIAN_URL = "https://content.guardianapis.com/search"


class GuardianAdapter(BaseAdapter):
    """
    Searches The Guardian via their Content API.
    Requires GUARDIAN_API_KEY (free at open-platform.theguardian.com,
    ~12 requests/second, effectively unlimited daily).

    Optional filters via source_config.filters:
        section: e.g. "fashion", "technology", "us-news"
        from_date: ISO date string, e.g. "2026-01-01"
    """

    source_type = "news"

    def __init__(self) -> None:
        self._api_key = os.environ.get("GUARDIAN_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        if not self._api_key:
            logger.warning("GuardianAdapter: GUARDIAN_API_KEY not set, skipping")
            self._last_failed = True
            return []

        results = []
        for term in source_config.terms:
            try:
                params: dict = {
                    "q": term,
                    "api-key": self._api_key,
                    "show-fields": "trailText",
                    "order-by": "newest",
                    "page-size": 20,
                }
                if "section" in source_config.filters:
                    params["section"] = source_config.filters["section"]
                if "from_date" in source_config.filters:
                    params["from-date"] = source_config.filters["from_date"]

                resp = requests.get(GUARDIAN_URL, params=params, timeout=15)
                resp.raise_for_status()
                items = resp.json().get("response", {}).get("results", [])
                for item in items:
                    raw_date = item.get("webPublicationDate", "")
                    fetched_at = datetime.now(timezone.utc)
                    if raw_date:
                        try:
                            fetched_at = datetime.fromisoformat(
                                raw_date.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                    section = item.get("sectionName", "")
                    source_label = f"guardian:{section}" if section else "guardian"
                    trail = (item.get("fields") or {}).get("trailText", "") or ""
                    results.append(
                        Result(
                            url=item.get("webUrl", ""),
                            title=item.get("webTitle", ""),
                            snippet=trail,
                            source=source_label,
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning("GuardianAdapter error for term '%s': %s", term, exc)
                self._last_failed = True
        return results
