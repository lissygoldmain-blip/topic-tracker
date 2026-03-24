#!/usr/bin/env python3
"""
suggest.py — Source Suggester CLI
──────────────────────────────────
Given a topic name and description, recommends polling sources and outputs
ready-to-paste YAML for topics.yaml.

Usage:
    python suggest.py "My Topic" "Description of what I want to track"
    python suggest.py "Sickle cell gene therapy" "Latest clinical trial results and FDA approvals"
    python suggest.py "Jackson Heights restaurants" "New openings and reviews in Queens"

Requires GEMINI_API_KEY in .env or environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env if present
_env = Path(".env")
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from tracker.suggest import suggest_sources  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    topic_name = sys.argv[1]
    description = " ".join(sys.argv[2:])

    print(f"\n🔍 Generating source suggestions for: {topic_name!r}\n")

    try:
        result = suggest_sources(topic_name, description)
        print(result)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
