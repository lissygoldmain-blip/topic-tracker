"""
eBay Browse API adapter.

Auth: OAuth 2.0 Client Credentials Grant.
Tokens are cached in _token_cache for their full 2-hour lifetime.
"""

import logging
import os
import time
from base64 import b64encode
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

# module-level token cache: key = (client_id, client_secret) -> {"token": str, "expires_at": float}
_token_cache: dict[tuple[str, str], dict] = {}


class EbayAdapter(BaseAdapter):
    source_type = "shopping"

    def __init__(self) -> None:
        self._client_id = os.environ.get("EBAY_CLIENT_ID", "")
        self._client_secret = os.environ.get("EBAY_CLIENT_SECRET", "")
        self._last_failed: bool = False

    def _get_token(self) -> str | None:
        """Return a valid access token, fetching a new one if the cache is stale."""
        cache_key = (self._client_id, self._client_secret)
        cached = _token_cache.get(cache_key)
        if cached and time.time() < cached["expires_at"]:
            return cached["token"]

        credentials = f"{self._client_id}:{self._client_secret}"
        encoded = b64encode(credentials.encode()).decode()
        try:
            resp = requests.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {encoded}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=f"grant_type=client_credentials&scope={SCOPE}",
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("eBay token fetch failed: %s", exc)
            return None

        data = resp.json()
        token = data.get("access_token")
        if not token:
            logger.warning("eBay token response missing access_token: %s", data)
            return None

        expires_in = int(data.get("expires_in", 7200))
        _token_cache[cache_key] = {
            "token": token,
            "expires_at": time.time() + expires_in - 60,  # 60-second buffer
        }
        return token

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        if not self._client_id or not self._client_secret:
            logger.warning("EbayAdapter: EBAY_CLIENT_ID or EBAY_CLIENT_SECRET not set, skipping")
            self._last_failed = True
            return []
        token = self._get_token()
        if not token:
            self._last_failed = True
            return []

        params: dict[str, str | int] = {"q": topic.name, "limit": 20}
        filters = getattr(source_config, "filters", {}) or {}
        if "price_max" in filters:
            params["filter"] = f"price:[..{filters['price_max']}]"

        try:
            resp = requests.get(
                SEARCH_URL,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("eBay search failed for topic '%s': %s", topic.name, exc)
            self._last_failed = True
            return []

        data = resp.json()
        items = data.get("itemSummaries", [])
        results: list[Result] = []
        for item in items:
            price_data = item.get("price")
            price = f'${price_data["value"]} {price_data["currency"]}' if price_data else None
            results.append(
                Result(
                    url=item["itemWebUrl"],
                    title=item["title"],
                    snippet=item.get("shortDescription", ""),
                    source="ebay",
                    source_type=self.source_type,
                    topic_name=topic.name,
                    fetched_at=datetime.now(timezone.utc),
                    price=price,
                    raw=item,
                )
            )
        return results
