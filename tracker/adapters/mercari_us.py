"""
Mercari adapter using the mercari PyPI package (v2.2.1).

NOTE: Despite the plan name "Mercari US", this library wraps the Mercari Japan API
(api.mercari.jp). Results are Japan listings. This is a known library mismatch from
the original plan — Mercari US has no maintained open-source client.

mercari.search(keywords) returns an iterable of Item objects (not dicts).
Item attributes: .id, .productName, .productURL, .price, .status, .soldOut
"""

import logging
from datetime import datetime, timezone

import mercari as mercari_lib

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)


class MercariUSAdapter(BaseAdapter):
    source_type = "shopping"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        try:
            items = list(mercari_lib.search(topic.name))
        except Exception as exc:
            logger.warning("Mercari search failed for topic '%s': %s", topic.name, exc)
            self._last_failed = True
            return []

        results: list[Result] = []
        for item in items:
            price_raw = getattr(item, "price", None)
            price = f"${price_raw:.2f}" if price_raw is not None else None
            item_id = getattr(item, "id", "")
            url = getattr(item, "productURL", f"https://jp.mercari.com/item/{item_id}")
            title = getattr(item, "productName", "")
            results.append(
                Result(
                    url=url,
                    title=title,
                    snippet="",
                    source="mercari",
                    source_type=self.source_type,
                    topic_name=topic.name,
                    fetched_at=datetime.now(timezone.utc),
                    price=price,
                    raw={"id": item_id, "name": title, "price": price_raw},
                )
            )
        return results
