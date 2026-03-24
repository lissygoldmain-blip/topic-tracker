"""
Etsy Open API v3 adapter.

Auth: x-api-key header.
Endpoint: /v3/application/listings/active
"""

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

SEARCH_URL = "https://openapi.etsy.com/v3/application/listings/active"


class EtsyAdapter(BaseAdapter):
    source_type = "shopping"

    def __init__(self) -> None:
        self._api_key = os.environ.get("ETSY_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        if not self._api_key:
            logger.warning("EtsyAdapter: ETSY_API_KEY not set, skipping")
            self._last_failed = True
            return []
        try:
            resp = requests.get(
                SEARCH_URL,
                headers={"x-api-key": self._api_key},
                params={"keywords": topic.name, "limit": 25},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Etsy search failed for topic '%s': %s", topic.name, exc)
            self._last_failed = True
            return []

        data = resp.json()
        items = data.get("results", [])
        results: list[Result] = []
        for item in items:
            price_data = item.get("price")
            if price_data:
                amount = price_data["amount"] / price_data["divisor"]
                price = f'${amount:.2f} {price_data["currency_code"]}'
            else:
                price = None
            results.append(
                Result(
                    url=item["url"],
                    title=item["title"],
                    snippet=item.get("description", "")[:200],
                    source="etsy",
                    source_type=self.source_type,
                    topic_name=topic.name,
                    fetched_at=datetime.now(timezone.utc),
                    price=price,
                    raw=item,
                )
            )
        return results
