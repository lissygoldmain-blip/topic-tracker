"""
TMDb (The Movie Database) adapter.

Supports two modes, controlled by source config:

  Discover mode (no terms):
    Rolling window of upcoming releases using /discover/movie + /discover/tv.
    Good for a "what's coming out" feed.
    filters:
      media_type: "movie" | "tv" | "both"  (default: "both")
      days_ahead: int                        (default: 90)
      region: str                            (default: "US")
      language: str                          (default: "en-US")
      max_results: int                       (default: 20 per media type)

  Search mode (terms provided):
    Keyword search via /search/multi — tracks specific titles, franchises,
    studios, or actors. Returns movies and TV shows, skips person results.
    filters:
      language: str  (default: "en-US")

Requires TMDB_API_KEY (Bearer token from themoviedb.org/settings/api).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

_BASE = "https://api.themoviedb.org/3"
_SITE = "https://www.themoviedb.org"


class TMDbAdapter(BaseAdapter):
    source_type = "entertainment"

    def __init__(self) -> None:
        self._api_key = os.environ.get("TMDB_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False

        if not self._api_key:
            logger.warning("TMDB_API_KEY not set — skipping TMDb fetch")
            self._last_failed = True
            return []

        filters = source_config.filters or {}
        media_type = filters.get("media_type", "both")

        try:
            if source_config.terms:
                return self._search(source_config.terms, topic, filters)
            else:
                return self._discover(topic, media_type, filters)
        except Exception as exc:
            logger.warning("TMDb fetch failed: %s", exc)
            self._last_failed = True
            return []

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}

    def _get(self, path: str, params: dict) -> dict:
        resp = requests.get(f"{_BASE}{path}", headers=self._headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── Discover mode ─────────────────────────────────────────────────────────

    def _discover(self, topic: TopicConfig, media_type: str, filters: dict) -> list[Result]:
        days_ahead = int(filters.get("days_ahead", 90))
        today = datetime.now(timezone.utc).date()
        future = today + timedelta(days=days_ahead)
        language = filters.get("language", "en-US")
        region = filters.get("region", "US")
        max_results = int(filters.get("max_results", 20))

        results: list[Result] = []

        if media_type in ("movie", "both"):
            data = self._get("/discover/movie", {
                "primary_release_date.gte": today.isoformat(),
                "primary_release_date.lte": future.isoformat(),
                "sort_by": "primary_release_date.asc",
                "language": language,
                "region": region,
                "page": 1,
            })
            for item in data.get("results", [])[:max_results]:
                results.append(self._movie_result(item, topic))

        if media_type in ("tv", "both"):
            data = self._get("/discover/tv", {
                "first_air_date.gte": today.isoformat(),
                "first_air_date.lte": future.isoformat(),
                "sort_by": "first_air_date.asc",
                "language": language,
                "page": 1,
            })
            for item in data.get("results", [])[:max_results]:
                results.append(self._tv_result(item, topic))

        return results

    # ── Search mode ───────────────────────────────────────────────────────────

    def _search(self, terms: list[str], topic: TopicConfig, filters: dict) -> list[Result]:
        language = filters.get("language", "en-US")
        results: list[Result] = []

        for term in terms:
            data = self._get("/search/multi", {"query": term, "language": language, "page": 1})
            for item in data.get("results", [])[:10]:
                media = item.get("media_type")
                if media == "movie":
                    results.append(self._movie_result(item, topic))
                elif media == "tv":
                    results.append(self._tv_result(item, topic))
                # skip "person" results

        return results

    # ── Result builders ───────────────────────────────────────────────────────

    def _movie_result(self, item: dict, topic: TopicConfig) -> Result:
        item_id = item.get("id", "")
        title = item.get("title", "")
        release_date = item.get("release_date", "")
        overview = item.get("overview", "")

        display_title = f"{title} ({release_date})" if release_date else title
        snippet = overview[:300] if overview else f"Movie · release {release_date}"

        return Result(
            url=f"{_SITE}/movie/{item_id}",
            title=display_title,
            snippet=snippet,
            source="tmdb",
            source_type=self.source_type,
            topic_name=topic.name,
            fetched_at=datetime.now(timezone.utc),
            raw=item,
        )

    def _tv_result(self, item: dict, topic: TopicConfig) -> Result:
        item_id = item.get("id", "")
        title = item.get("name", "")
        air_date = item.get("first_air_date", "")
        overview = item.get("overview", "")

        display_title = f"{title} [TV] ({air_date})" if air_date else f"{title} [TV]"
        snippet = overview[:300] if overview else f"TV premiere · {air_date}"

        return Result(
            url=f"{_SITE}/tv/{item_id}",
            title=display_title,
            snippet=snippet,
            source="tmdb",
            source_type=self.source_type,
            topic_name=topic.name,
            fetched_at=datetime.now(timezone.utc),
            raw=item,
        )
