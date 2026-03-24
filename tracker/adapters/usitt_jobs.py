from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

USITT_JOBS_URL = "https://www.usitt.org/industry-resources/jobs"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TopicTracker/1.0; +https://github.com)",
    "Accept": "text/html,application/xhtml+xml",
}


class USITTJobsAdapter(BaseAdapter):
    """
    Scrapes USITT's (United States Institute for Theatre Technology) public
    career center. Covers technical theater: TDs, LDs, SDs, scenic, props,
    costume, production management. No key required. Robots.txt permits crawling.

    source_type = "jobs" (30-day dedup window).

    Terms are used for client-side filtering of the fetched listings —
    only jobs whose title or snippet contain any term are returned.
    If no terms, all current listings are returned.
    """

    source_type = "jobs"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        results = []

        try:
            resp = requests.get(USITT_JOBS_URL, headers=_HEADERS, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Webflow CMS collection: jobs live in w-dyn-items lists
            job_items = soup.find_all(class_="avail-jobs_chart-row") or \
                        soup.find_all(class_=lambda c: c and "w-dyn-item" in (c or ""))

            # Also look for featured job tiles
            featured = soup.find_all(class_=lambda c: c and "featured-job" in (c or ""))
            all_items = list(job_items) + [f for f in featured if f not in job_items]

            terms_lower = [t.lower() for t in source_config.terms] if source_config.terms else []

            seen_urls: set[str] = set()
            for item in all_items:
                link_tag = item.find("a", href=True)
                if not link_tag:
                    continue
                href = link_tag["href"]
                if not href.startswith("http"):
                    href = f"https://www.usitt.org{href}"
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                heading = item.find(["h2", "h3", "h4", "h5"])
                title = (
                    heading.get_text(strip=True)
                    if heading
                    else link_tag.get_text(strip=True)
                )
                if not title:
                    continue

                # Collect any paragraph or span text as snippet
                paras = item.find_all(["p", "span"])
                snippet_parts = [
                    p.get_text(strip=True) for p in paras
                    if p.get_text(strip=True) and p.get_text(strip=True) != title
                ]
                snippet = " · ".join(snippet_parts[:3])[:280]

                # Client-side term filtering
                if terms_lower:
                    combined = (title + " " + snippet).lower()
                    if not any(t in combined for t in terms_lower):
                        continue

                results.append(
                    Result(
                        url=href,
                        title=title,
                        snippet=snippet,
                        source="usitt_jobs",
                        source_type=self.source_type,
                        topic_name=topic.name,
                        fetched_at=datetime.now(timezone.utc),
                        raw={},
                    )
                )

        except Exception as exc:
            logger.warning("USITTJobsAdapter error: %s", exc)
            self._last_failed = True

        return results
