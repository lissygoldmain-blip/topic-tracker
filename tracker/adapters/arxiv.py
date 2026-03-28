from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_TIMEOUT = 15
ARXIV_ABS_URL = "https://arxiv.org/abs/{arxiv_id}"


class ArxivAdapter(BaseAdapter):
    """
    Searches arXiv preprints via the public Atom API (no key required).

    source_type = "science" (365-day dedup window).

    Useful filters via source_config.filters:
        max_results: max per term (default 20)
        categories:  list of arXiv subject codes to AND into the query
                     e.g. ["cs.AI", "q-bio.GN", "econ.GN"]
        sort_by:     "submittedDate" (default) | "relevance" | "lastUpdatedDate"
    """

    source_type = "science"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        max_results = source_config.filters.get("max_results", 20)
        sort_by = source_config.filters.get("sort_by", "submittedDate")
        categories: list[str] = source_config.filters.get("categories", [])
        results = []

        for term in source_config.terms:
            try:
                # Build query: combine free-text term with category filters
                query = f"all:{term}"
                if categories:
                    cat_clause = " OR ".join(f"cat:{c}" for c in categories)
                    query = f"({query}) AND ({cat_clause})"

                params = urlencode({
                    "search_query": query,
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": sort_by,
                    "sortOrder": "descending",
                })
                url = f"{ARXIV_API_URL}?{params}"

                resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
                if feed.bozo and not feed.entries:
                    logger.warning("ArxivAdapter: feedparser error for term '%s'", term)
                    self._last_failed = True
                    continue

                for entry in feed.entries:
                    arxiv_id = entry.get("id", "").split("/abs/")[-1].strip()
                    if not arxiv_id:
                        continue

                    title = entry.get("title", "").replace("\n", " ").strip()
                    summary = entry.get("summary", "").replace("\n", " ").strip()
                    # Truncate long abstracts for the snippet
                    snippet = summary[:280] + "…" if len(summary) > 280 else summary

                    authors = entry.get("authors", [])
                    author_str = ", ".join(a.get("name", "") for a in authors[:3])
                    if len(authors) > 3:
                        author_str += " et al."

                    # Parse published date from entry
                    published = entry.get("published_parsed")
                    if published:
                        fetched_at = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        fetched_at = datetime.now(timezone.utc)

                    # Collect arXiv subject category tags
                    tags = [t.get("term", "") for t in entry.get("tags", [])]
                    cat_str = ", ".join(t for t in tags if t)

                    results.append(
                        Result(
                            url=ARXIV_ABS_URL.format(arxiv_id=arxiv_id),
                            title=title,
                            snippet=f"{author_str} — {cat_str}" if cat_str else snippet,
                            source="arxiv",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw={"id": arxiv_id, "summary": summary, "authors": author_str},
                        )
                    )
            except Exception as exc:
                logger.warning("ArxivAdapter error for term '%s': %s", term, exc)
                self._last_failed = True

        return results
