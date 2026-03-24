from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


class AdzunaAdapter(BaseAdapter):
    """
    Searches Adzuna job listings via their free REST API.
    Adzuna aggregates from LinkedIn, Indeed, company pages, and 1000s of other
    boards — the closest legitimate path to LinkedIn job search coverage.

    source_type = "jobs" (30-day dedup window).

    Requires env vars:
        ADZUNA_APP_ID   — from developer.adzuna.com (free)
        ADZUNA_APP_KEY  — from developer.adzuna.com (free, 50k req/month)

    Useful filters via source_config.filters:
        location:        location string (default "New York")
        country:         ISO country code (default "us")
        results_per_page: max results per term (default 20)
        sort_by:         "date" (default) | "relevance" | "salary"
        max_days_old:    max days since posting (default 14)
        full_time:       1 to restrict to full-time only
        part_time:       1 to restrict to part-time only
        contract:        1 to restrict to contract only
        salary_min:      minimum salary filter
    """

    source_type = "jobs"

    def __init__(self) -> None:
        self._app_id = os.environ.get("ADZUNA_APP_ID", "")
        self._app_key = os.environ.get("ADZUNA_APP_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False

        if not self._app_id or not self._app_key:
            logger.warning("AdzunaAdapter: ADZUNA_APP_ID or ADZUNA_APP_KEY not set, skipping")
            self._last_failed = True
            return []

        country = source_config.filters.get("country", "us")
        location = source_config.filters.get("location", "New York")
        results_per_page = source_config.filters.get("results_per_page", 20)
        sort_by = source_config.filters.get("sort_by", "date")
        max_days_old = source_config.filters.get("max_days_old", 14)
        results = []

        for term in source_config.terms:
            try:
                params: dict = {
                    "app_id": self._app_id,
                    "app_key": self._app_key,
                    "what": term,
                    "where": location,
                    "results_per_page": results_per_page,
                    "sort_by": sort_by,
                    "max_days_old": max_days_old,
                    "content-type": "application/json",
                }
                # Pass through optional job-type filters
                for flag in ("full_time", "part_time", "contract", "salary_min"):
                    if flag in source_config.filters:
                        params[flag] = source_config.filters[flag]

                resp = requests.get(
                    ADZUNA_URL.format(country=country),
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                for job in data.get("results", []):
                    url = job.get("redirect_url", "")
                    if not url:
                        continue

                    title = job.get("title", "").strip()
                    company = job.get("company", {}).get("display_name", "")
                    description = job.get("description", "").strip()
                    snippet = description[:280] + "…" if len(description) > 280 else description
                    if company:
                        snippet = f"{company} — {snippet}" if snippet else company

                    created = job.get("created", "")
                    try:
                        fetched_at = datetime.fromisoformat(
                            created.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        fetched_at = datetime.now(timezone.utc)

                    salary_min = job.get("salary_min")
                    salary_max = job.get("salary_max")
                    salary_str = ""
                    if salary_min and salary_max:
                        salary_str = f" · ${salary_min:,.0f}–${salary_max:,.0f}"
                    elif salary_min:
                        salary_str = f" · ${salary_min:,.0f}+"

                    results.append(
                        Result(
                            url=url,
                            title=f"{title}{salary_str}",
                            snippet=snippet,
                            source="adzuna",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw=job,
                        )
                    )
            except Exception as exc:
                logger.warning("AdzunaAdapter error for term '%s': %s", term, exc)
                self._last_failed = True

        return results
