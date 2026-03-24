from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class GDELTAdapter(BaseAdapter):
    """
    Searches the GDELT Project news database via their free DOC 2.0 API.
    No credentials required. Updates every 15 minutes.

    GDELT monitors news from 65 languages across the global media landscape —
    useful for tracking topics in non-English media (e.g. Japanese fashion press).

    Relevant filters (all optional, via source_config.filters):
        timespan:  e.g. "1d", "6h", "30d" (default "1d")
        sourcelang: ISO 639 language code, e.g. "english", "japanese"
        sourcecountry: ISO 3166 country code, e.g. "US", "JP"
    """

    source_type = "news"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        results = []
        for term in source_config.terms:
            try:
                params: dict = {
                    "query": term,
                    "mode": "artlist",
                    "maxrecords": 25,
                    "format": "json",
                    "timespan": source_config.filters.get("timespan", "1d"),
                }
                if "sourcelang" in source_config.filters:
                    params["sourcelang"] = source_config.filters["sourcelang"]
                if "sourcecountry" in source_config.filters:
                    params["sourcecountry"] = source_config.filters["sourcecountry"]

                resp = requests.get(GDELT_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                for article in data.get("articles", []):
                    raw_date = article.get("seendate", "")
                    fetched_at = datetime.now(timezone.utc)
                    if raw_date:
                        try:
                            # GDELT format: "20260323T100000Z"
                            fetched_at = datetime.strptime(
                                raw_date, "%Y%m%dT%H%M%SZ"
                            ).replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                    results.append(
                        Result(
                            url=article.get("url", ""),
                            title=article.get("title", ""),
                            snippet=article.get("domain", ""),
                            source="gdelt",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw=article,
                        )
                    )
            except Exception as exc:
                logger.warning("GDELTAdapter error for term '%s': %s", term, exc)
                self._last_failed = True
        return results
