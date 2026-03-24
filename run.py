#!/usr/bin/env python3
"""
Local test runner. Loads .env if present, then runs one poll tier.

Usage:
    python run.py [tier_index] [topics_path]

Examples:
    python run.py          # tier 0 (frequent), topics.yaml
    python run.py 1        # tier 1 (discovery)
    python run.py 0 dev.yaml
"""
import os
import sys
from pathlib import Path

# Load .env for local development (never committed, not used in GitHub Actions)
_env = Path(".env")
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

from tracker.poller import run_poll  # noqa: E402

try:
    tier = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if tier not in (0, 1, 2, 3):
        raise ValueError
except ValueError:
    print("Usage: python run.py [0|1|2|3] [topics_path]", file=sys.stderr)
    sys.exit(1)

topics = sys.argv[2] if len(sys.argv) > 2 else "topics.yaml"
run_poll(tier_index=tier, topics_path=topics)
