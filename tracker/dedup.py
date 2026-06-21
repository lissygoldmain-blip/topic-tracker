"""Collapse near-duplicate story pile-ons in the results index.

Lissy's "browse" pain was repetition: the same story as a piece, a follow-up, and
a follow-up quoting the follow-up. This clusters near-identical titles and keeps the
single best-scored item per cluster.

Scope: only news-like source types are deduped. Jobs/shopping titles are templated
("Production Coordinator — <org>") so title overlap there would wrongly merge distinct
listings; those are already de-duplicated by URL via seen_urls.json.

ponytail: naive O(n^2) per-topic, normalized-title token-overlap clustering. Fine for the
~100-items-per-topic index. Upgrade to MinHash/LSH only if the index grows ~10x.
"""
from __future__ import annotations

import re

# Source types where story pile-ons happen and titles describe the same event.
DEDUP_TYPES = {"news", "feeds", "social", "entertainment", "science"}

_WORD_RE = re.compile(r"[a-z0-9]+")
# Common words that shouldn't drive similarity (kept small — over-stripping merges distinct stories).
_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "at", "by", "is",
    "are", "with", "from", "as", "new", "this", "that", "its", "it", "be", "has",
    "was", "will", "how", "why", "what", "who",
}


def _tokens(title: str) -> set[str]:
    return {w for w in _WORD_RE.findall((title or "").lower()) if len(w) > 2 and w not in _STOP}


def _similar(a: set[str], b: set[str], threshold: float) -> bool:
    # Overlap coefficient: intersection / size of the smaller set. Robust to one title
    # being a longer "follow-up" elaboration of the other.
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= threshold


def dedup_results(results: list[dict], threshold: float = 0.6, score_key: str = "novelty_score") -> list[dict]:
    """Return results with near-duplicate news-like items collapsed to the highest-scored
    of each cluster. Non-dedupable types (jobs/shopping/etc.) always pass through. Order is
    preserved by first appearance; downstream views re-sort anyway."""
    kept: list[dict] = []
    kept_tokens: list[set[str] | None] = []  # None ⇒ never matches (passthrough item)
    for r in results:
        if r.get("source_type") not in DEDUP_TYPES:
            kept.append(r)
            kept_tokens.append(None)
            continue
        toks = _tokens(r.get("title", ""))
        dup_idx = next(
            (i for i, kt in enumerate(kept_tokens) if kt is not None and _similar(toks, kt, threshold)),
            None,
        )
        if dup_idx is None:
            kept.append(r)
            kept_tokens.append(toks)
        elif (r.get(score_key) or 0) > (kept[dup_idx].get(score_key) or 0):
            kept[dup_idx] = r
            kept_tokens[dup_idx] = toks
    return kept


if __name__ == "__main__":
    # ponytail self-check: the smallest thing that fails if the logic breaks.
    def N(title, score=0.5, st="news", url=None):
        return {"title": title, "novelty_score": score, "source_type": st, "url": url or title}

    # 1. Two obituaries of the same person collapse, higher score kept.
    out = dedup_results([
        N("James Burrows Dies: Legendary TV Comedy Director", 0.90),
        N("James Burrows, Legendary Sitcom Director Who Shaped Half a Century", 0.95),
    ])
    assert len(out) == 1, out
    assert out[0]["novelty_score"] == 0.95, "should keep the higher-scored of a cluster"

    # 2. Distinct news stories are NOT merged.
    out = dedup_results([N("David Hockney dies at 87"), N("James Burrows dies at 84")])
    assert len(out) == 2, out

    # 3. Templated job listings (non-dedupable type) always pass through, even if similar.
    out = dedup_results([
        N("Production Coordinator - Lincoln Center", st="jobs"),
        N("Production Coordinator - BAM", st="jobs"),
    ])
    assert len(out) == 2, "jobs must not be title-deduped"

    # 4. Exact-repost news collapses.
    out = dedup_results([N("ICE raid reported in Jackson Heights", 0.4),
                         N("ICE raid reported in Jackson Heights", 0.6)])
    assert len(out) == 1 and out[0]["novelty_score"] == 0.6

    print("dedup self-check passed")
