from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper-search"
S2_PAPER_URL = "https://www.semanticscholar.org/paper/{paper_id}"

# Fields to request from the API
_FIELDS = "title,abstract,authors,year,externalIds,citationCount,url,openAccessPdf,paperId"


class SemanticScholarAdapter(BaseAdapter):
    """
    Searches academic papers via the Semantic Scholar Graph API.

    Works without a key (shared rate limit), but set SEMANTIC_SCHOLAR_API_KEY
    for dedicated 1 RPS (vs the shared 5,000 req/5min pool).
    Apply for a free key at: https://www.semanticscholar.org/product/api

    source_type = "science" (365-day dedup window).

    Useful filters via source_config.filters:
        limit: results per search term (default 20, max 100)
        year:  restrict to a specific publication year (e.g. 2026)
    """

    source_type = "science"

    def __init__(self) -> None:
        self._api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        limit = int(source_config.filters.get("limit", 20))
        year = source_config.filters.get("year")

        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        results: list[Result] = []

        for term in source_config.terms:
            try:
                params: dict = {
                    "query": term,
                    "limit": min(limit, 100),
                    "fields": _FIELDS,
                }
                if year:
                    params["year"] = year

                resp = requests.get(
                    S2_SEARCH_URL, params=params, headers=headers, timeout=15
                )
                resp.raise_for_status()
                data = resp.json()

                for paper in data.get("data", []):
                    title = (paper.get("title") or "").strip()
                    paper_id = paper.get("paperId") or ""
                    abstract = (paper.get("abstract") or "").strip()

                    if not title or not paper_id:
                        continue

                    authors = paper.get("authors") or []
                    author_str = ", ".join(a.get("name", "") for a in authors[:3])
                    if len(authors) > 3:
                        author_str += " et al."

                    year_val = paper.get("year")
                    if year_val:
                        fetched_at = datetime(int(year_val), 1, 1, tzinfo=timezone.utc)
                    else:
                        fetched_at = datetime.now(timezone.utc)

                    snippet = (
                        abstract[:280] + "…" if len(abstract) > 280 else abstract
                    ) if abstract else author_str

                    external = paper.get("externalIds") or {}
                    doi = external.get("DOI", "")

                    # Prefer the paper's own URL if provided, fallback to constructed URL
                    paper_url = paper.get("url") or S2_PAPER_URL.format(paper_id=paper_id)

                    results.append(
                        Result(
                            url=paper_url,
                            title=title,
                            snippet=snippet,
                            source="semantic_scholar",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw={
                                "paperId": paper_id,
                                "doi": doi,
                                "citationCount": paper.get("citationCount"),
                                "openAccessPdf": (paper.get("openAccessPdf") or {}).get("url"),
                            },
                        )
                    )

            except Exception as exc:
                logger.warning(
                    "SemanticScholarAdapter error for term '%s': %s", term, exc
                )
                self._last_failed = True

        return results
