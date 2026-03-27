from __future__ import annotations

import json
import logging
import re
import time

import google.generativeai as genai

from tracker.models import Result, TopicConfig

logger = logging.getLogger(__name__)

_RETRY_SECONDS_RE = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)

SYSTEM_PROMPT = """You are a news relevance filter. Given a news result and topic description,
assess whether this result contains genuinely new information.

Respond ONLY with valid JSON in this exact format:
{
  "novelty_score": <float 0.0-1.0>,
  "is_relevant": <boolean>,
  "preliminary_tags": [<tags from the provided list only>],
  "reasoning": "<one sentence>"
}

Scoring guide:
- 0.9-1.0: First report of a significant development
- 0.7-0.9: New details not previously reported
- 0.5-0.7: Minor update to known story
- 0.3-0.5: Rehash of existing information
- 0.0-0.3: Pure noise, clickbait, or unrelated"""


class Stage1Filter:
    # Stay comfortably under the 15 req/min free-tier RPM limit.
    # 5s minimum gap → at most 12 req/min.
    _REQUEST_INTERVAL = 5.0

    # Hard cap on items scored across the ENTIRE run (all topics combined) to protect
    # the daily quota (1500 RPD free tier) and prevent RPM spirals on first run when
    # seen_urls.json is empty. With 8 topics × many new items each, per-topic caps are
    # not enough — we need a single budget shared across all filter() calls.
    # At 5s/item this is ~100s of Gemini calls, well within the 45-min job timeout.
    MAX_ITEMS_PER_RUN = 20

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-2.0-flash")
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

    def filter(
        self, items: list[tuple[Result, TopicConfig]]
    ) -> list[tuple[Result, TopicConfig]]:
        """Score each item and return only those above the topic's novelty_threshold."""
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
        for result, topic in items:
            if self._quota_exhausted:
                logger.warning("Stage1: daily quota exhausted — skipping remaining items")
                break
            # Enforce rate limit based on elapsed time since last request.
            # If the Gemini call itself took 4.8s, we only sleep 0.2s more.
            elapsed = time.monotonic() - self._last_request_at
            remaining = self._REQUEST_INTERVAL - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()
            self._items_scored_this_run += 1
            score = self._score(result, topic)
            if score is not None and score >= topic.novelty_threshold:
                result.novelty_score = score
                passed.append((result, topic))
        return passed

    def _score(self, result: Result, topic: TopicConfig) -> float | None:
        prompt = (
            f"Topic: {topic.name}\n"
            f"Description: {topic.description}\n"
            f"Available tags: {topic.tags}\n\n"
            f"Title: {result.title}\n"
            f"Snippet: {result.snippet}\n"
            f"Source: {result.source}"
        )
        for attempt in range(2):
            try:
                response = self._model.generate_content(
                    [SYSTEM_PROMPT, prompt],
                    generation_config={"response_mime_type": "application/json"},
                )
                data = json.loads(response.text)
                return float(data["novelty_score"])
            except (json.JSONDecodeError, KeyError) as e:
                if attempt < 1:
                    logger.warning("Stage1 JSON parse failed, retrying: %s", e)
                    continue
                logger.error(
                    "Stage1 JSON parse failed after retries for '%s', skipping", result.url
                )
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    match = _RETRY_SECONDS_RE.search(error_str)
                    if match:
                        # RPM limit: API told us exactly how long to wait — respect it.
                        wait = float(match.group(1)) + 2
                        logger.warning(
                            "Stage1 RPM limited, waiting %.0fs (attempt %d/2)",
                            wait, attempt + 1,
                        )
                        time.sleep(wait)
                        continue
                    else:
                        # No retry hint = daily quota exhausted, not an RPM blip.
                        # Abort immediately — retrying will just waste minutes per item.
                        logger.warning(
                            "Stage1 daily quota exhausted for '%s' — aborting batch",
                            result.url,
                        )
                        self._quota_exhausted = True
                        return None
                logger.error("Stage1 Gemini API error for '%s': %s", result.url, e)
                break
        return None
