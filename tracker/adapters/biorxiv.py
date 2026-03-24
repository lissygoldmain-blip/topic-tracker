from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

DETAILS_URL = "https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}/json"
PAPER_URL = "https://www.{server}.org/content/{doi}"

# bioRxiv API returns 100 papers per page
_PAGE_SIZE = 100


class BioRxivAdapter(BaseAdapter):
    """
    Fetches recent preprints from bioRxiv and medRxiv via the public details API.

    Handles both servers — use source: "biorxiv" or source: "medrxiv" in topics.yaml.
    No API key required.

    source_type = "science" (365-day dedup window).

    Useful filters via source_config.filters:
        days_back:   how many days to look back (default 7)
        max_results: cap on returned results (default 30)

    If source_config.terms are provided, papers are filtered client-side:
    any term must appear (case-insensitive) in the title or abstract.
    If no terms are given, all papers in the date window are returned (up to max_results).
    """

    source_type = "science"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        server = source_config.source  # "biorxiv" or "medrxiv"
        days_back = int(source_config.filters.get("days_back", 7))
        max_results = int(source_config.filters.get("max_results", 30))

        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        results: list[Result] = []
        cursor = 0

        try:
            while len(results) < max_results:
                url = DETAILS_URL.format(
                    server=server,
                    start=start_date,
                    end=end_date,
                    cursor=cursor,
                )
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                collection = data.get("collection", [])
                if not collection:
                    break

                for paper in collection:
                    if len(results) >= max_results:
                        break

                    title = paper.get("title", "")
                    abstract = paper.get("abstract", "")
                    doi = paper.get("doi", "")

                    if not title or not doi:
                        continue

                    # Client-side keyword filter: any term must appear in title or abstract
                    if source_config.terms:
                        text = (title + " " + abstract).lower()
                        if not any(t.lower() in text for t in source_config.terms):
                            continue

                    # Authors: semicolon-separated string in this API
                    raw_authors = paper.get("authors", "")
                    author_list = [a.strip() for a in raw_authors.split(";") if a.strip()]
                    author_display = ", ".join(author_list[:3])
                    if len(author_list) > 3:
                        author_display += " et al."

                    date_str = paper.get("date", "")
                    try:
                        fetched_at = datetime.strptime(date_str, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                    except (ValueError, TypeError):
                        fetched_at = datetime.now(timezone.utc)

                    snippet = (
                        abstract[:280] + "…" if len(abstract) > 280 else abstract
                    ) if abstract else author_display

                    results.append(
                        Result(
                            url=PAPER_URL.format(server=server, doi=doi),
                            title=title,
                            snippet=snippet,
                            source=server,
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw={
                                "doi": doi,
                                "category": paper.get("category", ""),
                                "authors": raw_authors,
                                "server": server,
                            },
                        )
                    )

                # Check if there are more pages (total count > cursor + page_size)
                messages = data.get("messages", [])
                total = int(messages[0].get("count", 0)) if messages else 0
                if cursor + _PAGE_SIZE >= total:
                    break
                cursor += _PAGE_SIZE

        except Exception as exc:
            logger.warning("BioRxivAdapter error for server '%s': %s", server, exc)
            self._last_failed = True

        return results
