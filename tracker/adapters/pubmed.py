from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

# Month abbreviation → number for date parsing
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_pubmed_date(pubdate: str) -> datetime:
    """Parse PubMed pubdate strings like '2026 Mar 23', '2026 Mar', '2026'."""
    parts = pubdate.strip().split()
    try:
        year = int(parts[0])
        month = _MONTHS.get(parts[1].lower()[:3], 1) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return datetime.now(timezone.utc)


class PubMedAdapter(BaseAdapter):
    """
    Searches PubMed via NCBI E-utilities (free, no key required for ≤3 req/sec).
    Set NCBI_API_KEY env var to raise limit to 10 req/sec.

    source_type = "science" (365-day dedup window — research stays relevant).

    Useful filters via source_config.filters:
        retmax: max results per term (default 20)
        sort:   "date" (default) | "relevance" | "pub+date"
    """

    source_type = "science"

    def __init__(self) -> None:
        self._api_key = os.environ.get("NCBI_API_KEY", "")
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        retmax = source_config.filters.get("retmax", 20)
        sort = source_config.filters.get("sort", "date")
        results = []

        for term in source_config.terms:
            try:
                # Step 1: search for PMIDs
                search_params: dict = {
                    "db": "pubmed",
                    "term": term,
                    "retmax": retmax,
                    "sort": sort,
                    "retmode": "json",
                }
                if self._api_key:
                    search_params["api_key"] = self._api_key

                search_resp = requests.get(
                    ESEARCH_URL, params=search_params, timeout=15
                )
                search_resp.raise_for_status()
                pmids = search_resp.json()["esearchresult"]["idlist"]
                if not pmids:
                    continue

                # Step 2: fetch summaries for those PMIDs
                summary_params: dict = {
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "retmode": "json",
                }
                if self._api_key:
                    summary_params["api_key"] = self._api_key

                summary_resp = requests.get(
                    ESUMMARY_URL, params=summary_params, timeout=15
                )
                summary_resp.raise_for_status()
                summary_data = summary_resp.json().get("result", {})

                for pmid in pmids:
                    doc = summary_data.get(pmid)
                    if not doc or not isinstance(doc, dict):
                        continue
                    title = doc.get("title", "")
                    source_name = doc.get("source", "")
                    pubdate = doc.get("pubdate", "")
                    fetched_at = (
                        _parse_pubmed_date(pubdate) if pubdate else datetime.now(timezone.utc)
                    )
                    authors = doc.get("authors", [])
                    author_str = ", ".join(
                        a.get("name", "") for a in authors[:3]
                    )
                    if len(authors) > 3:
                        author_str += " et al."
                    results.append(
                        Result(
                            url=PUBMED_URL.format(pmid=pmid),
                            title=title,
                            snippet=f"{author_str} — {source_name}" if author_str else source_name,
                            source="pubmed",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                            raw=doc,
                        )
                    )
            except Exception as exc:
                logger.warning("PubMedAdapter error for term '%s': %s", term, exc)
                self._last_failed = True

        return results
