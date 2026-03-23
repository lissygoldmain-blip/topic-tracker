from __future__ import annotations

import json
import logging

import google.generativeai as genai

from tracker.models import Result, TopicConfig

logger = logging.getLogger(__name__)

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
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-2.0-flash")

    def filter(
        self, items: list[tuple[Result, TopicConfig]]
    ) -> list[tuple[Result, TopicConfig]]:
        """Score each item and return only those above the topic's novelty_threshold."""
        passed = []
        for result, topic in items:
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
                if attempt == 0:
                    logger.warning("Stage1 JSON parse failed, retrying: %s", e)
                    continue
                logger.error(
                    "Stage1 JSON parse failed after retry for '%s', skipping", result.url
                )
            except Exception as e:
                logger.error("Stage1 Gemini API error for '%s': %s", result.url, e)
                break
        return None
