from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

PLAYBILL_JOBS_URL = "https://playbill.com/jobs"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TopicTracker/1.0; +https://github.com)",
    "Accept": "text/html,application/xhtml+xml",
}


class PlaybillJobsAdapter(BaseAdapter):
    """
    Scrapes Playbill's public job listings page.
    No key required. Robots.txt permits crawling.

    source_type = "jobs" (30-day dedup window).

    Useful filters via source_config.filters:
        category:  job category filter (e.g. "Stage Management", "Production")
        state:     US state abbreviation (e.g. "NY")
        is_union:  "1" to filter to union jobs only

    Terms are used as keyword searches (passed as ?q= to the page).
    If no terms, fetches the full recent listings.
    """

    source_type = "jobs"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        results = []

        terms = source_config.terms if source_config.terms else [""]

        for term in terms:
            try:
                params: dict = {}
                if term:
                    params["q"] = term
                if "category" in source_config.filters:
                    params["category"] = source_config.filters["category"]
                if "state" in source_config.filters:
                    params["state"] = source_config.filters["state"]
                if "is_union" in source_config.filters:
                    params["isUnion"] = source_config.filters["is_union"]

                resp = requests.get(
                    PLAYBILL_JOBS_URL, params=params, headers=_HEADERS, timeout=15
                )
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                container = soup.find(id="job-listings") or soup.find(
                    class_="job-listings"
                )
                if not container:
                    # Fallback: look for any element with "job" tiles
                    container = soup.find("main") or soup

                tiles = container.find_all(
                    class_=lambda c: c and "pb-tile-tag-job" in c
                ) if container else []

                # Also try generic article/li job entries as fallback
                if not tiles:
                    tiles = container.find_all(
                        attrs={"data-entity-type": "job"}
                    ) if container else []

                seen_urls: set[str] = set()
                for tile in tiles:
                    link_tag = tile.find("a", href=True)
                    if not link_tag:
                        continue
                    href = link_tag["href"]
                    if not href.startswith("http"):
                        href = f"https://playbill.com{href}"
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    # Title: prefer heading tags, fall back to link text
                    heading = tile.find(["h2", "h3", "h4"])
                    title = (
                        heading.get_text(strip=True)
                        if heading
                        else link_tag.get_text(strip=True)
                    )
                    if not title:
                        continue

                    # Snippet: any paragraph or description-like text in the tile
                    desc_tag = tile.find("p") or tile.find(
                        class_=lambda c: c and "desc" in (c or "")
                    )
                    snippet = desc_tag.get_text(strip=True) if desc_tag else ""

                    # Company / location metadata
                    meta_tags = tile.find_all(class_=lambda c: c and any(
                        k in (c or "") for k in ("company", "location", "org", "meta")
                    ))
                    meta_str = " · ".join(
                        t.get_text(strip=True) for t in meta_tags if t.get_text(strip=True)
                    )
                    if meta_str and not snippet:
                        snippet = meta_str
                    elif meta_str:
                        snippet = f"{meta_str} — {snippet}"

                    results.append(
                        Result(
                            url=href,
                            title=title,
                            snippet=snippet[:280],
                            source="playbill_jobs",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=datetime.now(timezone.utc),
                            raw={},
                        )
                    )

            except Exception as exc:
                logger.warning("PlaybillJobsAdapter error for term '%s': %s", term, exc)
                self._last_failed = True

        return results
