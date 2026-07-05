from __future__ import annotations

import json
import logging
import os
import re
import time

import google.generativeai as genai

from tracker.models import Result, TopicConfig

logger = logging.getLogger(__name__)

_RETRY_SECONDS_RE = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)

_SCORING_GUIDE = """Set "relevant" false when the item falls outside the topic's stated interests or matches its
deprioritize/skip guidance. Score "novelty_score" as how worth-surfacing the item is:
- 0.85-1.0: squarely matches the stated interests AND is a significant new development
- 0.65-0.85: matches the interests; moderately new or useful
- 0.45-0.65: tangentially relevant, or a minor update to a known story
- 0.0-0.45: off-intent, deprioritized, rehash, clickbait, or noise"""

SYSTEM_PROMPT = f"""You decide whether a result is worth surfacing to a user who defined a tracking topic.

You are given the topic's description, which states what the user CARES ABOUT and often what to
DEPRIORITIZE or SKIP. Honor it. An item can be brand-new and still NOT worth surfacing if it does
not match the user's stated interests -- for example an obituary of someone outside the topic's
focus, a film or franchise the description says to deprioritize, or reaction/punditry the user said
to skip. Judge relevance to the stated intent FIRST, then significance and newness.

Respond ONLY with valid JSON in this exact format:
{{
  "relevant": <boolean>,
  "novelty_score": <float 0.0-1.0>,
  "preliminary_tags": [<tags from the provided list only>],
  "reasoning": "<one sentence>"
}}

{_SCORING_GUIDE}"""

BATCH_SYSTEM_PROMPT = f"""You decide which of several results are worth surfacing to a user who defined a tracking topic.

You are given the topic's description, which states what the user CARES ABOUT and often what to
DEPRIORITIZE or SKIP. Honor it. An item can be brand-new and still NOT worth surfacing if it does
not match the user's stated interests. Judge relevance to the stated intent FIRST, then
significance and newness. Score every item independently on its own merits.

The items are numbered. Respond ONLY with a valid JSON array containing EXACTLY one object per
item, in this exact format:
[
  {{
    "index": <int, the item's number>,
    "relevant": <boolean>,
    "novelty_score": <float 0.0-1.0>,
    "preliminary_tags": [<tags from the provided list only>],
    "reasoning": "<one sentence>"
  }}
]

{_SCORING_GUIDE}

If an item covers the same story or event as an earlier item in this list (or in the
already-accepted list, if provided), score its novelty_score below 0.4 regardless of source."""


