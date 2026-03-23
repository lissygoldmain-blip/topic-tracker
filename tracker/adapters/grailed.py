"""
Grailed adapter using the grailed_api PyPI package (v0.1.5).

Actual API: GrailedAPIClient.find_products(query_search=..., hits_per_page=..., sold=False)
Returns list of dicts. Key fields: id (int), title (str), price (int, USD dollars),
slug (may be None).
URL constructed as: https://www.grailed.com/listings/{id}
"""

import logging
from datetime import datetime, timezone

from grailed_api import GrailedAPIClient

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)


class GrailedAdapter(BaseAdapter):
    source_type = "shopping"

    def __init__(self) -> None:
        self._client = GrailedAPIClient()
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        try:
            items = self._client.find_products(
                query_search=topic.name,
                hits_per_page=20,
                sold=False,
            )
        except Exception as exc:
            logger.warning("Grailed search failed for topic '%s': %s", topic.name, exc)
            self._last_failed = True
            return []

        results: list[Result] = []
        for item in items:
            price_raw = item.get("price")
            price = f"${price_raw:.2f}" if price_raw is not None else None
            item_id = item.get("id", "")
            url = f"https://www.grailed.com/listings/{item_id}"
            results.append(
                Result(
                    url=url,
                    title=item.get("title", ""),
                    snippet=", ".join(item.get("designer_names", [])) or "",
                    source="grailed",
                    source_type=self.source_type,
                    topic_name=topic.name,
                    fetched_at=datetime.now(timezone.utc),
                    price=price,
                    raw=item,
                )
            )
        return results
