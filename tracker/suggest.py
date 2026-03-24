"""
tracker/suggest.py
──────────────────
Source Suggester: given a topic name and description, uses Gemini Flash
to recommend polling sources from the verified sources library, then
renders ready-to-paste YAML polling blocks.

Usage (as a library):
    from tracker.suggest import suggest_sources
    yaml_output = suggest_sources("My Topic", "description here", api_key="...")

Usage (CLI wrapper): see suggest.py at the project root.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import google.generativeai as genai
import yaml

logger = logging.getLogger(__name__)

_LIBRARY_PATH = Path(__file__).parent / "sources_library.yaml"

_SYSTEM_PROMPT = """\
You are a source recommendation engine for a personal topic-monitoring tool.
The tool polls news, science, shopping, social, and RSS sources on a schedule.

You will be given:
  1. A TOPIC (name + description)
  2. A SOURCES LIBRARY — a YAML catalog of every available adapter with its
     category tags, credential requirements, and usage notes.

Your job:
  - Select the 3–8 most relevant sources from the library for this topic.
  - For each source, provide ready-to-use polling config in YAML format.
  - Assign each source to exactly one tier: frequent, discovery, or broad.
    · frequent  → high-signal, low-noise, check often (e.g. RSS for a niche beat)
    · discovery → broad keyword searches across many outlets
    · broad     → background awareness, infrequent (e.g. GDELT, global news)
  - Generate 2–4 specific, effective search terms per source.
  - For RSS sources, include a filters.feeds list with real, verified feed URLs
    (only use feeds listed in the sources library).
  - For science/medicine topics, prefer pubmed and arxiv.
  - For NYC/local topics, prefer rss with NYC feeds, reddit, and bluesky.
  - Do NOT invent sources not in the library.
  - Do NOT include credentials in the output.

Respond ONLY with valid JSON in this exact format:
{
  "reasoning": "<1-2 sentence explanation of your source choices>",
  "polling": {
    "frequent": [
      {
        "source": "<adapter key>",
        "terms": ["<term1>", "<term2>"],
        "filters": {}
      }
    ],
    "discovery": [...],
    "broad": [...]
  }
}

Omit any tier that has zero sources. Keep filters as an empty object {} if
no filters are needed. For RSS, always include filters.feeds as a list.
"""


def _load_library() -> str:
    """Load and return the sources library YAML as a string."""
    return _LIBRARY_PATH.read_text()


def suggest_sources(
    topic_name: str,
    description: str,
    api_key: str | None = None,
) -> str:
    """
    Ask Gemini Flash to recommend polling sources for the given topic.

    Returns a YAML string ready to paste into topics.yaml under `polling:`.
    Raises ValueError if the API key is missing or the LLM call fails.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("GEMINI_API_KEY is required for source suggestions.")

    genai.configure(api_key=key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    library_yaml = _load_library()

    user_prompt = (
        f"TOPIC NAME: {topic_name}\n"
        f"TOPIC DESCRIPTION: {description}\n\n"
        f"SOURCES LIBRARY:\n{library_yaml}"
    )

    try:
        response = model.generate_content(
            [_SYSTEM_PROMPT, user_prompt],
            generation_config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Gemini API error: {exc}") from exc

    reasoning = data.get("reasoning", "")
    polling = data.get("polling", {})

    return _render_yaml(topic_name, description, reasoning, polling)


def _render_yaml(
    topic_name: str,
    description: str,
    reasoning: str,
    polling: dict,
) -> str:
    """Convert the LLM JSON response into a ready-to-paste YAML polling block."""
    lines = [
        f"# ── Suggested sources for: {topic_name} ──────────────────────────",
        f"# {reasoning}",
        "#",
        "# Paste the block below under your topic's  polling:  key in topics.yaml",
        "# Then review terms and filters before committing.",
        "",
        "polling:",
    ]

    tier_order = ["frequent", "discovery", "broad"]
    for tier in tier_order:
        entries = polling.get(tier)
        if not entries:
            continue
        lines.append(f"  {tier}:")
        for entry in entries:
            source = entry.get("source", "unknown")
            terms = entry.get("terms", [])
            filters = entry.get("filters", {})

            lines.append(f"    - source: {source}")
            if terms:
                lines.append("      terms:")
                for t in terms:
                    lines.append(f"        - \"{t}\"")
            if filters:
                # Render filters with proper indentation
                filter_yaml = yaml.dump(
                    {"filters": filters}, default_flow_style=False
                ).strip()
                for fl in filter_yaml.split("\n"):
                    lines.append(f"      {fl}")

    return "\n".join(lines) + "\n"