class Stage1Filter:
    # Stay comfortably under the 15 req/min free-tier RPM limit.
    # 5s minimum gap → at most 12 req/min.
    _REQUEST_INTERVAL = 5.0

    # Items scored per Gemini call. Batching is the free-tier throughput unlock:
    # the quota that binds is requests/day, not tokens, so 8 items per request
    # scores 8x the items for the same quota. Kept modest so flash-lite reliably
    # returns a well-formed array; malformed batches fall back to per-item calls.
    BATCH_SIZE = 8

    # Hard cap on items scored across the ENTIRE run (all topics combined) to protect
    # the daily quota (1500 RPD free tier) and prevent RPM spirals on first run when
    # seen_urls.json is empty. With batching this costs ~ceil(N/8) requests.
    MAX_ITEMS_PER_RUN = 20

    def __init__(self, api_key: str, max_items_per_run: int | None = None, feedback: list | None = None):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-2.5-flash-lite")
        # Feedback from feedback.json — list of {url, title, topic, vote, note, ts}
        self._feedback: list = feedback or []
        # Tracks when the last Gemini request was made (monotonic seconds).
        # Initialised to 0 so the very first call never waits.
        self._last_request_at: float = 0.0
        # Set to True when a 429 with no retry hint is received, indicating
        # daily quota exhaustion (not just RPM throttling). When set, the
        # batch is aborted immediately rather than retrying each item for minutes.
        self._quota_exhausted: bool = False
        # Global counter across ALL filter() calls in this run. Compared against
        # MAX_ITEMS_PER_RUN so the cap applies to the full run, not per topic.
        self._items_scored_this_run: int = 0
        # Allow the cap to be tuned without a code change: constructor param takes
        # precedence (useful in tests), then STAGE1_MAX_ITEMS_PER_RUN env var,
        # then the class-level default of 20.
        if max_items_per_run is not None:
            self.MAX_ITEMS_PER_RUN = max_items_per_run
        elif "STAGE1_MAX_ITEMS_PER_RUN" in os.environ:
            self.MAX_ITEMS_PER_RUN = int(os.environ["STAGE1_MAX_ITEMS_PER_RUN"])

    def filter(
        self, items: list[tuple[Result, TopicConfig]]
    ) -> list[tuple[Result, TopicConfig]]:
        """Score each item and return only those above the topic's novelty_threshold.

        Items are scored in batches of BATCH_SIZE per Gemini call; a malformed
        batch response falls back to one call per item for that chunk.
        """
        remaining_budget = self.MAX_ITEMS_PER_RUN - self._items_scored_this_run
        if remaining_budget <= 0:
            logger.info(
                "Stage1: global run cap of %d reached — skipping %d items",
                self.MAX_ITEMS_PER_RUN, len(items),
            )
            return []
        if len(items) > remaining_budget:
            logger.warning(
                "Stage1: %d items but only %d slots remain in run cap — deferring excess",
                len(items), remaining_budget,
            )
            items = items[:remaining_budget]

        passed = []
        # Titles of items that have already passed this run, per topic.
        # Injected into subsequent prompts so Gemini can score near-duplicates low.
        passed_titles: list[str] = []

        # ponytail: chunk within same-topic runs (the poller calls filter() once per
        # topic anyway); a chunk shares one topic so the prompt has one description.
        i = 0
        while i < len(items):
            if self._quota_exhausted:
                logger.warning("Stage1: daily quota exhausted — skipping remaining items")
                break
            topic = items[i][1]
            chunk = [items[i]]
            while (
                len(chunk) < self.BATCH_SIZE
                and i + len(chunk) < len(items)
                and items[i + len(chunk)][1].name == topic.name
            ):
                chunk.append(items[i + len(chunk)])
            i += len(chunk)

            scores = self._score_chunk(chunk, topic, passed_titles)
            for (result, t), score in zip(chunk, scores):
                if score is not None and score >= t.novelty_threshold:
                    result.novelty_score = score
                    passed.append((result, t))
                    passed_titles.append(result.title)
        return passed

    def _score_chunk(
        self,
        chunk: list[tuple[Result, TopicConfig]],
        topic: TopicConfig,
        passed_titles: list[str],
    ) -> list[float | None]:
        """Score a same-topic chunk: one batch call, per-item fallback on failure."""
        if len(chunk) == 1:
            self._throttle()
            self._items_scored_this_run += 1
            return [self._score(chunk[0][0], topic, passed_titles=passed_titles)]

        self._throttle()
        self._items_scored_this_run += len(chunk)
        batch_scores = self._score_batch(chunk, topic, passed_titles)
        if batch_scores is not None:
            return batch_scores

        # Batch response unusable — fall back to one call per item (old behavior).
        logger.warning("Stage1: batch scoring failed for %d items — falling back to per-item", len(chunk))
        scores: list[float | None] = []
        for result, t in chunk:
            if self._quota_exhausted:
                scores.append(None)
                continue
            self._throttle()
            scores.append(self._score(result, t, passed_titles=passed_titles))
        return scores

    def _throttle(self) -> None:
        # Enforce rate limit based on elapsed time since last request.
        # If the Gemini call itself took 4.8s, we only sleep 0.2s more.
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._REQUEST_INTERVAL - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    # ── prompt building ──────────────────────────────────────────────────────

    def _feedback_text(self, topic: TopicConfig) -> str:
        """User preference history for this topic (most recent 8 votes)."""
        topic_fb = [f for f in self._feedback if f.get("topic") == topic.name]
        if not topic_fb:
            return ""
        lines = []
        for fb in topic_fb[-8:]:
            sign = "\U0001f44d" if fb.get("vote") == 1 else "\U0001f44e"
            title_trunc = str(fb.get("title", ""))[:70]
            note = f' — "{fb["note"]}"' if fb.get("note") else ""
            lines.append(f'{sign} "{title_trunc}"{note}')
        return (
            "\n\nUser preference history for this topic (use to calibrate your scoring):\n"
            + "\n".join(lines)
        )

    @staticmethod
    def _dedup_text(passed_titles: list[str]) -> str:
        """Already-accepted titles — Gemini should score near-duplicates low."""
        if not passed_titles:
            return ""
        listed = "\n".join(f"- {t[:80]}" for t in passed_titles[-15:])
        return (
            "\n\nAlready accepted in this batch (same topic, this run):\n"
            + listed
            + "\nIf an item covers the same story or event as any of the above, "
            "score its novelty_score below 0.4 regardless of source."
        )

    @staticmethod
    def _topic_header(topic: TopicConfig) -> str:
        return (
            f"Topic: {topic.name}\n"
            f"Description: {topic.description}\n"
            f"Available tags: {topic.tags}\n\n"
        )

    # ── Gemini plumbing ──────────────────────────────────────────────────────

    def _generate_json(self, system_prompt: str, prompt: str, context: str):
        """One Gemini call with retry/429 handling. Returns parsed JSON or None."""
        for attempt in range(3):
            try:
                response = self._model.generate_content(
                    [system_prompt, prompt],
                    generation_config={"response_mime_type": "application/json"},
                )
                return json.loads(response.text)
            except json.JSONDecodeError as e:
                if attempt < 2:
                    logger.warning("Stage1 JSON parse failed, retrying: %s", e)
                    continue
                logger.error("Stage1 JSON parse failed after retries for %s, skipping", context)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    match = _RETRY_SECONDS_RE.search(error_str)
                    if match:
                        wait = float(match.group(1)) + 2
                        if wait > 300:
                            # Retry hint > 5 min = RPD exhausted (resets at UTC midnight).
                            logger.warning("Stage1 quota exhausted for %s — aborting batch", context)
                            self._quota_exhausted = True
                            return None
                        if attempt < 2:
                            # Short retry hint = RPM pressure. Wait and retry (up to 3×).
                            logger.warning(
                                "Stage1 RPM limited, waiting %.0fs (attempt %d/3)",
                                wait, attempt + 1,
                            )
                            time.sleep(wait)
                            continue
                    # No retry hint, or all 3 attempts exhausted — treat as RPD exhausted.
                    logger.warning("Stage1 quota exhausted for %s — aborting batch", context)
                    self._quota_exhausted = True
                    return None
                logger.error("Stage1 Gemini API error for %s: %s", context, e)
                break
        return None

    @staticmethod
    def _gate(entry: dict) -> float:
        """Extract the score, applying the hard relevance gate: an off-intent item
        never ranks high no matter how "new" (this is what stops the
        obituary/Marvel/punditry pile-up at the top)."""
        score = float(entry["novelty_score"])
        if not entry.get("relevant", True):
            score = min(score, 0.2)
        return score

    # ── scoring paths ────────────────────────────────────────────────────────

    def _score(self, result: Result, topic: TopicConfig, passed_titles: list[str] | None = None) -> float | None:
        prompt = (
            self._topic_header(topic)
            + f"Title: {result.title}\n"
            f"Snippet: {result.snippet}\n"
            f"Source: {result.source}"
            + self._feedback_text(topic)
            + self._dedup_text(passed_titles or [])
        )
        data = self._generate_json(SYSTEM_PROMPT, prompt, context=f"'{result.url}'")
        if data is None:
            return None
        try:
            return self._gate(data)
        except (KeyError, TypeError, ValueError) as e:
            logger.error("Stage1 malformed response for '%s': %s", result.url, e)
            return None

    def _score_batch(
        self,
        chunk: list[tuple[Result, TopicConfig]],
        topic: TopicConfig,
        passed_titles: list[str],
    ) -> list[float | None] | None:
        """Score a same-topic chunk in ONE Gemini call. Returns a score per item
        (None for items the model skipped), or None if the whole response is unusable."""
        item_lines = []
        for n, (result, _t) in enumerate(chunk):
            item_lines.append(
                f"Item {n}:\n"
                f"  Title: {result.title}\n"
                f"  Snippet: {(result.snippet or '')[:400]}\n"
                f"  Source: {result.source}"
            )
        prompt = (
            self._topic_header(topic)
            + "\n\n".join(item_lines)
            + self._feedback_text(topic)
            + self._dedup_text(passed_titles)
        )
        data = self._generate_json(
            BATCH_SYSTEM_PROMPT, prompt, context=f"batch of {len(chunk)} ({topic.name})"
        )
        if not isinstance(data, list):
            return None

        scores: list[float | None] = [None] * len(chunk)
        matched = 0
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry["index"])
                if not 0 <= idx < len(chunk):
                    continue
                scores[idx] = self._gate(entry)
                matched += 1
            except (KeyError, TypeError, ValueError):
                continue
        # If the model matched under half the items, treat the response as garbage
        # and let the caller fall back to per-item scoring.
        if matched < max(1, len(chunk) // 2):
            logger.warning(
                "Stage1 batch response matched only %d/%d items — discarding", matched, len(chunk)
            )
            return None
        return scores
